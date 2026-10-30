"""Head Office Issue Tracking & Resolution Management schema and constants.

Defines lifecycle statuses, valid transitions, roles, SLA policies, and table DDL.
"""

from __future__ import annotations

from typing import Final

# Lifecycle Statuses
STATUS_NEW: Final[str] = "NEW"
STATUS_ASSIGNED: Final[str] = "ASSIGNED"
STATUS_ACKNOWLEDGED: Final[str] = "ACKNOWLEDGED"
STATUS_IN_PROGRESS: Final[str] = "IN_PROGRESS"
STATUS_PENDING: Final[str] = "PENDING"
STATUS_AWAITING_VERIFICATION: Final[str] = "RESOLVED_AWAITING_VERIFICATION"
STATUS_VERIFIED_CLOSED: Final[str] = "VERIFIED_CLOSED"
STATUS_REOPENED: Final[str] = "REOPENED"

ALL_STATUSES: Final[tuple[str, ...]] = (
    STATUS_NEW,
    STATUS_ASSIGNED,
    STATUS_ACKNOWLEDGED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_AWAITING_VERIFICATION,
    STATUS_VERIFIED_CLOSED,
    STATUS_REOPENED,
)

# Valid State Transitions
VALID_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    STATUS_NEW: frozenset({STATUS_ASSIGNED}),
    STATUS_ASSIGNED: frozenset({STATUS_ACKNOWLEDGED, STATUS_ASSIGNED}),
    STATUS_ACKNOWLEDGED: frozenset({STATUS_IN_PROGRESS, STATUS_PENDING, STATUS_ASSIGNED}),
    STATUS_IN_PROGRESS: frozenset({STATUS_PENDING, STATUS_AWAITING_VERIFICATION, STATUS_ASSIGNED}),
    STATUS_PENDING: frozenset({STATUS_IN_PROGRESS, STATUS_AWAITING_VERIFICATION, STATUS_ASSIGNED}),
    STATUS_AWAITING_VERIFICATION: frozenset({STATUS_VERIFIED_CLOSED, STATUS_IN_PROGRESS, STATUS_REOPENED}),
    STATUS_VERIFIED_CLOSED: frozenset({STATUS_REOPENED}),
    STATUS_REOPENED: frozenset({STATUS_ASSIGNED, STATUS_IN_PROGRESS, STATUS_PENDING}),
}

# Standard Pending / Blocker Reasons
PENDING_REASONS: Final[tuple[str, ...]] = (
    "Waiting for additional information",
    "Waiting for approval",
    "Waiting for replacement or supply",
    "Waiting for external dependency",
    "Store visit or inspection scheduled",
)

# User Roles
ROLE_HEAD_OFFICE_ADMIN: Final[str] = "head_office_admin"
ROLE_REGIONAL_MGR: Final[str] = "regional_manager"
ROLE_DEPT_MGR: Final[str] = "department_manager"
ROLE_DEPT_MEMBER: Final[str] = "department_member"
ROLE_STORE_OWNER: Final[str] = "store_owner"

ALL_ROLES: Final[tuple[str, ...]] = (
    ROLE_HEAD_OFFICE_ADMIN,
    ROLE_REGIONAL_MGR,
    ROLE_DEPT_MGR,
    ROLE_DEPT_MEMBER,
    ROLE_STORE_OWNER,
)

# SLA Hours by Severity (Acknowledgement, Resolution, Verification)
# Critical & Safety issues require same-day response
SLA_HOURS: Final[dict[str, dict[str, int]]] = {
    "critical": {"ack": 4, "resolve": 24, "verify": 24},
    "safety": {"ack": 4, "resolve": 24, "verify": 24},
    "high": {"ack": 24, "resolve": 48, "verify": 48},
    "medium": {"ack": 48, "resolve": 120, "verify": 72},
    "low": {"ack": 72, "resolve": 168, "verify": 72},
}

# SQLite Table DDL
SQLITE_TABLES: Final[str] = """
CREATE TABLE IF NOT EXISTS ho_issues (
    id TEXT PRIMARY KEY,
    source_detection_id TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    issue_type_id TEXT NOT NULL,
    issue_category TEXT NOT NULL,
    severity TEXT NOT NULL,
    actionability INTEGER DEFAULT 1,
    is_safety INTEGER DEFAULT 0,
    is_emerging INTEGER DEFAULT 0,
    store_id TEXT NOT NULL,
    store_name TEXT NOT NULL,
    region TEXT NOT NULL,
    store_format TEXT DEFAULT 'Saffron Market',
    owning_department TEXT NOT NULL,
    assigned_user_id TEXT,
    assigned_team TEXT,
    current_status TEXT NOT NULL DEFAULT 'NEW',
    pending_reason TEXT,
    detected_at TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    acknowledged_at TEXT,
    resolved_at TEXT,
    verified_at TEXT,
    reopened_at TEXT,
    ack_deadline TEXT,
    res_deadline TEXT,
    verif_deadline TEXT,
    confidence REAL DEFAULT 0.0,
    evidence_count INTEGER DEFAULT 1,
    next_step TEXT,
    resolution_summary TEXT,
    verification_notes TEXT,
    verified_by TEXT,
    reopened_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ho_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id TEXT NOT NULL,
    previous_status TEXT,
    new_status TEXT NOT NULL,
    changed_by TEXT NOT NULL,
    user_role TEXT NOT NULL,
    department TEXT,
    reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ho_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_role TEXT NOT NULL,
    department TEXT NOT NULL,
    action_type TEXT NOT NULL,
    action_description TEXT NOT NULL,
    progress_notes TEXT,
    blockers TEXT,
    expected_completion TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ho_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id TEXT NOT NULL,
    feedback_id TEXT,
    evidence_type TEXT NOT NULL,
    channel TEXT,
    feedback_text TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ho_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id TEXT NOT NULL,
    verifier_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    rejection_reason TEXT,
    verification_notes TEXT,
    verified_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ho_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id TEXT NOT NULL,
    recipient_role TEXT NOT NULL,
    recipient_department TEXT,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    read_status INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ho_issues_status ON ho_issues(current_status);
CREATE INDEX IF NOT EXISTS idx_ho_issues_dept ON ho_issues(owning_department);
CREATE INDEX IF NOT EXISTS idx_ho_issues_region ON ho_issues(region);
CREATE INDEX IF NOT EXISTS idx_ho_history_issue ON ho_status_history(issue_id);
CREATE INDEX IF NOT EXISTS idx_ho_actions_issue ON ho_actions(issue_id);
CREATE INDEX IF NOT EXISTS idx_ho_evidence_issue ON ho_evidence(issue_id);
"""

# PostgreSQL DDL for Supabase
POSTGRES_TABLES: Final[str] = """
CREATE TABLE IF NOT EXISTS public.ho_issues (
    id VARCHAR(64) PRIMARY KEY,
    source_detection_id VARCHAR(64),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    issue_type_id VARCHAR(16) NOT NULL,
    issue_category TEXT NOT NULL,
    severity VARCHAR(16) NOT NULL,
    actionability SMALLINT DEFAULT 1,
    is_safety SMALLINT DEFAULT 0,
    is_emerging SMALLINT DEFAULT 0,
    store_id VARCHAR(32) NOT NULL,
    store_name TEXT NOT NULL,
    region VARCHAR(64) NOT NULL,
    store_format VARCHAR(64) DEFAULT 'Saffron Market',
    owning_department VARCHAR(64) NOT NULL,
    assigned_user_id VARCHAR(64),
    assigned_team VARCHAR(64),
    current_status VARCHAR(32) NOT NULL DEFAULT 'NEW',
    pending_reason TEXT,
    detected_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    acknowledged_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    verified_at TIMESTAMPTZ,
    reopened_at TIMESTAMPTZ,
    ack_deadline TIMESTAMPTZ,
    res_deadline TIMESTAMPTZ,
    verif_deadline TIMESTAMPTZ,
    confidence NUMERIC DEFAULT 0.0,
    evidence_count INTEGER DEFAULT 1,
    next_step TEXT,
    resolution_summary TEXT,
    verification_notes TEXT,
    verified_by VARCHAR(64),
    reopened_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS public.ho_status_history (
    id BIGSERIAL PRIMARY KEY,
    issue_id VARCHAR(64) NOT NULL REFERENCES public.ho_issues(id) ON DELETE CASCADE,
    previous_status VARCHAR(32),
    new_status VARCHAR(32) NOT NULL,
    changed_by VARCHAR(64) NOT NULL,
    user_role VARCHAR(32) NOT NULL,
    department VARCHAR(64),
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.ho_actions (
    id BIGSERIAL PRIMARY KEY,
    issue_id VARCHAR(64) NOT NULL REFERENCES public.ho_issues(id) ON DELETE CASCADE,
    user_id VARCHAR(64) NOT NULL,
    user_role VARCHAR(32) NOT NULL,
    department VARCHAR(64) NOT NULL,
    action_type VARCHAR(32) NOT NULL,
    action_description TEXT NOT NULL,
    progress_notes TEXT,
    blockers TEXT,
    expected_completion TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.ho_evidence (
    id BIGSERIAL PRIMARY KEY,
    issue_id VARCHAR(64) NOT NULL REFERENCES public.ho_issues(id) ON DELETE CASCADE,
    feedback_id VARCHAR(32),
    evidence_type VARCHAR(32) NOT NULL,
    channel VARCHAR(32),
    feedback_text TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.ho_verifications (
    id BIGSERIAL PRIMARY KEY,
    issue_id VARCHAR(64) NOT NULL REFERENCES public.ho_issues(id) ON DELETE CASCADE,
    verifier_id VARCHAR(64) NOT NULL,
    decision VARCHAR(32) NOT NULL,
    rejection_reason TEXT,
    verification_notes TEXT,
    verified_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.ho_notifications (
    id BIGSERIAL PRIMARY KEY,
    issue_id VARCHAR(64) NOT NULL,
    recipient_role VARCHAR(32) NOT NULL,
    recipient_department VARCHAR(64),
    event_type VARCHAR(64) NOT NULL,
    message TEXT NOT NULL,
    read_status SMALLINT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ho_issues_status ON public.ho_issues(current_status);
CREATE INDEX IF NOT EXISTS idx_ho_issues_dept ON public.ho_issues(owning_department);
CREATE INDEX IF NOT EXISTS idx_ho_issues_region ON public.ho_issues(region);

ALTER TABLE public.ho_issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ho_status_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ho_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ho_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ho_verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ho_notifications ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow read ho_issues" ON public.ho_issues FOR SELECT USING (true);
CREATE POLICY "Allow write ho_issues" ON public.ho_issues FOR ALL USING (true);
CREATE POLICY "Allow read ho_history" ON public.ho_status_history FOR SELECT USING (true);
CREATE POLICY "Allow write ho_history" ON public.ho_status_history FOR ALL USING (true);
CREATE POLICY "Allow read ho_actions" ON public.ho_actions FOR SELECT USING (true);
CREATE POLICY "Allow write ho_actions" ON public.ho_actions FOR ALL USING (true);
CREATE POLICY "Allow read ho_evidence" ON public.ho_evidence FOR SELECT USING (true);
CREATE POLICY "Allow write ho_evidence" ON public.ho_evidence FOR ALL USING (true);
CREATE POLICY "Allow read ho_verifications" ON public.ho_verifications FOR SELECT USING (true);
CREATE POLICY "Allow write ho_verifications" ON public.ho_verifications FOR ALL USING (true);
CREATE POLICY "Allow read ho_notifications" ON public.ho_notifications FOR SELECT USING (true);
CREATE POLICY "Allow write ho_notifications" ON public.ho_notifications FOR ALL USING (true);
"""

