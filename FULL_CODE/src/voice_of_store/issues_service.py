"""Head Office Issue Tracking service and business logic.

Manages issue lifecycles, SLA calculations, role-based authorization,
verification workflows, and operational KPIs.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from .issues_db import IssuesDB
from .issues_schema import (
    ROLE_DEPT_MEMBER,
    ROLE_DEPT_MGR,
    ROLE_HEAD_OFFICE_ADMIN,
    ROLE_REGIONAL_MGR,
    ROLE_STORE_OWNER,
    SLA_HOURS,
    STATUS_ACKNOWLEDGED,
    STATUS_ASSIGNED,
    STATUS_AWAITING_VERIFICATION,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
    STATUS_PENDING,
    STATUS_REOPENED,
    STATUS_VERIFIED_CLOSED,
    VALID_TRANSITIONS,
)

log = logging.getLogger(__name__)


def _tally_counts(kpis: dict[str, int], it: dict[str, Any], is_overdue: bool) -> None:
    """Increment status and priority counters for an issue."""
    st = it.get("current_status")
    mapping = {
        STATUS_NEW: "new",
        STATUS_ASSIGNED: "assigned",
        STATUS_ACKNOWLEDGED: "acknowledged",
        STATUS_IN_PROGRESS: "in_progress",
        STATUS_PENDING: "pending",
        STATUS_AWAITING_VERIFICATION: "awaiting_verification",
        STATUS_VERIFIED_CLOSED: "verified_closed",
        STATUS_REOPENED: "reopened",
    }
    key = mapping.get(st or "")
    if key:
        kpis[key] += 1
    if it.get("is_safety") or it.get("severity") == "critical":
        kpis["critical_safety"] += 1
    if is_overdue:
        kpis["overdue"] += 1


def _tally_dept(dept_summary: dict[str, dict[str, Any]], dept: str, st: str | None, is_overdue: bool) -> None:
    """Accumulate workload statistics per department."""
    if dept not in dept_summary:
        dept_summary[dept] = {"total": 0, "open": 0, "closed": 0, "overdue": 0}
    dept_summary[dept]["total"] += 1
    if st == STATUS_VERIFIED_CLOSED:
        dept_summary[dept]["closed"] += 1
    else:
        dept_summary[dept]["open"] += 1
    if is_overdue:
        dept_summary[dept]["overdue"] += 1


class IssuesService:
    """Business logic for Head Office issue lifecycle, SLA, and verification."""

    def __init__(self, db: IssuesDB | None = None) -> None:
        self.db = db or IssuesDB()

    @staticmethod
    def calculate_deadlines(severity: str, is_safety: bool, detected_at_iso: str) -> dict[str, str]:
        """Compute SLA deadlines based on severity and escalation rules."""
        base_time = dt.datetime.fromisoformat(detected_at_iso.replace("Z", "+00:00"))
        tier = "safety" if is_safety else severity.lower()
        cfg = SLA_HOURS.get(tier, SLA_HOURS["medium"])

        ack_dl = base_time + dt.timedelta(hours=cfg["ack"])
        res_dl = base_time + dt.timedelta(hours=cfg["resolve"])
        verif_dl = res_dl + dt.timedelta(hours=cfg["verify"])

        return {
            "ack_deadline": ack_dl.strftime("%Y-%m-%d %H:%M:%S"),
            "res_deadline": res_dl.strftime("%Y-%m-%d %H:%M:%S"),
            "verif_deadline": verif_dl.strftime("%Y-%m-%d %H:%M:%S"),
        }

    @staticmethod
    def check_overdue(issue: dict[str, Any]) -> dict[str, Any]:
        """Determine whether an issue has breached any SLA deadline."""
        now = dt.datetime.now(dt.UTC)
        status = issue.get("current_status", STATUS_NEW)

        def parse(ts_str: str | None) -> dt.datetime | None:
            if not ts_str:
                return None
            try:
                t = dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                return t if t.tzinfo else t.replace(tzinfo=dt.UTC)
            except (ValueError, TypeError):
                return None

        ack_dl = parse(issue.get("ack_deadline"))
        res_dl = parse(issue.get("res_deadline"))
        verif_dl = parse(issue.get("verif_deadline"))

        if status in (STATUS_NEW, STATUS_ASSIGNED) and ack_dl and now > ack_dl:
            hours = round((now - ack_dl).total_seconds() / 3600, 1)
            return {"is_overdue": True, "overdue_type": "Acknowledgement Overdue", "hours": hours}

        if status in (STATUS_ACKNOWLEDGED, STATUS_IN_PROGRESS, STATUS_PENDING, STATUS_REOPENED) and res_dl and now > res_dl:
            hours = round((now - res_dl).total_seconds() / 3600, 1)
            return {"is_overdue": True, "overdue_type": "Resolution Overdue", "hours": hours}

        if status == STATUS_AWAITING_VERIFICATION and verif_dl and now > verif_dl:
            hours = round((now - verif_dl).total_seconds() / 3600, 1)
            return {"is_overdue": True, "overdue_type": "Verification Overdue", "hours": hours}

        return {"is_overdue": False, "overdue_type": "", "hours": 0.0}

    def validate_transition(
        self,
        current_status: str,
        new_status: str,
        user_role: str,
        reason: str | None = None,
    ) -> tuple[bool, str]:
        """Validate whether a status change is allowed by role and workflow."""
        allowed = VALID_TRANSITIONS.get(current_status, frozenset())
        if new_status not in allowed:
            return False, f"Invalid transition from {current_status} to {new_status}"

        # Department members and store owners cannot mark their own work as independently verified
        if new_status == STATUS_VERIFIED_CLOSED and user_role in (ROLE_DEPT_MEMBER, ROLE_DEPT_MGR, ROLE_STORE_OWNER):
            return False, "Department members cannot independently verify and close their own issues."

        # Pending status must provide a blocker reason
        if new_status == STATUS_PENDING and not (reason and reason.strip()):
            return False, "A reason explaining the blocker is required when moving to PENDING"

        # Reopening requires Head Office or Regional authorization and a reason
        if new_status == STATUS_REOPENED:
            if user_role not in (ROLE_HEAD_OFFICE_ADMIN, ROLE_REGIONAL_MGR):
                return False, "Only Head Office Administrators or Regional Managers may reopen issues"
            if not (reason and reason.strip()):
                return False, "A clear reason or recurrence evidence is required to reopen an issue"

        return True, ""

    def _prepare_transition_extra(
        self,
        issue: dict[str, Any],
        new_status: str,
        changed_by: str,
        reason: str | None,
        now_str: str,
    ) -> dict[str, Any]:
        """Prepare database extra update fields based on new status."""
        extra: dict[str, Any] = {}
        issue_id = issue["id"]

        if new_status == STATUS_ACKNOWLEDGED and not issue.get("acknowledged_at"):
            extra["acknowledged_at"] = now_str
        elif new_status == STATUS_AWAITING_VERIFICATION:
            extra["resolved_at"] = now_str
            if reason:
                extra["resolution_summary"] = reason
            self.db.add_notification(
                {
                    "issue_id": issue_id,
                    "recipient_role": ROLE_HEAD_OFFICE_ADMIN,
                    "event_type": "VERIFICATION_REQUIRED",
                    "message": f"Issue {issue_id} submitted for Head Office verification",
                }
            )
        elif new_status == STATUS_VERIFIED_CLOSED:
            extra["verified_at"] = now_str
            extra["verified_by"] = changed_by
            if reason:
                extra["verification_notes"] = reason
        elif new_status == STATUS_REOPENED:
            extra["reopened_at"] = now_str
            extra["reopened_count"] = int(issue.get("reopened_count") or 0) + 1
        elif new_status == STATUS_PENDING:
            extra["pending_reason"] = reason

        return extra

    def change_status(
        self,
        issue_id: str,
        new_status: str,
        changed_by: str,
        user_role: str,
        department: str,
        reason: str | None = None,
    ) -> tuple[bool, str]:
        """Execute validated status change with audit trail and notifications."""
        issue = self.db.get_issue(issue_id)
        if not issue:
            return False, "Issue not found"

        ok, msg = self.validate_transition(issue["current_status"], new_status, user_role, reason)
        if not ok:
            return False, msg

        now_str = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S")
        extra = self._prepare_transition_extra(issue, new_status, changed_by, reason, now_str)

        success = self.db.update_issue_status(issue_id, new_status, changed_by, user_role, department, reason, extra)
        return success, "Status updated successfully" if success else "Failed to update status"

    def record_verification(
        self,
        issue_id: str,
        verifier_id: str,
        user_role: str,
        decision: str,
        notes: str | None = None,
        rejection_reason: str | None = None,
    ) -> tuple[bool, str]:
        """Record Head Office resolution verification decision."""
        if user_role != ROLE_HEAD_OFFICE_ADMIN:
            return False, "Only Head Office Administrators can record resolution verifications"

        issue = self.db.get_issue(issue_id)
        if not issue:
            return False, "Issue not found"
        if issue["current_status"] != STATUS_AWAITING_VERIFICATION:
            return False, f"Issue is in {issue['current_status']}, not awaiting verification"

        dec = decision.upper()
        if dec == "APPROVED":
            self.db.add_verification(
                {
                    "issue_id": issue_id,
                    "verifier_id": verifier_id,
                    "decision": "APPROVED",
                    "verification_notes": notes or "Resolution verified by Head Office",
                }
            )
            return self.change_status(
                issue_id,
                STATUS_VERIFIED_CLOSED,
                verifier_id,
                user_role,
                "Head Office",
                notes or "Verified & closed by Head Office",
            )

        if dec == "REJECTED":
            if not (rejection_reason and rejection_reason.strip()):
                return False, "A rejection reason is mandatory when rejecting verification"
            self.db.add_verification(
                {
                    "issue_id": issue_id,
                    "verifier_id": verifier_id,
                    "decision": "REJECTED",
                    "rejection_reason": rejection_reason,
                    "verification_notes": notes,
                }
            )
            return self.change_status(
                issue_id, STATUS_IN_PROGRESS, verifier_id, user_role, "Head Office", f"Verification rejected: {rejection_reason}"
            )

        return False, "Invalid decision; must be APPROVED or REJECTED"

    def get_kpis(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Calculate operational dashboard metrics using real database records."""
        issues = self.db.list_issues(filters)
        kpis: dict[str, int] = {
            "total": len(issues),
            "new": 0,
            "assigned": 0,
            "acknowledged": 0,
            "in_progress": 0,
            "pending": 0,
            "awaiting_verification": 0,
            "verified_closed": 0,
            "reopened": 0,
            "overdue": 0,
            "critical_safety": 0,
        }
        dept_summary: dict[str, dict[str, Any]] = {}

        for it in issues:
            ov = self.check_overdue(it)
            _tally_counts(kpis, it, ov["is_overdue"])
            dept = it.get("owning_department") or "Store Ops"
            _tally_dept(dept_summary, dept, it.get("current_status"), ov["is_overdue"])

        return {
            "counts": kpis,
            "status_counts": {
                "NEW": kpis["new"],
                "ASSIGNED": kpis["assigned"],
                "ACKNOWLEDGED": kpis["acknowledged"],
                "IN_PROGRESS": kpis["in_progress"],
                "PENDING": kpis["pending"],
                "RESOLVED_AWAITING_VERIFICATION": kpis["awaiting_verification"],
                "VERIFIED_CLOSED": kpis["verified_closed"],
                "REOPENED": kpis["reopened"],
            },
            "total_issues": kpis["total"],
            "overdue_count": kpis["overdue"],
            "reopened_count": kpis["reopened"],
            "critical_safety_count": kpis["critical_safety"],
            "departments": dept_summary,
            "department_summary": dept_summary,
        }

    def get_resolution_matrix(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Retrieve aggregated problem resolution status across stores, regions, and formats."""
        res = self.db.get_resolution_matrix(filters)
        for it in res["issues"]:
            ov = self.check_overdue(it)
            it["is_overdue"] = ov["is_overdue"]
            it["overdue_type"] = ov["overdue_type"]
        return res
