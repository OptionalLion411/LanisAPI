"""This script includes the LanisClient to interact with Lanis."""

import json
import os
from datetime import datetime, time as dtime, timedelta
from enum import Enum
from pathlib import Path
from time import time

import httpx

from .constants import JSON, LOGGER, URL
from .exceptions import (
    ForceNewAuthenticationError,
    NoSchoolFoundError,
    WrongCredentialsError,
)
from .functions.apps import (
    App,
    Folder,
    _get_app_availability,
    _get_apps,
    _get_available_apps,
    _get_folders,
)
from .functions.authentication_types import LanisAccount, LanisCookie, SessionType
from .functions.calendar import Calendar, _get_calendar, _get_calendar_month
from .functions.conversations import Conversation, _get_conversations
from .functions.schools import _get_schools
from .functions.substitution import SubstitutionPlan, _get_substitutions
from .functions.tasks import Task, _get_tasks, _get_semester, _get_course, _get_attendance, _download_attachment, \
    _mark_done, Attendance, Semester, Course, Attachment
from .functions.logoutbook import LogoutSettings, AbsenceInformation, _get_state, _logout_timed, _logout_until, _logout_home, _log_back, _snooze
from .functions.filestorage import _search, _list_node, _download_node, SearchResult, FileNode, FolderNode
from .helpers.authentication import (
    get_authentication_sid,
    get_authentication_url,
    get_session,
    get_session_and_autologin,
    get_session_by_autologin,
    get_moodle_login
)
from .helpers.cryptor import Cryptor
from .helpers.request import Request
from .helpers.wrappers import check_availability, handle_exceptions, requires_auth


class LanisClient:
    """The interface between python and Schulportal Hessen.

    Use ``authenticate()`` to use this interface.

    Parameters
    ----------
    authentication : LanisAccount or LanisCookie or None
        1. A Lanis account with its username and password, and a school id or school name and city in ``School``.
        2. Cookies with authentication data (school id and session id) in ``LanisCookie`` for instantly interacting with Lanis. You can obtain this during a session with ``authentication_cookies``.
        3. If None it will use the session.json, like for the 30-days session or last session (100min), when no session.json exists, it will return ``ForceNewAuthenticationError``.
    ad_header : httpx.Headers, default {"user-agent": ....}
        Send custom headers to Lanis. Primarily used to send a
        custom ``user-agent``.
    """

    class AuthenticationMethod(Enum):
        """Used to indicate with which method that this lib provides was used."""

        LanisCookie = 1
        LanisAccount = 2
        SessionsFile = 3

    def __init__(  # noqa: D107
        self,
        authentication: LanisAccount | LanisCookie | None,
        ad_header: httpx.Headers = None,
    ) -> None:
        self.authentication = authentication
        self.ad_header = (
            ad_header
            if ad_header is not None
            else httpx.Headers(
                {
                    "user-agent": "LanisAPI by kurwjan and contributors (https://github.com/kurwjan/LanisAPI/)"
                }
            )
        )
        self.authenticated = False
        self.authentication_method: LanisClient.AuthenticationMethod = None
        self.session_type: SessionType = None
        self.autologin: list[str] | None = None
        
        self.request = Request()
        self.request.set_headers(self.ad_header)
        self.cryptor = Cryptor(self.request)

        LOGGER.debug("USING VERSION 0.4.2")

    def __del__(self) -> None:
        """If the script closes close the parser."""
        self.request.close()

    @property
    def authentication_cookies(self) -> LanisCookie:
        """Return ``LanisCookie`` with the authentication data (school id and session id) if authenticated. You can use this to authenticate with Lanis instantly."""
        cookies = self.request.get_cookies()
        return LanisCookie(cookies.get("i", domain=""), cookies.get("sid"))

    def close(self) -> None:
        """Close the client; you need to do this."""
        self.request.close()
        self.authenticated = False
        LOGGER.debug("Closed current session.")

    @handle_exceptions
    def get_schools(self) -> list[dict[str, str]]:
        """Return all schools with their id, name and city.

        Returns
        -------
        list[dict[str, str]]
            JSON
        """
        return _get_schools(self.request)

    @handle_exceptions
    def _create_new_session(self) -> None:
        # Check if a id or school and place is provided.
        if isinstance(self.authentication.school, str):
            school_id = self.authentication.school
        else:
            schools = self.get_schools()

            # Try to get wanted school with a one liner generator.
            try:
                school_id = next(
                    school
                    for school in schools
                    if school["Name"] == self.authentication.school.name
                    and school["Ort"] == self.authentication.school.city
                )["Id"]
            except StopIteration as err:
                msg = "School doesn't exist, check for right spelling."
                raise NoSchoolFoundError(msg) from err

        # Get new session (value: SPH-Session) and autologin token by posting to login page.
        if self.session_type == SessionType.LONG:
            response_cookies, autologin = get_session_and_autologin(
                self.request, school_id, self.authentication.username, self.authentication.password
            )
            self.autologin = autologin
            response_location = "."
        else:
            response_cookies, response_location = get_session(
                self.request, school_id, self.authentication.username, self.authentication.password
            )

        if not response_location:
            # It also could be other problems, Lanis can be very finicky.
            msg = "Could not log in, possibly wrong credentials."
            raise WrongCredentialsError(msg)

        # Get authentication url to get sid.
        auth_url = get_authentication_url(self.request, response_cookies)

        # Get sid.
        self.request.set_cookies(
            get_authentication_sid(self.request, auth_url, response_cookies, school_id)
        )

        self.authentication_method = self.AuthenticationMethod.LanisAccount

    @handle_exceptions
    def authenticate(
        self, session_type: SessionType = SessionType.NORMAL, force: bool = False
    ) -> None:
        """Log into the school portal and sets the session id in the auth_cookies.

        Parameters
        ----------
        force : bool, optional
            If True it always makes a new session with Lanis, by default False
        session_type : SessionType, optional by default SessionType.NORMAL
            Which session to create.
            There are two session types: NORMAL and LONG. The long session is 30-days long (``angemeldet bleiben`` option) and needs no password or name to be put in afterwards.
            It does not force a new session!

        Note
        ----
        Supports only the new system (login.schulportal.hessen.de).
        More at https://support.schulportal.hessen.de/knowledgebase.php?article=1087.
        """
        if self.authenticated:
            LOGGER.debug("Authenticate: Already authenticated.")
            return

        self.session_type = session_type

        if self.authentication is None:
            msg = "Can't login, no credentials."
            raise WrongCredentialsError(msg)

        # First check if we can restore session from a file.
        if not force:
            # LanisCookie login (highest priority)
            if isinstance(self.authentication, LanisCookie):
                self.request.set_cookies(
                    {
                        "i": self.authentication.school_id,
                        "sid": self.authentication.session_id,
                    }
                )
                self.authentication_method = self.AuthenticationMethod.LanisCookie
        # Create new session if force is True or the other methods are False.
        if force:
            self._create_new_session()

        # Tell Lanis how to encrypt
        if not self.cryptor.authenticate():
            LOGGER.error("Authenticate: Couldn't handshake with Lanis.")
            return

        self.authenticated = True

        available_apps = _get_available_apps(self.request)

        LOGGER.debug(f"Session type: {self.session_type.name}")

        LOGGER.debug(f"Authentication method: {self.authentication_method.name}")

        LOGGER.debug(
            "Available apps:\n"
            f"  Calendar: {'Kalender' in available_apps}\n"
            + f"  Tasks: {'Mein Unterricht' in available_apps}\n"
            + f"  Conversations: {'Nachrichten - Beta-Version' in available_apps}\n"
            + f"  Substitution plan: {'Vertretungsplan' in available_apps}"
        )

        LOGGER.debug("Authenticated.")

    @requires_auth
    @handle_exceptions
    def logout(self) -> None:
        """Log out.

        Note
        ----
        For closing the current LanisClient use `close()`
        """
        self.request.post(URL.index, data={"logout": "all"})
        self.authenticated = False
        LOGGER.debug("Logged out.")

    @requires_auth
    @check_availability("Vertretungsplan")
    @handle_exceptions
    def get_substitution_plan(self) -> SubstitutionPlan:
        """Return the whole substitution plan of the current day.

        Returns
        -------
        SubstitutionPlan
        """
        return _get_substitutions(self.request)

    @requires_auth
    @handle_exceptions
    def get_calendar_of_month(self) -> Calendar:
        """Use the get_calendar() function but only returns all events of the current month.

        Returns
        -------
        Calendar
            `Calendar` with `Event`
        """
        return _get_calendar_month(self.request)

    @requires_auth
    @check_availability("Kalender")
    @handle_exceptions
    def get_calendar(
        self, start: datetime, end: datetime, json: bool = False
    ) -> Calendar:
        """Return all calendar events between the start and end date.

        Parameters
        ----------
        start : datetime.datetime
            Start date
        end : datetime.datetime
            End date
        json : bool, default False
            Returns Json with every property instead of the limited CalendarData.
            Defaults to False.

        Returns
        -------
        Calendar
            `Calendar` with `Event` or Json.
        """
        return _get_calendar(self.request, start, end, json)

    @requires_auth
    @check_availability("Mein Unterricht")
    @handle_exceptions
    def get_tasks(self) -> list[Task]:
        """Return all tasks from the "Mein Unterricht" page with downloads in .zip format.

        Returns
        -------
        list[TaskData]
        """
        return _get_tasks(self.request)

    @requires_auth
    @check_availability("Mein Unterricht")
    @handle_exceptions
    def get_semester(self, course_id: int, semester: int = 1) -> Semester:
        """Return the semester data of a course."""

        return _get_semester(self.request, self.cryptor, course_id, semester)

    @requires_auth
    @check_availability("Mein Unterricht")
    @handle_exceptions
    def get_course(self, course_id: int) -> Course:
        """Return the course data of a course."""

        return _get_course(self.request, self.cryptor, course_id)

    @requires_auth
    @check_availability("Mein Unterricht")
    @handle_exceptions
    def get_attendance(self) -> list[Attendance]:
        return _get_attendance(self.request, self.cryptor)

    @requires_auth
    @check_availability("Mein Unterricht")
    @handle_exceptions
    def download_attachment(self, attachment: str | Attachment):
        return _download_attachment(self.request, attachment)

    @requires_auth
    @check_availability("Mein Unterricht")
    @handle_exceptions
    def set_done(self, course_id: int, entry_id: int, value=True) -> None:
        _mark_done(self.request, course_id, entry_id, value)

    @requires_auth
    @check_availability("Dateispeicher")
    @handle_exceptions
    def search_files(self, query: str = "") -> list[SearchResult]:
        return _search(self.request, query)

    @requires_auth
    @check_availability("Dateispeicher")
    @handle_exceptions
    def list_files(self, node: int = 0) -> tuple[list[FileNode], list[FolderNode]]:
        return _list_node(self.request, node)

    @requires_auth
    @check_availability("Dateispeicher")
    @handle_exceptions
    def download_storage_file(self, node: int|FileNode):
        return _download_node(self.request, node)

    @requires_auth
    @handle_exceptions
    def get_state(self) -> LogoutSettings|AbsenceInformation:
        return _get_state(self.request)

    @requires_auth
    @handle_exceptions
    def logout_timed(self, end_time: dtime, reason: str, agreement: str = "") -> bool:
        return _logout_timed(self.request, end_time, reason, agreement)

    @requires_auth
    @handle_exceptions
    def logout_until(self, end_time: datetime, reason: str, agreement: str = "") -> bool:
        return _logout_until(self.request, end_time, reason, agreement)

    @requires_auth
    @handle_exceptions
    def logout_home(self, agreement: str = "") -> bool:
        return _logout_home(self.request, agreement)

    @requires_auth
    @handle_exceptions
    def logout_snooze(self, minutes: int) -> bool:
        return _snooze(self.request, minutes)

    @requires_auth
    @handle_exceptions
    def logout_logback(self) -> bool:
        return _log_back(self.request)

    @requires_auth
    @check_availability("Nachrichten - Beta-Version")
    @handle_exceptions
    def get_conversations(self, number: int = 5) -> list[Conversation]:
        """Return conversations from the "Nachrichten - Beta-Version".

        Parameters
        ----------
        number : int, optional
            The number of conversations to return, by default 5. To get all conversations use -1 but this will take a while and spam Lanis servers.

        Returns
        -------
        list[Conversation]
            The conversations in Conversation.
        """
        return _get_conversations(self.request, self.cryptor, number)

    # TODO: check if moodle is available
    @requires_auth
    @handle_exceptions
    def get_moodle_login(self, url = URL.moodle_redirect) -> tuple[str, str] | None:
        return get_moodle_login(self.request, url)

    @requires_auth
    @handle_exceptions
    def get_apps(self) -> list[App]:
        """Get all web applets from Lanis, not only supported ones.

        Returns
        -------
        list[App]
            A list of `App`.
        """
        return _get_apps(self.request)

    @requires_auth
    @handle_exceptions
    def get_available_apps(self) -> list[str]:
        """Get all supported web applets by this library which are also supported by the Lanis of the user.

        Returns
        -------
        list[str]
            A list of the supported applets.
        """
        return _get_available_apps(self.request)

    @requires_auth
    @handle_exceptions
    def get_app_availability(self, app_name: str) -> bool:
        """Check if one of these apps: ``Kalender``, ``Mein Unterricht``, ``Nachrichten - Beta-Version``, ``Vertretungsplan`` is supported by the school.

        Parameters
        ----------
        app_name : str
            The applet name.

        Returns
        -------
        bool
        """
        return _get_app_availability(self.request, app_name)

    @requires_auth
    @handle_exceptions
    def get_folders(self) -> list[Folder]:
        """Get all web folders from Lanis.

        Returns
        -------
        list[Folder]
            A list of Folder.
        """
        return _get_folders(self.request)
