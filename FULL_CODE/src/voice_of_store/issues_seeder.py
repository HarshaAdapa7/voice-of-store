"""Seeder for Head Office Issue Tracking system.

Ingests detected emerging issues and high-severity safety reports from
the Voice-of-Store engine into the relational issue database.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from .issues_db import IssuesDB
from .issues_schema import (
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
from .issues_service import IssuesService
from .routing import SAFETY_TYPES, next_step

log = logging.getLogger(__name__)


def _load_data_frames(
    data_dir: Path, submission_dir: Path
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, dict[str, str]]] | None:
    """Load required CSV files into memory for issue seeding."""
    flags_csv = submission_dir / "R5_emerging_flags.csv"
    stores_csv = data_dir / "store_master.csv"
    tax_csv = data_dir / "issue_taxonomy.csv"
    fb_csv = data_dir / "feedback.csv"

    if not (flags_csv.is_file() and stores_csv.is_file() and tax_csv.is_file()):
        return None

    stores_df = pd.read_csv(stores_csv, dtype=str).set_index("store_id")
    tax_df = pd.read_csv(tax_csv, dtype=str).set_index("issue_type_id")
    flags_df = pd.read_csv(flags_csv, dtype=str)
    fb_map: dict[str, dict[str, str]] = {}

    if fb_csv.is_file():
        fb_df = pd.read_csv(fb_csv, dtype=str)
        for _, r in fb_df.iterrows():
            fb_map[str(r["feedback_id"])] = {
                "channel": str(r.get("channel", "in_app")),
                "text": str(r.get("text", "")),
            }
    return flags_df, stores_df, tax_df, fb_map


def _build_issue_dict(
    row: pd.Series,
    stores_df: pd.DataFrame,
    tax_df: pd.DataFrame,
    idx: int,
    now_dt: dt.datetime,
) -> dict[str, Any]:
    """Construct one issue record dictionary."""
    st_id, it_id = str(row["store_id"]), str(row["issue_type_id"])
    store_name = str(stores_df.loc[st_id, "store_name"])
    region = str(stores_df.loc[st_id, "region"])
    store_format = str(stores_df.loc[st_id, "format"]) if "format" in stores_df.columns else "Saffron Market"
    it_name = str(tax_df.loc[it_id, "issue_type"])
    dept = str(tax_df.loc[it_id, "owner_function"])
    if dept.startswith("None"):
        dept = "Store Ops"

    is_safety = int(it_id in SAFETY_TYPES)
    severity = "critical" if is_safety else ("high" if float(row.get("confidence", 0.5)) > 0.8 else "medium")
    issue_id = f"ISSUE-EMG-{st_id}-{it_id}-{idx}"

    statuses = [
        STATUS_NEW,
        STATUS_ASSIGNED,
        STATUS_ACKNOWLEDGED,
        STATUS_IN_PROGRESS,
        STATUS_PENDING,
        STATUS_AWAITING_VERIFICATION,
        STATUS_VERIFIED_CLOSED,
        STATUS_REOPENED,
    ]
    status = statuses[idx % len(statuses)]
    week_str = str(row["as_of_week_start"])
    detected_iso = f"{week_str}T08:00:00Z"
    deadlines = IssuesService.calculate_deadlines(severity, bool(is_safety), detected_iso)

    return {
        "id": issue_id,
        "source_detection_id": f"FLAG-{st_id}-{it_id}",
        "title": f"Emerging: {it_name} at {store_name}",
        "description": f"CUSUM detector flagged emerging spike in {it_name} (confidence {float(row['confidence']):.2f}).",
        "issue_type_id": it_id,
        "issue_category": it_name,
        "severity": severity,
        "actionability": 1,
        "is_safety": is_safety,
        "is_emerging": 1,
        "store_id": st_id,
        "store_name": store_name,
        "region": region,
        "store_format": store_format,
        "owning_department": dept,
        "assigned_user_id": f"mgr_{dept.lower().replace(' ', '_')}@storevoice.local",
        "assigned_team": f"{dept} Regional Response Team",
        "current_status": status,
        "pending_reason": "Waiting for supplier shipment" if status == STATUS_PENDING else None,
        "detected_at": detected_iso,
        "created_at": detected_iso,
        "updated_at": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "ack_deadline": deadlines["ack_deadline"],
        "res_deadline": deadlines["res_deadline"],
        "verif_deadline": deadlines["verif_deadline"],
        "confidence": float(row["confidence"]),
        "evidence_count": len(str(row.get("evidence_feedback_ids", "")).split(";")),
        "next_step": next_step(it_id, dept, True),
    }


def seed_issues_from_engine(db: IssuesDB, data_dir: Path, submission_dir: Path) -> int:
    """Populate database with detected issues from engine outputs if empty."""
    if db.count_issues() > 0:
        return 0

    loaded = _load_data_frames(data_dir, submission_dir)
    if not loaded:
        return 0
    flags_df, stores_df, tax_df, fb_map = loaded

    count = 0
    now_dt = dt.datetime.now(dt.UTC)

    for idx, row in flags_df.iterrows():
        st_id, it_id = str(row["store_id"]), str(row["issue_type_id"])
        if st_id not in stores_df.index or it_id not in tax_df.index:
            continue

        rec = _build_issue_dict(row, stores_df, tax_df, idx, now_dt)
        issue_id = rec["id"]
        db.insert_issue(rec)
        _seed_audit_history(db, issue_id, rec["current_status"], rec["owning_department"], now_dt)
        _seed_evidence(db, issue_id, str(row.get("evidence_feedback_ids", "")), fb_map)
        count += 1

    count += _seed_format_coverage(db, stores_df, tax_df, now_dt)
    log.info("Seeded %d issues into Head Office Issue Management database", count)
    return count


def _seed_early_audit(db: IssuesDB, issue_id: str, final_status: str, dept: str) -> bool:
    """Progress status history through NEW, ASSIGNED, and ACKNOWLEDGED stages."""
    db.update_issue_status(issue_id, STATUS_NEW, "System Detector", "system", "AI Engine", "Detected by CUSUM algorithm")
    if final_status == STATUS_NEW:
        return False
    db.update_issue_status(
        issue_id, STATUS_ASSIGNED, "HO Dispatcher", ROLE_HEAD_OFFICE_ADMIN, "Head Office", f"Assigned to {dept}"
    )
    if final_status == STATUS_ASSIGNED:
        return False
    db.update_issue_status(issue_id, STATUS_ACKNOWLEDGED, "Team Lead", ROLE_DEPT_MGR, dept, "Acknowledged receipt by department")
    return final_status != STATUS_ACKNOWLEDGED


def _seed_audit_history(db: IssuesDB, issue_id: str, final_status: str, dept: str, now_dt: dt.datetime) -> None:
    """Create realistic audit history progression for seeded issue."""
    if not _seed_early_audit(db, issue_id, final_status, dept):
        return

    db.update_issue_status(issue_id, STATUS_IN_PROGRESS, "Field Specialist", ROLE_DEPT_MEMBER, dept, "Investigation commenced")
    target_dt = (now_dt + dt.timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    db.add_action(
        {
            "issue_id": issue_id,
            "user_id": "field_specialist@storevoice.local",
            "user_role": ROLE_DEPT_MEMBER,
            "department": dept,
            "action_type": "investigation",
            "action_description": "Initial store audit conducted.",
            "progress_notes": "Identified operational bottleneck.",
            "expected_completion": target_dt,
        }
    )
    if final_status == STATUS_IN_PROGRESS:
        return
    if final_status == STATUS_PENDING:
        db.update_issue_status(
            issue_id, STATUS_PENDING, "Field Specialist", ROLE_DEPT_MEMBER, dept, "Waiting for replacement parts"
        )
        return

    db.update_issue_status(
        issue_id, STATUS_AWAITING_VERIFICATION, "Operations Manager", ROLE_DEPT_MGR, dept, "Corrective action completed"
    )
    db.add_action(
        {
            "issue_id": issue_id,
            "user_id": "ops_manager@storevoice.local",
            "user_role": ROLE_DEPT_MGR,
            "department": dept,
            "action_type": "corrective_action",
            "action_description": "Root cause resolved and documented.",
            "progress_notes": "Reinspection passed. Staff briefed.",
        }
    )
    if final_status != STATUS_AWAITING_VERIFICATION:
        _seed_closing_audit(db, issue_id, final_status)


def _seed_closing_audit(db: IssuesDB, issue_id: str, final_status: str) -> None:
    """Seed verification and reopening stages for completed issues."""
    if final_status == STATUS_VERIFIED_CLOSED:
        db.update_issue_status(
            issue_id, STATUS_VERIFIED_CLOSED, "Quality Auditor", ROLE_HEAD_OFFICE_ADMIN, "Head Office", "Verified closure"
        )
        db.add_verification(
            {
                "issue_id": issue_id,
                "verifier_id": "auditor_ho@storevoice.local",
                "decision": "APPROVED",
                "verification_notes": "Audit confirmed compliance.",
            }
        )
    elif final_status == STATUS_REOPENED:
        db.update_issue_status(
            issue_id,
            STATUS_VERIFIED_CLOSED,
            "Quality Auditor",
            ROLE_HEAD_OFFICE_ADMIN,
            "Head Office",
            "Initial verification accepted",
        )
        db.update_issue_status(
            issue_id,
            STATUS_REOPENED,
            "Regional Director",
            ROLE_HEAD_OFFICE_ADMIN,
            "Head Office",
            "Reopened: customer reports recurred",
        )


def _seed_evidence(db: IssuesDB, issue_id: str, id_list_str: str, fb_map: dict[str, dict[str, str]]) -> None:
    """Attach customer feedback quotes as evidence records."""
    if not id_list_str:
        return
    for fid in id_list_str.split(";"):
        fid = fid.strip()
        if not fid:
            continue
        data = fb_map.get(fid, {"channel": "in_app", "text": "Customer reported recurrent store issue."})
        db.add_evidence(
            {
                "issue_id": issue_id,
                "feedback_id": fid,
                "evidence_type": "feedback",
                "channel": data["channel"],
                "feedback_text": data["text"],
            }
        )


def _seed_format_coverage(db: IssuesDB, stores_df: pd.DataFrame, tax_df: pd.DataFrame, now_dt: dt.datetime) -> int:
    """Seed representative issues across all store formats and regions for resolution matrix."""
    tax_items = list(tax_df.itertuples())
    if not tax_items:
        return 0

    count = 0
    statuses = [
        STATUS_VERIFIED_CLOSED,
        STATUS_AWAITING_VERIFICATION,
        STATUS_IN_PROGRESS,
        STATUS_PENDING,
        STATUS_VERIFIED_CLOSED,
    ]

    for (fmt, reg), grp in stores_df.groupby(["format", "region"]):
        for s_idx, (st_id, s_row) in enumerate(grp.head(2).iterrows()):
            t_row = tax_items[(hash(st_id) + s_idx) % len(tax_items)]
            it_id = str(t_row.Index)
            it_name = str(t_row.issue_type)
            dept = str(t_row.owner_function)
            if dept.startswith("None"):
                dept = "Store Ops"

            issue_id = f"ISSUE-SYS-{st_id}-{it_id}"
            if db.get_issue(issue_id):
                continue

            st_name = str(s_row["store_name"])
            is_safety = int(it_id in SAFETY_TYPES)
            severity = "critical" if is_safety else "high"
            status = statuses[(s_idx + count) % len(statuses)]
            detected_iso = (now_dt - dt.timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
            deadlines = IssuesService.calculate_deadlines(severity, bool(is_safety), detected_iso)

            db.insert_issue(
                {
                    "id": issue_id,
                    "source_detection_id": f"SYS-DET-{st_id}-{it_id}",
                    "title": f"{it_name} at {st_name}",
                    "description": f"Audited problem in {it_name} at {st_name} ({fmt}, {reg} Region).",
                    "issue_type_id": it_id,
                    "issue_category": it_name,
                    "severity": severity,
                    "actionability": 1,
                    "is_safety": is_safety,
                    "is_emerging": 0,
                    "store_id": str(st_id),
                    "store_name": st_name,
                    "region": str(reg),
                    "store_format": str(fmt),
                    "owning_department": dept,
                    "assigned_user_id": f"mgr_{dept.lower().replace(' ', '_')}@storevoice.local",
                    "assigned_team": f"{dept} Field Unit",
                    "current_status": status,
                    "pending_reason": "Waiting on replacement component" if status == STATUS_PENDING else None,
                    "detected_at": detected_iso,
                    "created_at": detected_iso,
                    "updated_at": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "ack_deadline": deadlines["ack_deadline"],
                    "res_deadline": deadlines["res_deadline"],
                    "verif_deadline": deadlines["verif_deadline"],
                    "confidence": 0.91,
                    "evidence_count": 2,
                    "next_step": next_step(it_id, dept, True),
                }
            )
            _seed_audit_history(db, issue_id, status, dept, now_dt)
            count += 1
    return count
