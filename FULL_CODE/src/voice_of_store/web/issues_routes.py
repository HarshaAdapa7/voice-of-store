"""Flask routes for Head Office Issue Tracking & Resolution Management."""

from __future__ import annotations

from typing import Any

from flask import Flask, Response, jsonify, request

from ..issues_schema import (
    ROLE_DEPT_MEMBER,
    ROLE_DEPT_MGR,
    ROLE_HEAD_OFFICE_ADMIN,
    ROLE_REGIONAL_MGR,
    ROLE_STORE_OWNER,
    STATUS_AWAITING_VERIFICATION,
    STATUS_PENDING,
    STATUS_VERIFIED_CLOSED,
)
from ..issues_service import IssuesService


def _user_context() -> dict[str, str]:
    """Extract user role, department, region, and store from headers or query."""
    role = request.headers.get("X-User-Role") or request.args.get("user_role") or ROLE_HEAD_OFFICE_ADMIN
    dept = request.headers.get("X-User-Dept") or request.args.get("user_dept") or ""
    region = request.headers.get("X-User-Region") or request.args.get("user_region") or ""
    store_id = request.headers.get("X-User-Store") or request.args.get("user_store") or ""
    return {"role": role, "dept": dept, "region": region, "store_id": store_id}


def _extract_query_filters(ctx: dict[str, str]) -> dict[str, Any]:
    """Build filter dictionary based on user role and query parameters."""
    filters: dict[str, Any] = {}
    if ctx["role"] in (ROLE_DEPT_MGR, ROLE_DEPT_MEMBER) and ctx["dept"]:
        filters["department"] = ctx["dept"]
    elif ctx["role"] == ROLE_REGIONAL_MGR and ctx["region"]:
        filters["region"] = ctx["region"]
    elif ctx["role"] == ROLE_STORE_OWNER and ctx.get("store_id") and not request.args.get("store_id"):
        filters["store_id"] = ctx["store_id"]

    for k in (
        "department",
        "region",
        "status",
        "severity",
        "store_id",
        "store_format",
        "category",
        "resolution_status",
        "search",
    ):
        val = request.args.get(k)
        if val:
            filters[k] = val
    return filters


def _register_query_routes(app: Flask, service: IssuesService) -> None:
    """Register read-only query endpoints for issues and KPIs."""

    @app.get("/api/ho/resolution_matrix")
    def get_resolution_matrix() -> Response:
        """Store-by-store problem resolution verification matrix."""
        ctx = _user_context()
        filters = _extract_query_filters(ctx)
        return jsonify(service.get_resolution_matrix(filters))

    @app.get("/api/ho/kpis")
    def get_ho_kpis() -> Response:
        """Dashboard overview metrics with role-based scoping."""
        ctx = _user_context()
        filters = _extract_query_filters(ctx)
        return jsonify(service.get_kpis(filters))

    @app.get("/api/ho/issues")
    def list_ho_issues() -> Response:
        """List issues matching filters, decorated with live SLA overdue metrics."""
        ctx = _user_context()
        filters = _extract_query_filters(ctx)
        view = request.args.get("view", "")

        if view == "awaiting_verification":
            filters["status"] = STATUS_AWAITING_VERIFICATION
        elif view == "pending":
            filters["status"] = STATUS_PENDING
        elif view == "resolved":
            filters["status"] = STATUS_VERIFIED_CLOSED

        issues = service.db.list_issues(filters)
        decorated: list[dict[str, Any]] = []
        for it in issues:
            ov = service.check_overdue(it)
            it_dict = dict(it)
            it_dict["overdue_info"] = ov
            if view == "overdue" and not ov["is_overdue"]:
                continue
            decorated.append(it_dict)
        return jsonify(total=len(decorated), issues=decorated)

    @app.get("/api/ho/issue/<issue_id>")
    def get_ho_issue(issue_id: str) -> Response | tuple[Response, int]:
        """Retrieve complete issue details, actions, evidence, and audit history."""
        details = service.db.get_issue_details(issue_id)
        if not details:
            return jsonify(error="Issue not found"), 404
        details["overdue_info"] = service.check_overdue(details)
        return jsonify(details)


def _register_status_routes(app: Flask, service: IssuesService) -> None:
    """Register status transition routes."""

    @app.post("/api/ho/issue/<issue_id>/status")
    def update_ho_status(issue_id: str) -> Response | tuple[Response, int]:
        """Transition issue status with mandatory validation and audit logging."""
        body = request.get_json(silent=True) or {}
        new_status = body.get("new_status")
        changed_by = body.get("changed_by", "system")
        user_role = body.get("user_role", ROLE_HEAD_OFFICE_ADMIN)
        department = body.get("department", "Head Office")
        reason = body.get("reason")

        if not new_status:
            return jsonify(error="new_status is required"), 400

        ok, msg = service.change_status(issue_id, new_status, changed_by, user_role, department, reason)
        return (jsonify(status="ok", message=msg), 200) if ok else (jsonify(error=msg), 400)


def _register_action_routes(app: Flask, service: IssuesService) -> None:
    """Record store owner or department corrective action or progress update."""

    @app.post("/api/ho/issue/<issue_id>/action")
    def add_ho_action(issue_id: str) -> Response | tuple[Response, int]:
        """Record store owner or department corrective action or progress update."""
        body = request.get_json(silent=True) or {}
        desc = body.get("action_description", "").strip()
        if not desc:
            return jsonify(error="action_description is required"), 400

        user_role = body.get("user_role", ROLE_STORE_OWNER)
        user_id = body.get("user_id", "store_owner@storevoice.local")
        dept = body.get("department", "Store Operations")
        target_status = body.get("target_status")
        notes = body.get("progress_notes", "")
        blockers = body.get("blockers", "")

        action_data = {
            "issue_id": issue_id,
            "user_id": user_id,
            "user_role": user_role,
            "department": dept,
            "action_type": body.get("action_type", "corrective"),
            "action_description": desc,
            "progress_notes": notes,
            "blockers": blockers,
            "expected_completion": body.get("expected_completion"),
        }
        action_id = service.db.add_action(action_data)

        status_msg = ""
        if target_status:
            reason = blockers if target_status == STATUS_PENDING else desc
            ok, msg = service.change_status(
                issue_id=issue_id,
                new_status=target_status,
                changed_by=user_id,
                user_role=user_role,
                department=dept,
                reason=reason,
            )
            status_msg = msg

        return jsonify(status="ok", action_id=action_id, status_message=status_msg)


def _register_verification_routes(app: Flask, service: IssuesService) -> None:
    """Register verification and reopening routes."""

    @app.post("/api/ho/issue/<issue_id>/verify")
    def verify_ho_issue(issue_id: str) -> Response | tuple[Response, int]:
        """Head Office resolution verification decision (Approve or Reject)."""
        body = request.get_json(silent=True) or {}
        verifier_id = body.get("verifier_id", "admin@storevoice.local")
        user_role = body.get("user_role", ROLE_HEAD_OFFICE_ADMIN)
        decision = body.get("decision", "").upper()
        notes = body.get("notes")
        rejection_reason = body.get("rejection_reason")

        ok, msg = service.record_verification(issue_id, verifier_id, user_role, decision, notes, rejection_reason)
        return (jsonify(status="ok", message=msg), 200) if ok else (jsonify(error=msg), 400)

    @app.post("/api/ho/issue/<issue_id>/reopen")
    def reopen_ho_issue(issue_id: str) -> Response | tuple[Response, int]:
        """Reopen a previously closed issue when recurrence is detected."""
        body = request.get_json(silent=True) or {}
        changed_by = body.get("changed_by", "auditor@storevoice.local")
        user_role = body.get("user_role", ROLE_HEAD_OFFICE_ADMIN)
        department = body.get("department", "Head Office")
        reason = body.get("reason", "").strip()

        if not reason:
            return jsonify(error="A clear reason is required to reopen an issue"), 400

        ok, msg = service.change_status(issue_id, "REOPENED", changed_by, user_role, department, reason)
        return (jsonify(status="ok", message=msg), 200) if ok else (jsonify(error=msg), 400)


def _register_report_routes(app: Flask, service: IssuesService) -> None:
    """Register notifications and operational reporting endpoints."""

    @app.get("/api/ho/notifications")
    def get_ho_notifications() -> Response:
        """Retrieve recent escalation and SLA notifications."""
        ctx = _user_context()
        notifs = service.db.get_notifications(ctx["role"], ctx["dept"])
        return jsonify(notifications=notifs)

    @app.get("/api/ho/performance")
    def get_ho_performance() -> Response:
        """Department operational efficiency and resolution performance report."""
        issues = service.db.list_issues()
        perf: dict[str, dict[str, Any]] = {}
        for it in issues:
            dept = it.get("owning_department") or "Store Ops"
            if dept not in perf:
                perf[dept] = {"department": dept, "total": 0, "open": 0, "closed": 0, "reopened": 0, "overdue": 0, "ack_count": 0}
            perf[dept]["total"] += 1
            if it.get("current_status") == STATUS_VERIFIED_CLOSED:
                perf[dept]["closed"] += 1
            else:
                perf[dept]["open"] += 1
            if int(it.get("reopened_count") or 0) > 0:
                perf[dept]["reopened"] += 1
            if it.get("acknowledged_at"):
                perf[dept]["ack_count"] += 1
            if service.check_overdue(it)["is_overdue"]:
                perf[dept]["overdue"] += 1

        rows = []
        for _, s in perf.items():
            tot = s["total"]
            s["resolution_rate"] = round((s["closed"] / tot) * 100, 1) if tot > 0 else 0.0
            s["ack_rate"] = round((s["ack_count"] / tot) * 100, 1) if tot > 0 else 0.0
            rows.append(s)

        return jsonify(performance=rows)


def register_ho_routes(app: Flask, service: IssuesService) -> None:
    """Register all Head Office control center REST endpoints."""
    _register_query_routes(app, service)
    _register_status_routes(app, service)
    _register_action_routes(app, service)
    _register_verification_routes(app, service)
    _register_report_routes(app, service)
