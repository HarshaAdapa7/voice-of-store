"""Flask application factory. All user-controlled values are validated against allow-lists before use."""

from __future__ import annotations

import re
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file

from ..assistant import MAX_QUESTION_CHARS, Assistant
from ..brief import render_html
from ..routing import ESCALATION_RULE
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
        name = STATIC_FILES[request.path]  # key comes from a fixed table, never from the user
        return send_file(STATIC / name, mimetype=STATIC_TYPES[name].split(";")[0], max_age=0)

    for path in STATIC_FILES:
        app.add_url_rule(path, endpoint="static_" + path.strip("/").replace(".", "_"), view_func=static_page, methods=["GET"])


def _arg(name: str, allowed: set, pattern: re.Pattern | None = None) -> str:
    """A query value that must be in the allow-list built at start-up (and match the pattern, when given)."""
    v = request.args.get(name, "")
    if (pattern and not pattern.match(v)) or v not in allowed:
        abort(400)
    return v


def _register_api(app: Flask, state: AppState, cfg: SecurityConfig) -> None:
    meta = state.meta()
    channels = set(meta["channels"])
    types = {t["id"] for t in meta["issue_types"]}
    stores = {s["id"] for s in meta["stores"]}
    regions, weeks = set(state.regions), set(state.weeks)
    assistant = Assistant(state)

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.get("/api/meta")
    def get_meta():
        return jsonify(dict(meta, escalation_rule=ESCALATION_RULE))

    @app.get("/api/brief")
    def get_brief():
        region, week = _arg("region", regions), _arg("week", weeks, _DATE)
        return jsonify(region=region, week=week, rows_used=state.week_rows(region, week), entries=state.brief(region, week))

    @app.get("/brief")
    def brief_page():
        region, week = _arg("region", regions), _arg("week", weeks, _DATE)
        return Response(render_html(region, week, state.brief(region, week), state.week_rows(region, week)), mimetype="text/html")

    @app.get("/api/flags")
    def get_flags():
        week = _arg("week", weeks, _DATE)
        return jsonify(week=week, flags=state.flags_for(week))

    @app.get("/api/series")
    def get_series():
        return jsonify(state.series(_arg("store_id", stores, _ID), _arg("issue_type", types)))

    @app.get("/api/validation")
    def get_validation():
        return jsonify(state.validation())

    @app.get("/api/store")
    def get_store():
        return jsonify(state.store_overview(_arg("store_id", stores, _ID), _arg("week", weeks, _DATE)))

    @app.post("/api/assistant")
    def post_assistant():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"message"}:
            abort(400)
        message = body["message"]
        if not isinstance(message, str) or not message.strip() or len(message) > MAX_QUESTION_CHARS:
            abort(400)
        return jsonify(assistant.ask(message))

    @app.post("/api/classify")
    def post_classify():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) - {"text", "channel"}:
            abort(400)
        text, channel = body.get("text"), body.get("channel", "in_app")
        if not isinstance(text, str) or not text.strip() or len(text) > cfg.max_text_chars or channel not in channels:
            abort(400)
        return jsonify(state.classify(text, channel))


def create_app(state: AppState, cfg: SecurityConfig | None = None) -> Flask:
    """Flask application factory. All user-controlled values are validated against allow-lists before use."""
    cfg = cfg or SecurityConfig.from_env()
    app = Flask(__name__, static_folder=None)
    install(app, cfg)
    _register_static(app)
    _register_api(app, state, cfg)
    return app
