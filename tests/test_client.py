from __future__ import annotations

import datetime as dt

import pytest

from schoolmessenger_mcp.client import (
    SchoolMessengerError,
    absence_identity,
    build_absence_payload,
    find_absence,
    make_draft,
)


def attendance_fixture() -> dict:
    today = dt.date.today()
    if today.isoweekday() > 5:
        today += dt.timedelta(days=8 - today.isoweekday())
    return {
        "attendanceEnabledStudents": [
            {
                "customerId": 37,
                "organizationId": 46,
                "personId": 141269,
                "firstName": "Test",
                "lastName": "Student",
                "organizationName": "Test School",
            }
        ],
        "organizationSettings": [
            {
                "customerId": 37,
                "organizationId": 46,
                "commentsEnabled": False,
                "attachmentsEnabled": False,
                "maxConsecutiveDays": 15,
                "term": {
                    "startDate": (today - dt.timedelta(days=1)).isoformat(),
                    "endDate": (today + dt.timedelta(days=300)).isoformat(),
                },
                "absenceTypes": [
                    {
                        "type": "fullDay",
                        "text": "Full Day",
                        "reasons": [{"code": "I", "text": "Illness"}],
                    },
                    {
                        "type": "late",
                        "text": "Late",
                        "reasons": [{"code": "L", "text": "Late"}],
                    },
                ],
            }
        ],
        "holidays": [],
    }


def test_builds_full_day_payload() -> None:
    today = dt.date.today()
    if today.isoweekday() > 5:
        today += dt.timedelta(days=8 - today.isoweekday())
    payload, summary = build_absence_payload(
        attendance_fixture(),
        student=None,
        absence_type="fullDay",
        reason="Illness",
        date=today.isoformat(),
    )

    assert payload["student"]["personId"] == 141269
    assert payload["absenceType"] == "fullDay"
    assert payload["reasonCode"] == "I"
    assert payload["absenceDates"] == [
        {"date": today.isoformat(), "inTime": None, "outTime": None}
    ]
    assert "Test Student" in summary


def test_late_requires_in_time() -> None:
    today = dt.date.today()
    if today.isoweekday() > 5:
        today += dt.timedelta(days=8 - today.isoweekday())

    with pytest.raises(SchoolMessengerError, match="in_time is required"):
        build_absence_payload(
            attendance_fixture(),
            student=None,
            absence_type="late",
            reason="Late",
            date=today.isoformat(),
        )


def test_absence_identity_handles_nested_schoolmessenger_shape() -> None:
    absence = {
        "customerId": 37,
        "absence": {
            "id": "abc123",
            "absenceDates": [{"date": "2026-09-14"}],
        },
    }

    assert absence_identity(absence) == (37, "abc123")


def test_find_absence_filters_by_customer_id() -> None:
    response = {
        "absences": [
            {"customerId": 11, "absence": {"id": "abc123"}},
            {"customerId": 37, "absence": {"id": "abc123"}},
        ]
    }

    assert find_absence(response, "abc123", 37) == {"customerId": 37, "absence": {"id": "abc123"}}


def test_cancel_draft_uses_cancel_confirmation_phrase() -> None:
    draft = make_draft({"customer_id": 37, "absence_id": "abc123"}, "Cancel test", action="CANCEL")

    assert draft["confirmation_phrase"] == f"CANCEL ABSENCE {draft['draft_id']}"
