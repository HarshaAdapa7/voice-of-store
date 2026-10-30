"""Comprehensive unit tests for Head Office Issue Tracking & Resolution Management."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from voice_of_store.issues_db import IssuesDB
from voice_of_store.issues_schema import (
    ROLE_DEPT_MEMBER,
    ROLE_DEPT_MGR,
    ROLE_HEAD_OFFICE_ADMIN,
    STATUS_ACKNOWLEDGED,
    STATUS_ASSIGNED,
    STATUS_AWAITING_VERIFICATION,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
    STATUS_PENDING,
    STATUS_REOPENED,
    STATUS_VERIFIED_CLOSED,
)
from voice_of_store.issues_service import IssuesService


@pytest.fixture
def temp_service(tmp_path: Path) -> IssuesService:
    db = IssuesDB(tmp_path / "test_issues.db")
    service = IssuesService(db)
    # Insert sample issue
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    deadlines = service.calculate_deadlines("high", False, now_iso)
    db.insert_issue({
        "id": "ISSUE-TEST-001",
        "title": "Stock Shortage at Central",
        "description": "Recurrent stockouts reported by shoppers.",
        "issue_type_id": "IT01",
        "issue_category": "Out of Stock",
        "severity": "high",
        "actionability": 1,
        "is_safety": 0,
        "is_emerging": 1,
        "store_id": "ST-101",
        "store_name": "Central Store",
        "region": "London",
        "owning_department": "Supply Chain",
        "current_status": STATUS_NEW,
        "detected_at": now_iso,
        "created_at": now_iso,
        "updated_at": now_iso,
        "ack_deadline": deadlines["ack_deadline"],
        "res_deadline": deadlines["res_deadline"],
        "verif_deadline": deadlines["verif_deadline"],
    })
    return service


def test_valid_lifecycle_transitions(temp_service: IssuesService) -> None:
    svc = temp_service
    issue_id = "ISSUE-TEST-001"

    # NEW -> ASSIGNED
    ok, _ = svc.change_status(issue_id, STATUS_ASSIGNED, "admin", ROLE_HEAD_OFFICE_ADMIN, "Head Office")
    assert ok is True
    assert svc.db.get_issue(issue_id)["current_status"] == STATUS_ASSIGNED

    # ASSIGNED -> ACKNOWLEDGED
    ok, _ = svc.change_status(issue_id, STATUS_ACKNOWLEDGED, "lead", ROLE_DEPT_MGR, "Supply Chain")
    assert ok is True
    assert svc.db.get_issue(issue_id)["current_status"] == STATUS_ACKNOWLEDGED
    assert svc.db.get_issue(issue_id)["acknowledged_at"] is not None

    # ACKNOWLEDGED -> IN_PROGRESS
    ok, _ = svc.change_status(issue_id, STATUS_IN_PROGRESS, "analyst", ROLE_DEPT_MEMBER, "Supply Chain")
    assert ok is True

    # IN_PROGRESS -> PENDING (requires reason)
    ok, _ = svc.change_status(issue_id, STATUS_PENDING, "analyst", ROLE_DEPT_MEMBER, "Supply Chain", "Waiting for supplier shipment")
    assert ok is True
    assert svc.db.get_issue(issue_id)["pending_reason"] == "Waiting for supplier shipment"

    # PENDING -> RESOLVED_AWAITING_VERIFICATION
    ok, _ = svc.change_status(issue_id, STATUS_AWAITING_VERIFICATION, "lead", ROLE_DEPT_MGR, "Supply Chain")
    assert ok is True
    assert svc.db.get_issue(issue_id)["resolved_at"] is not None


def test_department_member_cannot_self_verify(temp_service: IssuesService) -> None:
    svc = temp_service
    issue_id = "ISSUE-TEST-001"
    svc.change_status(issue_id, STATUS_ASSIGNED, "admin", ROLE_HEAD_OFFICE_ADMIN, "Head Office")
    svc.change_status(issue_id, STATUS_ACKNOWLEDGED, "lead", ROLE_DEPT_MGR, "Supply Chain")
    svc.change_status(issue_id, STATUS_IN_PROGRESS, "analyst", ROLE_DEPT_MEMBER, "Supply Chain")
    svc.change_status(issue_id, STATUS_AWAITING_VERIFICATION, "lead", ROLE_DEPT_MGR, "Supply Chain")

    # Department member/manager attempts to verify and close
    ok, msg = svc.change_status(issue_id, STATUS_VERIFIED_CLOSED, "analyst", ROLE_DEPT_MEMBER, "Supply Chain")
    assert ok is False
    assert "Department members cannot independently verify" in msg


def test_head_office_verification_approval_and_rejection(temp_service: IssuesService) -> None:
    svc = temp_service
    issue_id = "ISSUE-TEST-001"
    svc.change_status(issue_id, STATUS_ASSIGNED, "admin", ROLE_HEAD_OFFICE_ADMIN, "Head Office")
    svc.change_status(issue_id, STATUS_ACKNOWLEDGED, "lead", ROLE_DEPT_MGR, "Supply Chain")
    svc.change_status(issue_id, STATUS_IN_PROGRESS, "analyst", ROLE_DEPT_MEMBER, "Supply Chain")
    svc.change_status(issue_id, STATUS_AWAITING_VERIFICATION, "lead", ROLE_DEPT_MGR, "Supply Chain")

    # Rejection requires reason
    ok, msg = svc.record_verification(issue_id, "admin", ROLE_HEAD_OFFICE_ADMIN, "REJECTED", rejection_reason="")
    assert ok is False

    # Valid rejection returns to IN_PROGRESS
    ok, _ = svc.record_verification(issue_id, "admin", ROLE_HEAD_OFFICE_ADMIN, "REJECTED", rejection_reason="Deficiency still observed")
    assert ok is True
    assert svc.db.get_issue(issue_id)["current_status"] == STATUS_IN_PROGRESS

    # Resubmit and Approve
    svc.change_status(issue_id, STATUS_AWAITING_VERIFICATION, "lead", ROLE_DEPT_MGR, "Supply Chain")
    ok, _ = svc.record_verification(issue_id, "admin", ROLE_HEAD_OFFICE_ADMIN, "APPROVED", notes="Closure inspected and confirmed")
    assert ok is True
    details = svc.db.get_issue(issue_id)
    assert details["current_status"] == STATUS_VERIFIED_CLOSED
    assert details["verified_by"] == "admin"


def test_reopen_issue_workflow(temp_service: IssuesService) -> None:
    svc = temp_service
    issue_id = "ISSUE-TEST-001"
    # Move to verified closed
    svc.change_status(issue_id, STATUS_ASSIGNED, "admin", ROLE_HEAD_OFFICE_ADMIN, "Head Office")
    svc.change_status(issue_id, STATUS_ACKNOWLEDGED, "lead", ROLE_DEPT_MGR, "Supply Chain")
    svc.change_status(issue_id, STATUS_IN_PROGRESS, "analyst", ROLE_DEPT_MEMBER, "Supply Chain")
    svc.change_status(issue_id, STATUS_AWAITING_VERIFICATION, "lead", ROLE_DEPT_MGR, "Supply Chain")
    svc.record_verification(issue_id, "admin", ROLE_HEAD_OFFICE_ADMIN, "APPROVED")

    # Department member cannot reopen
    ok, _ = svc.change_status(issue_id, STATUS_REOPENED, "analyst", ROLE_DEPT_MEMBER, "Supply Chain", "Problem back")
    assert ok is False

    # Head Office reopens with reason
    ok, _ = svc.change_status(issue_id, STATUS_REOPENED, "admin", ROLE_HEAD_OFFICE_ADMIN, "Head Office", "Recurrence detected in fresh customer reviews")
    assert ok is True
    details = svc.db.get_issue(issue_id)
    assert details["current_status"] == STATUS_REOPENED
    assert details["reopened_count"] == 1


def test_sla_deadlines_and_overdue_detection(temp_service: IssuesService) -> None:
    svc = temp_service
    # Past detected date should trigger overdue
    past_iso = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).isoformat()
    deadlines = svc.calculate_deadlines("critical", True, past_iso)
    issue = {
        "current_status": STATUS_NEW,
        "ack_deadline": deadlines["ack_deadline"],
        "res_deadline": deadlines["res_deadline"],
        "verif_deadline": deadlines["verif_deadline"],
    }
    ov = svc.check_overdue(issue)
    assert ov["is_overdue"] is True
    assert "Acknowledgement Overdue" in ov["overdue_type"]
    assert ov["hours"] > 0


def test_audit_history_preservation(temp_service: IssuesService) -> None:
    svc = temp_service
    issue_id = "ISSUE-TEST-001"
    svc.change_status(issue_id, STATUS_ASSIGNED, "admin", ROLE_HEAD_OFFICE_ADMIN, "Head Office", "Assigned to supply")
    svc.change_status(issue_id, STATUS_ACKNOWLEDGED, "lead", ROLE_DEPT_MGR, "Supply Chain", "Receipt confirmed")

    details = svc.db.get_issue_details(issue_id)
    history = details["history"]
    assert len(history) >= 2
    assert history[-1]["previous_status"] == STATUS_ASSIGNED
    assert history[-1]["new_status"] == STATUS_ACKNOWLEDGED
    assert history[-1]["changed_by"] == "lead"

