"""Head Office Issue Tracking database repository.

Provides ACID persistence for issues, status history, department actions,
verifications, evidence, and escalation notifications.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from .issues_schema import (
    SQLITE_TABLES,
    STATUS_AWAITING_VERIFICATION,
    STATUS_PENDING,
    STATUS_VERIFIED_CLOSED,
)

log = logging.getLogger(__name__)


def _append_simple_filters(clauses: list[str], params: list[Any], filters: dict[str, Any]) -> None:
    """Append equality filters for standard database columns with table alias."""
    for col, key in (
        ("current_status", "status"),
        ("owning_department", "department"),
        ("region", "region"),
        ("severity", "severity"),
        ("store_id", "store_id"),
        ("store_format", "store_format"),
        ("issue_category", "category"),
    ):
        if filters.get(key):
            clauses.append(f"i.{col} = ?")
            params.append(filters[key])


def _append_special_filters(clauses: list[str], params: list[Any], filters: dict[str, Any]) -> None:
    """Append resolution, safety, and text search clauses with table alias."""
    res_val = filters.get("resolution_status")
    if res_val == "resolved":
        clauses.append("i.current_status = 'VERIFIED_CLOSED'")
    elif res_val == "awaiting_verification":
        clauses.append("i.current_status = 'RESOLVED_AWAITING_VERIFICATION'")
    elif res_val == "unresolved":
        clauses.append("i.current_status NOT IN ('VERIFIED_CLOSED', 'RESOLVED_AWAITING_VERIFICATION')")
    elif res_val == "pending":
        clauses.append("i.current_status = 'PENDING'")

    if filters.get("is_safety") is not None:
        clauses.append("i.is_safety = ?")
        params.append(int(filters["is_safety"]))

    if filters.get("search"):
        term = f"%{filters['search']}%"
        clauses.append("(i.title LIKE ? OR i.description LIKE ? OR i.store_name LIKE ? OR i.id LIKE ?)")
        params.extend([term, term, term, term])


def _tally_matrix_item(groups: list[dict[str, dict[str, Any]]], keys: list[str], status: str) -> None:
    """Tally resolution counters across multiple breakdown groups."""
    for grp, k in zip(groups, keys, strict=False):
        if k not in grp:
            grp[k] = {"total": 0, "resolved": 0, "awaiting": 0, "unresolved": 0}
        grp[k]["total"] += 1
        if status == STATUS_VERIFIED_CLOSED:
            grp[k]["resolved"] += 1
        elif status == STATUS_AWAITING_VERIFICATION:
            grp[k]["awaiting"] += 1
        else:
            grp[k]["unresolved"] += 1


def _finalize_rates(groups: list[dict[str, dict[str, Any]]]) -> None:
    """Calculate percentage resolution rates for breakdown groups."""
    for g in groups:
        for v in g.values():
            v["resolution_rate"] = round((v["resolved"] / v["total"] * 100), 1) if v["total"] else 0.0


class IssuesDB:
    """Database repository for Head Office issue resolution management."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            root = Path(__file__).resolve().parents[2]
            db_path = root / "data" / "voice_of_store.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a connection with row factory enabled."""
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initialize database tables and indexes."""
        with self._get_connection() as conn:
            conn.executescript(SQLITE_TABLES)
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(ho_issues)")
            cols = {r[1] for r in cur.fetchall()}
            if "store_format" not in cols:
                conn.execute("ALTER TABLE ho_issues ADD COLUMN store_format TEXT DEFAULT 'Saffron Market'")

    def count_issues(self) -> int:
        """Count total issues in database."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM ho_issues")
            return int(cur.fetchone()[0])

    def insert_issue(self, issue: dict[str, Any]) -> str:
        """Insert a newly detected or created issue."""
        cols = [
            "id", "source_detection_id", "title", "description", "issue_type_id",
            "issue_category", "severity", "actionability", "is_safety", "is_emerging",
            "store_id", "store_name", "region", "store_format", "owning_department",
            "assigned_user_id", "assigned_team", "current_status", "pending_reason",
            "detected_at", "created_at", "updated_at", "ack_deadline", "res_deadline",
            "verif_deadline", "confidence", "evidence_count", "next_step"
        ]
        present = [c for c in cols if c in issue]
        placeholders = ", ".join(["?"] * len(present))
        sql = f"INSERT INTO ho_issues ({', '.join(present)}) VALUES ({placeholders})"
        vals = [issue[c] for c in present]

        with self._get_connection() as conn:
            conn.execute(sql, vals)
        return str(issue["id"])

    def get_issue(self, issue_id: str) -> dict[str, Any] | None:
        """Retrieve single issue by its unique ID."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ho_issues WHERE id = ?", (issue_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_issues(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """List issues matching given filter criteria, including latest action details."""
        clauses: list[str] = []
        params: list[Any] = []
        f = filters or {}
        _append_simple_filters(clauses, params, f)
        _append_special_filters(clauses, params, f)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""SELECT i.*,
                         a.action_description AS latest_action_desc,
                         a.user_id AS latest_action_by,
                         a.created_at AS latest_action_at,
                         a.action_type AS latest_action_type,
                         a.progress_notes AS latest_action_progress
                  FROM ho_issues i
                  LEFT JOIN ho_actions a ON a.id = (SELECT MAX(id) FROM ho_actions WHERE issue_id = i.id)
                  {where}
                  ORDER BY i.updated_at DESC"""

        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def update_issue_status(
        self,
        issue_id: str,
        new_status: str,
        changed_by: str,
        role: str,
        department: str,
        reason: str | None = None,
        extra_updates: dict[str, Any] | None = None,
    ) -> bool:
        """Update issue status with atomic audit log history."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT current_status FROM ho_issues WHERE id = ?", (issue_id,))
            row = cur.fetchone()
            if not row:
                return False
            prev_status = row["current_status"]

            # Update issue row
            set_parts = ["current_status = ?", "updated_at = CURRENT_TIMESTAMP"]
            params: list[Any] = [new_status]
            if extra_updates:
                for k, v in extra_updates.items():
                    set_parts.append(f"{k} = ?")
                    params.append(v)
            params.append(issue_id)

            conn.execute(f"UPDATE ho_issues SET {', '.join(set_parts)} WHERE id = ?", params)
            conn.execute(
                """INSERT INTO ho_status_history
                   (issue_id, previous_status, new_status, changed_by, user_role, department, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (issue_id, prev_status, new_status, changed_by, role, department, reason or ""),
            )
        return True

    def add_action(self, action: dict[str, Any]) -> int:
        """Record department investigation note or corrective action."""
        sql = """INSERT INTO ho_actions
                 (issue_id, user_id, user_role, department, action_type,
                  action_description, progress_notes, blockers, expected_completion)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        vals = (
            action["issue_id"], action["user_id"], action["user_role"],
            action["department"], action["action_type"], action["action_description"],
            action.get("progress_notes", ""), action.get("blockers", ""),
            action.get("expected_completion"),
        )
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, vals)
            return int(cur.lastrowid or 0)

    def add_evidence(self, evidence: dict[str, Any]) -> int:
        """Attach evidence feedback record to issue."""
        sql = """INSERT INTO ho_evidence
                 (issue_id, feedback_id, evidence_type, channel, feedback_text)
                 VALUES (?, ?, ?, ?, ?)"""
        vals = (
            evidence["issue_id"], evidence.get("feedback_id"),
            evidence["evidence_type"], evidence.get("channel"), evidence.get("feedback_text")
        )
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, vals)
            return int(cur.lastrowid or 0)

    def add_verification(self, verif: dict[str, Any]) -> int:
        """Record Head Office resolution verification decision."""
        sql = """INSERT INTO ho_verifications
                 (issue_id, verifier_id, decision, rejection_reason, verification_notes)
                 VALUES (?, ?, ?, ?, ?)"""
        vals = (
            verif["issue_id"], verif["verifier_id"], verif["decision"],
            verif.get("rejection_reason", ""), verif.get("verification_notes", "")
        )
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, vals)
            return int(cur.lastrowid or 0)

    def add_notification(self, notif: dict[str, Any]) -> int:
        """Create an in-app escalation notification."""
        sql = """INSERT INTO ho_notifications
                 (issue_id, recipient_role, recipient_department, event_type, message)
                 VALUES (?, ?, ?, ?, ?)"""
        vals = (
            notif["issue_id"], notif["recipient_role"],
            notif.get("recipient_department"), notif["event_type"], notif["message"]
        )
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, vals)
            return int(cur.lastrowid or 0)

    def get_issue_details(self, issue_id: str) -> dict[str, Any] | None:
        """Get full issue details with actions, evidence, and audit history."""
        issue = self.get_issue(issue_id)
        if not issue:
            return None
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ho_status_history WHERE issue_id = ? ORDER BY created_at ASC", (issue_id,))
            issue["history"] = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT * FROM ho_actions WHERE issue_id = ? ORDER BY created_at DESC", (issue_id,))
            issue["actions"] = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT * FROM ho_evidence WHERE issue_id = ? ORDER BY created_at ASC", (issue_id,))
            issue["evidence"] = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT * FROM ho_verifications WHERE issue_id = ? ORDER BY verified_at DESC", (issue_id,))
            issue["verifications"] = [dict(r) for r in cur.fetchall()]
        return issue

    def get_resolution_matrix(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Aggregate problem resolution status across stores, regions, and formats."""
        issues = self.list_issues(filters)
        total = len(issues)
        resolved = sum(1 for i in issues if i["current_status"] == STATUS_VERIFIED_CLOSED)
        awaiting = sum(1 for i in issues if i["current_status"] == STATUS_AWAITING_VERIFICATION)
        pending = sum(1 for i in issues if i["current_status"] == STATUS_PENDING)
        unresolved = total - resolved - awaiting

        by_format: dict[str, dict[str, Any]] = {}
        by_region: dict[str, dict[str, Any]] = {}
        by_cat: dict[str, dict[str, Any]] = {}
        groups = [by_format, by_region, by_cat]

        for i in issues:
            keys = [
                i.get("store_format") or "Saffron Market",
                i.get("region") or "Unknown",
                i.get("issue_category") or "General",
            ]
            _tally_matrix_item(groups, keys, i["current_status"])

        _finalize_rates(groups)
        rate = round((resolved / total * 100), 1) if total else 0.0
        return {
            "summary": {
                "total_problems": total,
                "verified_resolved": resolved,
                "awaiting_verification": awaiting,
                "unresolved": unresolved,
                "pending": pending,
                "resolution_rate": rate,
            },
            "by_format": by_format,
            "by_region": by_region,
            "by_category": by_cat,
            "issues": issues,
        }

    def get_notifications(self, role: str, department: str | None = None) -> list[dict[str, Any]]:
        """Fetch unread notifications for a user role and department."""
        sql = """SELECT * FROM ho_notifications
                 WHERE (recipient_role = ? OR recipient_role = 'all')
                   AND (recipient_department IS NULL OR recipient_department = ? OR recipient_department = '')
                 ORDER BY created_at DESC LIMIT 50"""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, (role, department or ""))
            return [dict(r) for r in cur.fetchall()]

