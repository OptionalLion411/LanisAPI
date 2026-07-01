"""This script includes classes and functions about the 'Mein Unterricht' page."""

import datetime as dt
from enum import Enum
from urllib.parse import urljoin
from collections import defaultdict

from attrs import define, field
from selectolax.parser import HTMLParser

from ..constants import LOGGER, URL
from ..exceptions import CriticalElementWasNotFoundError
from ..helpers.cryptor import Cryptor
from ..helpers.request import Request
from ..helpers.util import convert_size_unit


@define
class Attachment:
    """The attachment of a task."""

    name: str = field()
    size: int = field()
    download_url: str = field()

class AttendanceType(Enum):
    PRESENT = "anwesend"
    EXCUSED = "entschuldigt"
    LEAVED = "beurlaubt"
    OTHER_EVENT = "andere schulische Veranstaltung"
    ABSENT = "fehlend"


@define
class Attendance:
    course: str | None = field()
    teacher: str | None = field()
    present: int = field()        # anwesend
    excused: int = field()        # entschuldigt
    leaved: int = field()         # beurlaubt
    other_event: int = field()    # andere schulische Veranstaltung
    absent: int = field()         # fehlende

@define
class Task:
    """The "Mein Unterricht" page in a data type. Expect many parameters to be `None`. """

    title: str = field()
    description: str = field()
    date: dt.date = field()
    subject_name: str = field()
    teacher: str = field()
    homework: str = field()
    done: bool = field()
    attachment: list[str] = field()
    attachment_url: str = field()
    course_id: int = field()
    entry_id: str = field()

@define
class CourseTask:
    """The task of a course."""

    entry_id: str = field()
    title: str = field()
    description: str = field()
    date: dt.date = field()
    time: tuple[int, int] = field()
    homework: str = field()
    done: bool = field()
    attachments: list[Attachment] = field()
    attendance: AttendanceType = field()
    attendance_reason: str = field()
    uploads: list[dict] = field(factory=list)

@define
class Semester:
    """The semester of a course."""

    semester: int = field()
    tasks: list[CourseTask] = field(factory=list)

@define
class Course:
    """The course of a task."""

    name: str = field()
    teacher: tuple[str, str, str] = field()
    course_id: int = field()
    semesters: list[Semester] = field(factory=list)


def _get_tasks(request: Request) -> list[Task]:
    """Return all tasks from the "Mein Unterricht" page with downloads in .zip format.

    Returns
    -------
    list[Task]
    """
    # Unfortunately there is no API for us.
    response = request.get(URL.tasks)

    html = HTMLParser(response.text)

    elements = html.css("#aktuellTable tr.printable")

    # Parse page to get all tasks. Also report suspicious missing elements.
    task_list = []
    for element in elements:
        if not element:
            raise CriticalElementWasNotFoundError("Critical task element was not found!")

        main_element = element.css_first("td:nth-child(2)")
        if main_element and "noch kein Eintrag" in main_element.text():
            continue

        # Name of task.
        title_element = element.css_first("b.thema")
        try:
            title = title_element.text()
        except AttributeError:
            LOGGER.warning(
                "Get tasks: No task name found, possibly wrong css selector?"
            )
            title = None

        # Date it was given.
        date_element = element.css_first("small span.datum")
        try:
            date = dt.datetime.strptime(date_element.text(), "%d.%m.%Y")
        except AttributeError:
            LOGGER.warning(
                "Get tasks: No date found, possibly wrong css selector?"
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
                "Get tasks: No subject name found, possibly wrong css selector?"
            )
            subject = None

        # Teacher
        teacher_element = element.css_first("span.teacher button")
        try:
            teacher = teacher_element.attributes["title"]
        except AttributeError:
            LOGGER.warning(
                "Get tasks: No teacher name found, possibly wrong css selector?"
            )
            teacher = None

        # List of all attachment names.
        attachments = []
        attachment_elements = element.css("a.file")
        for attachment_element in attachment_elements:
            attachments.append(attachment_element.attributes["data-file"])

        # The download_url of a zip containing all attachments.
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
            description=details,
            date=date,
            subject_name=subject,
            teacher=teacher,
            homework=homework,
            done=done,
            attachment=attachments,
            attachment_url=attachment_url,
            course_id=int(course_id),
            entry_id=entry_id
        )

        task_list.append(task_data)

    LOGGER.debug("Get tasks: Successfully got tasks.")

    return task_list

def _get_semester(request: Request, cryptor: Cryptor, course_id: int, semester: int) -> Semester:
    response = request.get(URL.tasks, params={
        'a': 'sus_view',
        'id': course_id,
        'halb': semester
    })
    html = HTMLParser(cryptor.decrypt_encoded_tags(response.text))

    history = html.css_first("#history")
    entries = []
    for i in history.css("tbody > tr"):
        desc = i.css_first("span.markup i.far.fa-comment-alt:first-child")
        if desc:
            desc = desc.parent.text().strip()

        homework = i.css_first("span.homework + br + span.markup")
        if homework:
            homework = homework.text().strip()
        homework_done = i.css_first("span.done.hidden") is None if homework else None

        files = []
        files_div = i.css_first("div.alert.alert-info")
        if files_div:
            base_url = URL.base
            base_url += files_div.css_first("a").attributes["href"].replace("&b=zip", "")

            for file_div in i.css(".files > .file"):
                filename = file_div.attributes.get("data-file")
                size = convert_size_unit(file_div.css_first("a > small").text()[1:-1])
                file_url = f"{base_url}&f={filename}"
                files.append(Attachment(
                    name=filename,
                    size=size,
                    download_url=file_url
                ))

        # TODO maybe add uploads

        date_info = [x.strip() for x in i.css_first("td").text().split("\n") if x.strip()]
        date_date = dt.datetime.strptime(date_info[0], "%d.%m.%Y").date()
        date_time = [int(j.strip()[:-1]) for j in date_info[1].replace("Stunde", "").split("-")]
        if len(date_time) < 2:
            date_time.append(date_time[0])

        attendance_sel = i.css_first("td:last-child")
        attendance_sel.css_first("div.hidden").decompose()
        attendance_plain = attendance_sel.text().strip()
        attendance, _, detail = attendance_plain.partition(" (")
        if detail != '':
            detail = detail[:-1]
            print(detail)

        attendance = AttendanceType(attendance) if attendance and attendance != "nicht erfasst" else None

        entries.append(CourseTask(
            entry_id=i.attributes.get("data-entry"),
            title=i.css_first("td > b").text().strip(),
            description=desc,
            date=date_date,
            time=tuple(date_time),
            homework=homework,
            done=homework_done,
            attendance=attendance,
            attendance_reason=detail,
            attachments=files
        ))

    # TODO maybe add grades
    return Semester(
        semester=semester,
        tasks=entries
    )

def _get_course(request: Request, cryptor: Cryptor, course_id: int) -> Course:
    response = request.get(URL.tasks, params={
        'a': 'sus_view',
        'id': course_id
    })
    html = HTMLParser(response.text)

    semesters = [_get_semester(request, cryptor, course_id, 1)]

    headline = html.css_first("h1")
    semester_button = html.css_first(".btn.hidden-print")
    indicator = headline.css_first("span").text()
    if semester_button or indicator.strip().startswith("2"):
        semesters.append(_get_semester(request, cryptor, course_id, 2))

    teacher_button = html.css_first(".btn-primary.dropdown-toggle")
    teacher_info = teacher_button.parent.css_first(".dropdown-menu")

    return Course(
        course_id=course_id,
        name=headline.text(deep=False).strip(),
        teacher=(
            teacher_info.css_first("li").text().strip(),
            teacher_button.text().strip(),
            email.text().replace("mailto:", "").strip() if (email := teacher_info.css_first("[title='E-Mail-Adresse']")) else None
        ),
        semesters=semesters
    )


def _get_attendance(request: Request, cryptor: Cryptor) -> list[Attendance]:
    response = request.get(URL.tasks)
    html = HTMLParser(cryptor.decrypt_encoded_tags(response.text))

    attendances = []

    element = html.css_first("#anwesend")
    thead = element.css_first("thead > tr") # can be used to check if columns changed, not used here
    if thead is None: return attendances
    keys = [i.text().strip() for i in thead.css("th")]
    tbody = element.css("tbody > tr")

    total = defaultdict(int)

    for i in tbody:
        data = {}
        for key, j in zip(keys, i.css("td")):
            if 'style' in j.attributes:
                cell = j.text(deep=False).strip()
                v = int(cell) if cell.isdigit() else 0
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


def _download_attachment(request: Request, attachment: str | Attachment):
    if isinstance(attachment, Attachment):
        attachment = attachment.download_url

    stream = request.client.stream("get", attachment)
    return stream


def _mark_done(request: Request, course: int, entry: int, done: bool) -> bool:
    res = request.post(URL.tasks, data={
        'a': 'sus_homeworkDone',
        'b': 'done' if done else 'undone',
        'entry': entry,
        'id': course
    }, headers={
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest'
    })
    return res.status_code == 200