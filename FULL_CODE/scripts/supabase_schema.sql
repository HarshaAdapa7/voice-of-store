-- Supabase Schema for Voice of Store (Retail Intelligence Platform)
-- Run this in your Supabase SQL Editor (Dashboard -> SQL Editor -> New query)

-- Enable useful extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Store Master Table
CREATE TABLE IF NOT EXISTS public.stores (
    store_id VARCHAR(32) PRIMARY KEY,
    store_name TEXT NOT NULL,
    store_format VARCHAR(64) DEFAULT 'Saffron Market',
    region VARCHAR(64) NOT NULL,
    avg_weekly_footfall NUMERIC DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 2. Issue Taxonomy Table
CREATE TABLE IF NOT EXISTS public.issue_taxonomy (
    issue_type_id VARCHAR(16) PRIMARY KEY,
    issue_type TEXT NOT NULL,
    owner_function VARCHAR(64) NOT NULL,
    policy_severity_floor VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 3. Week Calendar Table
CREATE TABLE IF NOT EXISTS public.week_calendar (
    week_index INTEGER PRIMARY KEY,
    week_start DATE NOT NULL UNIQUE,
    labelled_period VARCHAR(32)
);

-- 4. Feedback Table
CREATE TABLE IF NOT EXISTS public.feedback (
    feedback_id VARCHAR(32) PRIMARY KEY,
    channel VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    store_id VARCHAR(32) REFERENCES public.stores(store_id) ON DELETE SET NULL,
    text TEXT NOT NULL,
    rating NUMERIC,
    imported_at TIMESTAMPTZ DEFAULT now()
);

-- 5. Feedback Labels Table (Ground Truth / Verified)
CREATE TABLE IF NOT EXISTS public.feedback_labels (
    feedback_id VARCHAR(32) PRIMARY KEY REFERENCES public.feedback(feedback_id) ON DELETE CASCADE,
    issue_type_id VARCHAR(16) REFERENCES public.issue_taxonomy(issue_type_id),
    severity VARCHAR(16) NOT NULL,
    actionable SMALLINT NOT NULL CHECK (actionable IN (0, 1))
);

-- 6. Emerging Flags Table (Detector Output)
CREATE TABLE IF NOT EXISTS public.emerging_flags (
    id BIGSERIAL PRIMARY KEY,
    as_of_week_start DATE NOT NULL,
    store_id VARCHAR(32) REFERENCES public.stores(store_id) ON DELETE CASCADE,
    issue_type_id VARCHAR(16) REFERENCES public.issue_taxonomy(issue_type_id) ON DELETE CASCADE,
    confidence NUMERIC NOT NULL,
    evidence_feedback_ids TEXT[] DEFAULT ARRAY[]::TEXT[],
    what_changed TEXT,
    next_step TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 7. Model Predictions Table
CREATE TABLE IF NOT EXISTS public.predictions (
    feedback_id VARCHAR(32) PRIMARY KEY,
    issue_type_id VARCHAR(16) REFERENCES public.issue_taxonomy(issue_type_id),
    severity VARCHAR(16) NOT NULL,
    actionable SMALLINT NOT NULL CHECK (actionable IN (0, 1)),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 8. Alert Audit Logs Table
CREATE TABLE IF NOT EXISTS public.alert_audit_logs (
    id BIGSERIAL PRIMARY KEY,
    week DATE NOT NULL,
    batch_id VARCHAR(64) NOT NULL,
    approved_by VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    recipient_count INTEGER DEFAULT 0,
    payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_stores_region ON public.stores (region);
CREATE INDEX IF NOT EXISTS idx_feedback_store ON public.feedback (store_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON public.feedback (created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_channel ON public.feedback (channel);
CREATE INDEX IF NOT EXISTS idx_emerging_flags_week ON public.emerging_flags (as_of_week_start);
CREATE INDEX IF NOT EXISTS idx_emerging_flags_store ON public.emerging_flags (store_id);
CREATE INDEX IF NOT EXISTS idx_alert_audit_batch ON public.alert_audit_logs (batch_id);

-- Enable Row Level Security (RLS)
ALTER TABLE public.stores ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.issue_taxonomy ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.week_calendar ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback_labels ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.emerging_flags ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.predictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alert_audit_logs ENABLE ROW LEVEL SECURITY;

-- Read policies for anon & authenticated roles
CREATE POLICY "Allow read stores" ON public.stores FOR SELECT USING (true);
CREATE POLICY "Allow read taxonomy" ON public.issue_taxonomy FOR SELECT USING (true);
CREATE POLICY "Allow read calendar" ON public.week_calendar FOR SELECT USING (true);
CREATE POLICY "Allow read feedback" ON public.feedback FOR SELECT USING (true);
CREATE POLICY "Allow read labels" ON public.feedback_labels FOR SELECT USING (true);
CREATE POLICY "Allow read flags" ON public.emerging_flags FOR SELECT USING (true);
CREATE POLICY "Allow read predictions" ON public.predictions FOR SELECT USING (true);
CREATE POLICY "Allow read audit logs" ON public.alert_audit_logs FOR SELECT USING (true);

-- Write policies for inserting/updating records
CREATE POLICY "Allow insert feedback" ON public.feedback FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow insert flags" ON public.emerging_flags FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow insert predictions" ON public.predictions FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow insert audit logs" ON public.alert_audit_logs FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow insert stores" ON public.stores FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow insert taxonomy" ON public.issue_taxonomy FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow insert calendar" ON public.week_calendar FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow insert labels" ON public.feedback_labels FOR INSERT WITH CHECK (true);



-- ==========================================
-- Head Office Issue Tracking & Resolution System
-- ==========================================

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
    store_format VARCHAR(64) DEFAULT 'Saffron Market',
    region VARCHAR(64) NOT NULL,
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
