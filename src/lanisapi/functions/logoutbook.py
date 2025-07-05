"""This script includes classes and functions about the ISH specific 'Austragebuch' page."""
import datetime
import re

from attrs import define, field
from requests import Response
from selectolax.parser import HTMLParser

from ..constants import URL, headers
from ..helpers.request import Request

class LogoutError(Exception):
    """Exception for errors in the logout process."""

@define
class AgreementOption:
    lastname: str = field()
    firstname: str = field()
    abbreviation: str = field()
    value: str = field()

@define
class AbsenceInformation:
    start: datetime.datetime = field()
    until: datetime.datetime = field()
    reason: str = field()
    alerts: list[str] = field()

@define
class LogoutSettings:
    agreement_options: list[AgreementOption]|None = field()
    ikey: str|None = field()

absence_pattern = re.compile("Ziel/Grund:\\W*<b>(.*?)</b>.+?((bis (.+?) Uhr)|(ab (\\w+), den (.+?),\\W*um (.+?) Uhr.+?bis (\\w+),.+?den (.+?),.+? um (.+?) Uhr))", re.DOTALL)

# TODO manual validate agreement option, since its not checked

def _get_state(request: Request) -> LogoutSettings|AbsenceInformation:
    response = request.get(URL.logout_book)
    html = HTMLParser(response.text)

    absence = html.css_first("#away")
    if absence:
        data = re.search(absence_pattern, absence.html).groups()
        if data[4] is None:
            start = None
            end_hour, end_minute = data[3].split(":")
            until = datetime.datetime(datetime.datetime.now().year, datetime.datetime.now().month, datetime.datetime.now().day, int(end_hour), int(end_minute))
        else:
            start_day, start_month, start_year = data[6].split(".")
            start_hour, start_minute = data[7].split(":")
            start = datetime.datetime(int(start_year), int(start_month), int(start_day), int(start_hour), int(start_minute))
            end_day, end_month, end_year = data[9].split(".")
            end_hour, end_minute = data[10].split(":")
            until = datetime.datetime(int(end_year), int(end_month), int(end_day), int(end_hour), int(end_minute))

        reason = data[0] if data else None
        alerts = [i.text().strip() for i in html.css("div.alert-warning")]

        return AbsenceInformation(
            start=start,
            until=until,
            reason=reason,
            alerts=alerts
        )
    else:
        agreement_options: list[AgreementOption] = []
        for i in html.css("#absprache select[name='absprache'] > option"):
            data = re.search("(\\w+)\\W*,\\W*(\\w+)\\W+\\((\\w+)\\)", i.text())
            if data:
                agreement_options.append(AgreementOption(*data.groups(), i.attributes["value"]))

        ikey = html.css_first("[name='ikey']").attributes['value']

        return LogoutSettings(agreement_options, ikey)

def _get_previous_reasons(request: Request) -> list[str]:
    response_dest = request.post(URL.logout_book, data={
        'a': "loadZiele"
    })

    return response_dest.json()

def _handle_error(response: Response) -> bool:
    res = response.json()
    if "error" in res and res["error"] != "" or response.status_code != 200:
        raise LogoutError("Logout failed. " + (res["error"] or "Unknown error"))
    return res["back"]

def _logout_base(request: Request, options: dict, agreement: str = "") -> bool:
    sett = _get_state(request)
    if isinstance(sett, AbsenceInformation):
        raise LogoutError("You are already logged out.")

    data: dict = options | {
        'absprache': agreement,
        'ikey': sett.ikey,
        'save': '1'
    }

    return _handle_error(request.post(URL.logout_book, headers=headers, data=data))

def _snooze(request: Request, minutes: int) -> bool:
    request = request.post(URL.logout_book, headers=headers, data={
        'a': 'start_sus',
        'b': 'snooze',
        'v': str(minutes)
    })
    return request.status_code == 200

def _logout_timed(request: Request, time: datetime.time, reason: str, agreement: str = "") -> bool:
    return _logout_base(request, {
        'a': 'addEntry',
        'art': 'ausgang',
        'bis': f'{time.hour}:{time.minute}',
        'ziel': reason
    }, agreement)


def _logout_until(request: Request, time: datetime.datetime, reason: str, agreement: str = "") -> bool:
    return _logout_base(request, {
        'a': 'addEntry',
        'art': 'rueckkehrInternat',
        'bisF': f'{time.year}-{time.month:02}-{time.day:02} {time.hour:02}:{time.minute:02}:00',
        'ziel': reason
    }, agreement)

# TODO cannot test since I am unable to log back
def _logout_home(request: Request, reason: str = "Krank zu Hause", agreement: str = "") -> bool:
    return _logout_base(request, {
        'a': 'addEntry',
        'art': 'krankZuHause',
        'offenesEndeAusgang': '1',
        'ziel': reason
    }, agreement)

def _log_back(request: Request) -> bool:
    request = request.post(URL.logout_book, headers=headers, data={
        'b': 'back'
    })
    return request.status_code == 200
