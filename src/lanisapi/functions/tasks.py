"""This script includes classes and functions about the 'Mein Unterricht' page."""

from datetime import datetime
from urllib.parse import urljoin
from collections import defaultdict

from attrs import define, field
from selectolax.parser import HTMLParser

from ..constants import LOGGER, URL
from ..exceptions import CriticalElementWasNotFoundError
from ..helpers.cryptor import Cryptor
from ..helpers.html_logger import HTMLLogger
from ..helpers.request import Request


@define
class Task:
    """The "Mein Unterricht" page in a data type. Expect many parameters to be `None`.

    Parameters
    ----------
    title : str
        Name of the task.
    date : datetime.datetime
        Creation date of the task.
    subject_name : str
        Subject of the task often with the class name and weird ids at the end,
        like "Chemie 7GA (071CH01-GYM)"
    teacher : str
        Abbreviation of the teacher.
    description : str
        Optional description of the task.
    details : str
        ``details`` is the blue button with a comment symbol that sometimes appears.
    attachment : list[str]
        List of the attachments names.
    attachment_url : str
        Download link to a zip file containing all attachments.
    """

    title: field(type=str)
    date: field(type=datetime)
    subject_name: field(type=str)
    teacher: field(type=str)
    details: field(type=str)
    homework: field(type=str)
    done: field(type=bool)
    attachment: field(factory=list, type=list[str])
    attachment_url: field(type=str)
    course_id: field(type=int)
    entry_id: field(type=str)

@define
class Attendance:
    course: field(type=str)
    teacher: field(type=str)
    present: field(type=int)        # anwesend
    excused: field(type=int)        # entschuldigt
    leaved: field(type=int)         # beurlaubt
    other_event: field(type=int)    # andere schulische Veranstaltung
    absent: field(type=int)         # fehlende


def _get_tasks() -> list[Task]:
    """Return all tasks from the "Mein Unterricht" page with downloads in .zip format.

    Returns
    -------
    list[Task]
    """
    # Unfortunately there is no API for us.
    response = Request.get(URL.tasks)

    html = HTMLParser(response.text)

    elements = html.css("#aktuellTable tr.printable")

    # Parse page to get all tasks. Also report suspicious missing elements.
    task_list = []
    for element in elements:
        if not element:
            HTMLLogger.log_missing_element(
                html.html, "get_task()", elements.index(element), "element"
            )
            msg = "Critical task element was not found, something is definitely wrong! Please file a bug with the html_logs.txt file."
            raise CriticalElementWasNotFoundError(msg)

        # Name of task.
        title_element = element.css_first("b.thema")
        try:
            title = title_element.text()
        except AttributeError:
            LOGGER.warning(
                "Get tasks: No task name found, possibly wrong css selector? Please file a bug with the html_logs.txt file."
            )
            HTMLLogger.log_missing_element(
                element.html, "get_task()", elements.index(element), "title"
            )
            title = None

        # Date it was given.
        date_element = element.css_first("small span.datum")
        try:
            date = datetime.strptime(date_element.text(), "%d.%m.%Y")
        except AttributeError:
            LOGGER.warning(
                "Get tasks: No date found, possibly wrong css selector? Please file a bug with the html_logs.txt file."
            )
            HTMLLogger.log_missing_element(
                element.html, "get_task()", elements.index(element), "date"
            )
            date = None

        course_id = element.attributes.get('data-book', None)
        entry_id = element.attributes.get('data-entry', None)


        # Homework, sometimes there is none, so maybe there is text under the details button.
        homework_element = element.css_first("div.markup.text.realHomework")
        try:
            homework = homework_element.text()
        except AttributeError:
            homework = None

        done = None if homework is None else element.css_first(".undone") is None

        # Details, hidden under the the blue button with the message symbol.
        details_element = element.css_first("div.inhalt span.markup")
        try:
            details = details_element.text()
        except AttributeError:
            details = None

        # Subject (with weird suffixes sometimes).
        subject_element = element.css_first("h3 span")
        try:
            subject = subject_element.text()
        except AttributeError:
            LOGGER.warning(
                "Get tasks: No subject name found, possibly wrong css selector? Please file a bug with the html_logs.txt file."
            )
            HTMLLogger.log_missing_element(
                element.html, "get_task()", elements.index(element), "subject"
            )
            subject = None

        # Teacher
        teacher_element = element.css_first("span.teacher button")
        try:
            teacher = teacher_element.attributes["title"]
        except AttributeError:
            LOGGER.warning(
                "Get tasks: No teacher name found, possibly wrong css selector? Please file a bug with the html_logs.txt file."
            )
            HTMLLogger.log_missing_element(
                element.html, "get_task()", elements.index(element), "teacher"
            )
            teacher = None

        # List of all attachment names.
        attachments = []
        attachment_elements = element.css("a.file")
        for attachment_element in attachment_elements:
            attachments.append(attachment_element.attributes["data-file"])

        # The url of a zip containing all attachments.
        attachment_url_element = element.css_first(
            "div.btn-group.files ul.dropdown-menu li:last-child a"
        )
        try:
            attachment_url = urljoin(
                URL.base, attachment_url_element.attributes["href"]
            )
        except AttributeError:
            attachment_url = None

        # Map everything together to `Task`.
        task_data = Task(
            title=title,
            date=date,
            subject_name=subject,
            teacher=teacher,
            homework=homework,
            done=done,
            details=details,
            attachment=attachments,
            attachment_url=attachment_url,
            course_id=course_id,
            entry_id=entry_id
        )

        task_list.append(task_data)

    LOGGER.info("Get tasks: Successfully got tasks.")

    return task_list

def _get_attendance(cryptor: Cryptor) -> list[Attendance]:
    response = Request.get(URL.tasks)

    html = HTMLParser(cryptor.decrypt_encoded_tags(response.text))

    element = html.css_first("#anwesend")
    thead = element.css_first("thead > tr") # can be used to check if columns changed, not used here
    keys = [i.text().strip() for i in thead.css("th")]
    tbody = element.css("tbody > tr")

    attendances = []
    total = defaultdict(int)

    for i in tbody:
        data = {}
        for key, j in zip(keys, i.css("td")):
            if 'style' in j.attributes:
                v = int(j.text(deep=False).strip() or 0)
                data[key] = v
                total[key] += v
            else:
                data[key] = j.text().strip()

        attendances.append(Attendance(
            course=data['Kurs'],
            teacher=data['Lehrkraft'],
            present=data.get('anwesend', 0),
            excused=data.get('entschuldigt', 0),
            absent=data.get('fehlend', 0),
            leaved=data.get('beurlaubt', 0),
            other_event=data.get('andere schulische Veranstaltung', 0)
        ))

    attendances.insert(0, Attendance(
        course=None,
        teacher=None,
        present=total.get('anwesend', 0),
        excused=total.get('entschuldigt', 0),
        absent=total.get('fehlend', 0),
        leaved=total.get('beurlaubt', 0),
        other_event=total.get('andere schulische Veranstaltung', 0)
    ))
    return attendances

def _mark_done(course: str, entry: str, done: bool):
    res = Request.post(URL.tasks, data={
        'a': 'sus_homeworkDone',
        'b': 'done' if done else 'undone',
        'entry': entry,
        'id': course
    }, headers={
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest'
    })
    print(res, res.status_code)