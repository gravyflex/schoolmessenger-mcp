from __future__ import annotations

import base64
import datetime as dt
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import yaml


class SchoolMessengerError(RuntimeError):
    """Raised for SchoolMessenger API or validation failures."""


@dataclass(frozen=True)
class Config:
    region: str
    username: str
    password: str
    timeout: int = 20

    @property
    def portal_base(self) -> str:
        return f"https://portal.schoolmessenger.{self.region}/api/2"

    @property
    def attendance_base(self) -> str:
        return f"https://go.schoolmessenger.{self.region}/api/1"


def load_config() -> Config:
    region = os.environ.get("SCHOOLMESSENGER_REGION", "ca").strip().lower()
    if region not in {"ca", "com"}:
        raise SchoolMessengerError("SCHOOLMESSENGER_REGION must be 'ca' or 'com'")

    username = os.environ.get("SCHOOLMESSENGER_USERNAME")
    password = os.environ.get("SCHOOLMESSENGER_PASSWORD")
    if username and password:
        return Config(region=region, username=username, password=password)

    default_file = Path.home() / f".config/schoolmessenger.{region}/creds.yml"
    creds_file = Path(os.environ.get("SCHOOLMESSENGER_CREDS_FILE", str(default_file))).expanduser()
    account = os.environ.get("SCHOOLMESSENGER_ACCOUNT", "default")
    if not creds_file.exists():
        raise SchoolMessengerError(
            "Set SCHOOLMESSENGER_USERNAME/PASSWORD or SCHOOLMESSENGER_CREDS_FILE"
        )
    data = yaml.safe_load(creds_file.read_text()) or {}
    if account not in data:
        raise SchoolMessengerError(f"Account {account!r} not found in credential file")
    entry = data[account]
    try:
        return Config(region=region, username=entry["username"], password=entry["password"])
    except KeyError as exc:
        raise SchoolMessengerError(f"Credential entry {account!r} missing {exc.args[0]}") from exc


class SchoolMessengerClient:
    def __init__(self, config: Config | None = None, session: requests.Session | None = None):
        self.config = config or load_config()
        self.session = session or requests.Session()
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at = 0.0

    def login(self) -> dict[str, Any]:
        client_secret = base64.b64encode(b"json-client:secret").decode("ascii")
        response = self.session.post(
            f"{self.config.portal_base}/oauth/token",
            headers={
                "Accept": "Application/json",
                "Authorization": f"Basic {client_secret}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "password",
                "username": self.config.username,
                "password": self.config.password,
            },
            timeout=self.config.timeout,
        )
        self._raise_for_status(response, "login failed")
        token = response.json()
        self._set_token(token)
        return self._redact_token(token)

    def _set_token(self, token: dict[str, Any]) -> None:
        self._access_token = token["access_token"]
        self._refresh_token = token.get("refresh_token")
        self._expires_at = time.time() + int(token.get("expires_in", 900)) - 60

    @staticmethod
    def _redact_token(token: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in token.items() if k not in {"access_token", "refresh_token"}}

    def _headers(self) -> dict[str, str]:
        if not self._access_token or time.time() >= self._expires_at:
            self.login()
        assert self._access_token
        bearer = f"Bearer {self._access_token}"
        return {
            "Accept": "application/json",
            "Authorization": bearer,
            "X-Authorization": bearer,
            "X-App-Client": "1",
            "X-Requested-With": "XMLHttpRequest",
        }

    def get_attendance(self) -> dict[str, Any]:
        response = self.session.get(
            f"{self.config.attendance_base}/attendance",
            headers=self._headers(),
            timeout=self.config.timeout,
        )
        self._raise_for_status(response, "attendance lookup failed")
        return response.json()

    def list_absences(
        self, from_date: str, to_date: str, unexplained_only: bool = False
    ) -> dict[str, Any]:
        _parse_date(from_date)
        _parse_date(to_date)
        suffix = "?filter=canBeExplained" if unexplained_only else ""
        response = self.session.get(
            f"{self.config.attendance_base}/attendance/absences/{from_date}/{to_date}{suffix}",
            headers=self._headers(),
            timeout=self.config.timeout,
        )
        self._raise_for_status(response, "absence range lookup failed")
        return response.json()

    def create_absence(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f"{self.config.attendance_base}/attendance/absences",
            headers={**self._headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=self.config.timeout,
        )
        self._raise_for_status(response, "absence create failed")
        if not response.content:
            return {"status": response.status_code}
        return response.json()

    def get_absence(self, customer_id: int, absence_id: str) -> dict[str, Any]:
        response = self.session.get(
            f"{self.config.attendance_base}/attendance/{customer_id}/absences/{absence_id}",
            headers=self._headers(),
            timeout=self.config.timeout,
        )
        self._raise_for_status(response, "absence lookup failed")
        return response.json()

    def delete_absence(self, customer_id: int, absence_id: str) -> dict[str, Any]:
        response = self.session.delete(
            f"{self.config.attendance_base}/attendance/{customer_id}/absences/{absence_id}",
            headers=self._headers(),
            timeout=self.config.timeout,
        )
        self._raise_for_status(response, "absence delete failed")
        if not response.content:
            return {"status": response.status_code}
        return response.json()

    @staticmethod
    def _raise_for_status(response: requests.Response, context: str) -> None:
        if response.ok:
            return
        message = context
        try:
            body = response.json()
            if isinstance(body, dict) and body.get("message"):
                message = f"{context}: {body['message']}"
            elif isinstance(body, list):
                message = f"{context}: {body}"
        except ValueError:
            if response.text:
                message = f"{context}: {response.text[:200]}"
        raise SchoolMessengerError(f"{message} (HTTP {response.status_code})")


def build_absence_payload(
    attendance: dict[str, Any],
    student: str | None,
    absence_type: str,
    reason: str,
    date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    in_time: str | None = None,
    out_time: str | None = None,
    comment: str | None = None,
) -> tuple[dict[str, Any], str]:
    selected_student = _select_student(attendance, student)
    org = _select_org(attendance, selected_student)
    type_info = _select_absence_type(org, absence_type)
    reason_info = _select_reason(type_info, reason)
    dates = _build_dates(type_info["type"], date, start_date, end_date, in_time, out_time)
    _validate_dates(dates, org, attendance)

    payload: dict[str, Any] = {
        "student": {
            "customerId": selected_student["customerId"],
            "personId": selected_student["personId"],
            "organizationId": selected_student["organizationId"],
        },
        "source": "user",
        "client": "web",
        "absenceType": type_info["type"],
        "reasonCode": reason_info["code"],
        "absenceDates": dates,
    }
    if org.get("commentsEnabled") and comment:
        payload["comment"] = comment

    summary = (
        f"{_student_name(selected_student)}: {type_info.get('text', type_info['type'])} "
        f"on {_date_summary(dates)} because {reason_info.get('text', reason_info['code'])}"
    )
    return payload, summary


def get_student_org(
    attendance: dict[str, Any], student: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected_student = _select_student(attendance, student)
    return selected_student, _select_org(attendance, selected_student)


def make_draft(payload: dict[str, Any], summary: str, action: str = "SUBMIT") -> dict[str, Any]:
    draft_id = secrets.token_urlsafe(12)
    confirmation_phrase = f"{action} ABSENCE {draft_id}"
    return {
        "draft_id": draft_id,
        "summary": summary,
        "confirmation_phrase": confirmation_phrase,
        "payload": payload,
    }


def absence_identity(absence: dict[str, Any]) -> tuple[int | None, str | None]:
    absence_body = absence.get("absence") if isinstance(absence.get("absence"), dict) else {}
    student = absence.get("student") if isinstance(absence.get("student"), dict) else {}
    customer_id = (
        absence.get("customerId")
        or absence_body.get("customerId")
        or student.get("customerId")
        or _nested_get(absence, ("student", "customer", "id"))
    )
    absence_id = (
        absence.get("id")
        or absence.get("absenceId")
        or absence_body.get("id")
        or absence_body.get("absenceId")
    )
    try:
        parsed_customer_id = int(customer_id) if customer_id is not None else None
    except (TypeError, ValueError):
        parsed_customer_id = None
    return parsed_customer_id, str(absence_id) if absence_id is not None else None


def find_absence(
    absences_response: dict[str, Any],
    absence_id: str,
    customer_id: int | None = None,
) -> dict[str, Any] | None:
    for item in absences_response.get("absences") or []:
        item_customer_id, item_absence_id = absence_identity(item)
        if item_absence_id != str(absence_id):
            continue
        if customer_id is not None and item_customer_id != int(customer_id):
            continue
        return item
    return None


def absence_summary(absence: dict[str, Any]) -> str:
    absence_body = absence.get("absence") if isinstance(absence.get("absence"), dict) else absence
    student = absence.get("student") if isinstance(absence.get("student"), dict) else {}
    student_name = (
        f"{student.get('firstName', '')} {student.get('lastName', '')}".strip()
        or absence.get("studentName")
        or "student"
    )
    absence_type = _text_or_code(absence_body.get("absenceType") or absence_body.get("type"))
    reason = _text_or_code(absence_body.get("reason") or absence_body.get("reasonCode"))
    dates = absence_body.get("absenceDates") or absence.get("absenceDates") or []
    date_text = _date_summary(dates) if dates else "unknown date"
    reason_text = f" because {reason}" if reason else ""
    return f"{student_name}: {absence_type or 'absence'} on {date_text}{reason_text}"


def _nested_get(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _text_or_code(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("text") or value.get("type") or value.get("code")
    if value is None:
        return None
    return str(value)


def _select_student(attendance: dict[str, Any], student: str | None) -> dict[str, Any]:
    students = attendance.get("attendanceEnabledStudents") or []
    if not students:
        raise SchoolMessengerError("No attendance-enabled students found")
    if not student:
        if len(students) == 1:
            return students[0]
        raise SchoolMessengerError("Multiple students found; provide a student name or personId")
    needle = student.strip().lower()
    matches = [
        s
        for s in students
        if str(s.get("personId")) == student
        or needle in f"{s.get('firstName', '')} {s.get('lastName', '')}".strip().lower()
    ]
    if len(matches) != 1:
        raise SchoolMessengerError(f"Student selector matched {len(matches)} students")
    return matches[0]


def _select_org(attendance: dict[str, Any], student: dict[str, Any]) -> dict[str, Any]:
    for org in attendance.get("organizationSettings") or []:
        if (
            org.get("customerId") == student.get("customerId")
            and org.get("organizationId") == student.get("organizationId")
        ):
            return org
    raise SchoolMessengerError("No organization settings found for selected student")


def _select_absence_type(org: dict[str, Any], absence_type: str) -> dict[str, Any]:
    needle = absence_type.strip().lower()
    for item in org.get("absenceTypes") or []:
        if needle in {str(item.get("type", "")).lower(), str(item.get("text", "")).lower()}:
            return item
    raise SchoolMessengerError(f"Unknown absence type {absence_type!r}")


def _select_reason(absence_type: dict[str, Any], reason: str) -> dict[str, Any]:
    needle = reason.strip().lower()
    for item in absence_type.get("reasons") or []:
        if needle in {str(item.get("code", "")).lower(), str(item.get("text", "")).lower()}:
            return item
    raise SchoolMessengerError(f"Unknown reason {reason!r} for {absence_type.get('type')}")


def _build_dates(
    absence_type: str,
    date: str | None,
    start_date: str | None,
    end_date: str | None,
    in_time: str | None,
    out_time: str | None,
) -> list[dict[str, Any]]:
    if absence_type == "multiDay":
        if not start_date or not end_date:
            raise SchoolMessengerError("multiDay requires start_date and end_date")
        start = _parse_date(start_date)
        end = _parse_date(end_date)
        if end <= start:
            raise SchoolMessengerError("multiDay end_date must be after start_date")
        dates = []
        current = start
        while current <= end:
            dates.append({"date": current.isoformat()})
            current += dt.timedelta(days=1)
        return dates

    if not date:
        raise SchoolMessengerError(f"{absence_type} requires date")
    item: dict[str, Any] = {"date": _parse_date(date).isoformat()}
    if absence_type in {"late", "partialDay"}:
        item["inTime"] = _parse_time(in_time, "in_time")
    else:
        item["inTime"] = in_time
    if absence_type in {"earlyDeparture", "partialDay"}:
        item["outTime"] = _parse_time(out_time, "out_time")
    else:
        item["outTime"] = out_time
    return [item]


def _validate_dates(
    dates: list[dict[str, Any]], org: dict[str, Any], attendance: dict[str, Any]
) -> None:
    term = org.get("term") or {}
    term_start = _parse_date(term.get("startDate"))
    term_end = _parse_date(term.get("endDate"))
    max_days = int(org.get("maxConsecutiveDays") or 366)
    if len(dates) > max_days:
        raise SchoolMessengerError(f"Absence exceeds maxConsecutiveDays={max_days}")

    blocked = set()
    for item in attendance.get("holidays") or []:
        if isinstance(item, str):
            blocked.add(item)
        elif isinstance(item, dict):
            for key in ("date", "startDate"):
                if item.get(key):
                    blocked.add(item[key])

    for item in dates:
        value = _parse_date(item["date"])
        if value < term_start or value > term_end:
            raise SchoolMessengerError("Absence date is outside the school term")
        if value.isoweekday() > 5:
            raise SchoolMessengerError("Absence date cannot be on a weekend")
        if value.isoformat() in blocked:
            raise SchoolMessengerError("Absence date falls on a holiday or exam day")


def _parse_date(value: str | None) -> dt.date:
    if not value:
        raise SchoolMessengerError("Date is required")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise SchoolMessengerError(f"Invalid date {value!r}; expected YYYY-MM-DD") from exc


def _parse_time(value: str | None, field: str) -> str:
    if not value:
        raise SchoolMessengerError(f"{field} is required")
    try:
        dt.datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise SchoolMessengerError(f"Invalid {field} {value!r}; expected HH:MM") from exc
    return value


def _student_name(student: dict[str, Any]) -> str:
    return f"{student.get('firstName', '')} {student.get('lastName', '')}".strip()


def _date_summary(dates: list[dict[str, Any]]) -> str:
    if len(dates) == 1:
        item = dates[0]
        suffix = ""
        if item.get("outTime") and item.get("inTime"):
            suffix = f" {item['outTime']}-{item['inTime']}"
        elif item.get("outTime"):
            suffix = f" leaving {item['outTime']}"
        elif item.get("inTime"):
            suffix = f" arriving {item['inTime']}"
        return item["date"] + suffix
    return f"{dates[0]['date']} through {dates[-1]['date']}"
