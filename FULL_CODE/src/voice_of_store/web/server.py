"""Flask application factory. All user-controlled values are validated against allow-lists before use."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file

from ..assistant import MAX_QUESTION_CHARS, Assistant
from ..brief import render_html
from ..routing import ESCALATION_RULE
from ..text import csv_safe
from .security import SecurityConfig, install
from .state import AppState

STATIC = Path(__file__).resolve().parent / "static"
STATIC_FILES = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
STATIC_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID = re.compile(r"^[A-Za-z0-9-]{1,16}$")


def _register_static(app: Flask) -> None:
    def static_page() -> Response:
        """Serve one file from the fixed static table."""
        name = STATIC_FILES[request.path]  # key comes from a fixed table, never from the user
        return send_file(STATIC / name, mimetype=STATIC_TYPES[name].split(";")[0], max_age=0)

    for path in STATIC_FILES:
        app.add_url_rule(path, endpoint="static_" + path.strip("/").replace(".", "_"), view_func=static_page, methods=["GET"])


def _only(*names: str) -> None:
    """The query string must hold exactly these keys, each once: no unknown or repeated parameters."""
    keys = list(request.args.keys())
    if set(keys) != set(names) or any(len(request.args.getlist(k)) != 1 for k in keys):
        abort(400)


def _arg(name: str, allowed: frozenset[str], pattern: re.Pattern | None = None) -> str:
    """A query value that must be in the allow-list built at start-up (and match the pattern, when given)."""
    v = request.args.get(name, "")
    if (pattern and not pattern.match(v)) or v not in allowed:
        abort(400)
    return v


@dataclass(frozen=True)
class Allowed:
    """Every value a query string or body may name, built once at start-up from the loaded data."""

    channels: frozenset[str]
    types: frozenset[str]
    stores: frozenset[str]
    regions: frozenset[str]
    weeks: frozenset[str]


CSV_HEAD = [
    "week_start",
    "store_id",
    "store",
    "region",
    "issue_type_id",
    "issue",
    "owner",
    "confidence",
    "evidence_count",
    "what_changed",
    "next_step",
]


def flags_csv(week: str, flags: list[dict]) -> str:
    """The week's flags as CSV text. Every cell passes `csv_safe`, so a name cannot become a spreadsheet formula."""
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    out.writerow(CSV_HEAD)
    for f in flags:
        row = [
            week,
            f["store_id"],
            f["store"],
            f["region"],
            f["issue_type"],
            f["issue"],
            f["owner"],
            f["confidence"],
            len(f["evidence"]),
            f["change"]["summary"],
            f["next_step"],
        ]
        out.writerow([csv_safe(v) for v in row])
    return buf.getvalue()


def _core_routes(app: Flask, state: AppState, meta: dict) -> None:
    """Routes with no parameters: health, metadata, precision statement and the evaluation report."""

    @app.get("/api/health")
    def health() -> Response:
        """Liveness probe; the only route open without login."""
        _only()
        return jsonify(status="ok")

    @app.get("/api/meta")
    def get_meta() -> Response:
        """Regions, weeks, issue types, channels, stores and the escalation rule."""
        _only()
        return jsonify(dict(meta, escalation_rule=ESCALATION_RULE))

    @app.get("/api/validation")
    def get_validation() -> Response:
        """The precision statement."""
        _only()
        return jsonify(state.validation())

    @app.get("/report")
    def report_page() -> Response:
        """The evaluation report page."""
        _only()
        return Response(state.report_html(), mimetype="text/html")

    @app.get("/api/report")
    def get_report() -> Response:
        """The evaluation report as JSON."""
        _only()
        return jsonify(state.report())


def _view_routes(app: Flask, state: AppState, ok: Allowed) -> None:
    """Read-only views: briefs, flags, series, export and the store page. Every value is checked against `ok`."""

    @app.get("/api/brief")
    def get_brief() -> Response:
        """Top issues for one region and week as JSON."""
        _only("region", "week")
        region, week = _arg("region", ok.regions), _arg("week", ok.weeks, _DATE)
        return jsonify(region=region, week=week, rows_used=state.week_rows(region, week), entries=state.brief(region, week))

    @app.get("/brief")
    def brief_page() -> Response:
        """The printable one-page brief."""
        _only("region", "week")
        region, week = _arg("region", ok.regions), _arg("week", ok.weeks, _DATE)
        return Response(render_html(region, week, state.brief(region, week), state.week_rows(region, week)), mimetype="text/html")

    @app.get("/api/flags")
    def get_flags() -> Response:
        """Emerging-issue flags for a week with evidence and what changed."""
        _only("week")
        week = _arg("week", ok.weeks, _DATE)
        return jsonify(week=week, flags=state.flags_for(week))

    @app.get("/api/series")
    def get_series() -> Response:
        """Weekly counts for one store and issue type."""
        _only("store_id", "issue_type")
        return jsonify(state.series(_arg("store_id", ok.stores, _ID), _arg("issue_type", ok.types)))

    @app.get("/api/export")
    def export_flags() -> Response:
        """The week's flags as a CSV download, formula-injection safe."""
        _only("week")
        week = _arg("week", ok.weeks, _DATE)
        resp = Response(flags_csv(week, state.flags_for(week)), mimetype="text/csv")
        resp.headers["Content-Disposition"] = f'attachment; filename="r5_flags_{week}.csv"'  # week is allow-listed
        return resp

    @app.get("/api/store")
    def get_store() -> Response:
        """Status of one store for a week."""
        _only("store_id", "week")
        return jsonify(state.store_overview(_arg("store_id", ok.stores, _ID), _arg("week", ok.weeks, _DATE)))


def _post_routes(app: Flask, state: AppState, ok: Allowed, cfg: SecurityConfig) -> None:
    """The two JSON POST endpoints: exact field sets, bounded lengths, allow-listed channel."""
    assistant = Assistant(state)

    @app.post("/api/assistant")
    def post_assistant() -> Response:
        """Answer one question of at most 300 characters."""
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"message"}:
            abort(400)
        message = body["message"]
        if not isinstance(message, str) or not message.strip() or len(message) > MAX_QUESTION_CHARS:
            abort(400)
        return jsonify(assistant.ask(message))

    @app.post("/api/classify")
    def post_classify() -> Response:
        """Classify one comment."""
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) - {"text", "channel"}:
            abort(400)
        text, channel = body.get("text"), body.get("channel", "in_app")
        if not isinstance(text, str) or not text.strip() or len(text) > cfg.max_text_chars or channel not in ok.channels:
            abort(400)
        return jsonify(state.classify(text, channel))


def _register_api(app: Flask, state: AppState, cfg: SecurityConfig) -> None:
    """Build the allow-lists from the loaded data and register every API and page route."""
    meta = state.meta()
    ok = Allowed(
        channels=frozenset(meta["channels"]),
        types=frozenset(t["id"] for t in meta["issue_types"]),
        stores=frozenset(s["id"] for s in meta["stores"]),
        regions=frozenset(state.regions),
        weeks=frozenset(state.weeks),
    )
    _core_routes(app, state, meta)
    _view_routes(app, state, ok)
    _post_routes(app, state, ok, cfg)


def create_app(state: AppState, cfg: SecurityConfig | None = None) -> Flask:
    """Flask application factory. All user-controlled values are validated against allow-lists before use."""
    cfg = cfg or SecurityConfig.from_env()
    app = Flask(__name__, static_folder=None)
    install(app, cfg)
    _register_static(app)
    _register_api(app, state, cfg)
    return app
