from __future__ import annotations

import datetime as dt
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import (
    SchoolMessengerClient,
    SchoolMessengerError,
    absence_identity,
    absence_summary,
    build_absence_payload,
    find_absence,
    get_student_org,
    make_draft,
)

mcp = FastMCP(
    "schoolmessenger-absence",
    instructions=(
        "Absence-only SchoolMessenger MCP. Never submit or cancel an absence until the user has "
        "explicitly approved the exact confirmation phrase returned by the matching draft tool."
    ),
)
client = SchoolMessengerClient()
drafts: dict[str, dict[str, Any]] = {}
cancel_drafts: dict[str, dict[str, Any]] = {}


@mcp.tool()
def list_students() -> dict[str, Any]:
    """List attendance-enabled students available to the configured account."""
    attendance = client.get_attendance()
    students = []
    for student in attendance.get("attendanceEnabledStudents", []):
        students.append(
            {
                "name": f"{student.get('firstName', '')} {student.get('lastName', '')}".strip(),
                "personId": student.get("personId"),
                "customerId": student.get("customerId"),
                "organizationId": student.get("organizationId"),
                "organizationName": student.get("organizationName"),
                "safearrivalPinEnabled": student.get("safearrivalPinEnabled"),
                "hasSafearrivalPin": student.get("hasSafearrivalPin"),
            }
        )
    return {"students": students}


@mcp.tool()
def list_absence_options(student: str | None = None) -> dict[str, Any]:
    """List absence types and reasons for a student selector or the only available student."""
    attendance = client.get_attendance()
    selected_student, org = get_student_org(attendance, student)
    return {
        "student": {
            "name": (
                f"{selected_student.get('firstName', '')} "
                f"{selected_student.get('lastName', '')}"
            ).strip(),
            "personId": selected_student.get("personId"),
            "customerId": selected_student.get("customerId"),
            "organizationId": selected_student.get("organizationId"),
            "organizationName": selected_student.get("organizationName"),
        },
        "term": org.get("term"),
        "schoolDay": org.get("schoolDay"),
        "maxConsecutiveDays": org.get("maxConsecutiveDays"),
        "commentsEnabled": org.get("commentsEnabled"),
        "attachmentsEnabled": org.get("attachmentsEnabled"),
        "absenceTypes": org.get("absenceTypes", []),
    }


@mcp.tool()
def list_absences(
    from_date: str | None = None, to_date: str | None = None, unexplained_only: bool = False
) -> dict[str, Any]:
    """List existing absences for a date range."""
    start = dt.date.fromisoformat(from_date) if from_date else dt.date.today()
    end = dt.date.fromisoformat(to_date) if to_date else start + dt.timedelta(days=45)
    return client.list_absences(start.isoformat(), end.isoformat(), unexplained_only)


@mcp.tool()
def draft_absence(
    absence_type: str,
    reason: str,
    student: str | None = None,
    date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    in_time: str | None = None,
    out_time: str | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    """Draft an absence and return the confirmation phrase required for submit_absence."""
    attendance = client.get_attendance()
    payload, summary = build_absence_payload(
        attendance=attendance,
        student=student,
        absence_type=absence_type,
        reason=reason,
        date=date,
        start_date=start_date,
        end_date=end_date,
        in_time=in_time,
        out_time=out_time,
        comment=comment,
    )
    draft = make_draft(payload, summary)
    drafts[draft["draft_id"]] = draft
    return {
        "draft_id": draft["draft_id"],
        "summary": draft["summary"],
        "confirmation_phrase": draft["confirmation_phrase"],
        "payload": draft["payload"],
    }


@mcp.tool()
def submit_absence(draft_id: str, confirmation_phrase: str) -> dict[str, Any]:
    """Submit a previously drafted absence after exact confirmation."""
    draft = drafts.get(draft_id)
    if not draft:
        raise SchoolMessengerError("Unknown draft_id; call draft_absence first")
    if confirmation_phrase != draft["confirmation_phrase"]:
        raise SchoolMessengerError("Confirmation phrase does not match draft")
    result = client.create_absence(draft["payload"])
    drafts.pop(draft_id, None)
    return {"summary": draft["summary"], "result": result}


@mcp.tool()
def draft_cancel_absence(
    absence_id: str,
    customer_id: int | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict[str, Any]:
    """Draft cancellation of an existing absence and return the required confirmation phrase."""
    absence = None
    start = (
        dt.date.fromisoformat(from_date)
        if from_date
        else dt.date.today() - dt.timedelta(days=30)
    )
    end = dt.date.fromisoformat(to_date) if to_date else dt.date.today() + dt.timedelta(days=180)
    absences = client.list_absences(start.isoformat(), end.isoformat())
    absence = find_absence(absences, absence_id, customer_id)

    if absence is None and customer_id is not None:
        absence = client.get_absence(customer_id, absence_id)

    if absence is None:
        raise SchoolMessengerError(
            "Absence not found; call list_absences and pass the absence_id and customer_id"
        )

    resolved_customer_id, resolved_absence_id = absence_identity(absence)
    if resolved_customer_id is None and customer_id is not None:
        resolved_customer_id = customer_id
    if resolved_absence_id is None:
        resolved_absence_id = absence_id
    if resolved_customer_id is None or resolved_absence_id is None:
        raise SchoolMessengerError(
            "Could not determine customer_id and absence_id for cancellation"
        )

    payload = {"customer_id": resolved_customer_id, "absence_id": resolved_absence_id}
    draft = make_draft(payload, f"Cancel {absence_summary(absence)}", action="CANCEL")
    cancel_drafts[draft["draft_id"]] = draft
    return {
        "draft_id": draft["draft_id"],
        "summary": draft["summary"],
        "confirmation_phrase": draft["confirmation_phrase"],
        "absence": absence,
    }


@mcp.tool()
def cancel_absence(draft_id: str, confirmation_phrase: str) -> dict[str, Any]:
    """Cancel a previously drafted absence cancellation after exact confirmation."""
    draft = cancel_drafts.get(draft_id)
    if not draft:
        raise SchoolMessengerError("Unknown draft_id; call draft_cancel_absence first")
    if confirmation_phrase != draft["confirmation_phrase"]:
        raise SchoolMessengerError("Confirmation phrase does not match draft")
    result = client.delete_absence(draft["payload"]["customer_id"], draft["payload"]["absence_id"])
    cancel_drafts.pop(draft_id, None)
    return {"summary": draft["summary"], "result": result}


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
