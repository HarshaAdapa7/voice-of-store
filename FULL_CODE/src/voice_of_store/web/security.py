"""Security layer for the web app: headers, host allow-list, origin check, body limits, rate limiting, optional API key.

Threat model (stated plainly): the app serves read-only analytics over synthetic data and one stateless classify endpoint.
It has no accounts, cookies, database or file upload. The main risks are therefore XSS through feedback text, DNS rebinding
and cross-site requests against a localhost server, resource exhaustion, information leaks through errors or logs, and
supply-chain issues. Each has a control below; none of them replaces running behind a TLS-terminating reverse proxy when the
app is exposed beyond localhost.
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from flask import Flask, Response, g, jsonify, request

log = logging.getLogger("voice_of_store.web")

JSON_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
PAGE_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'")
BRIEF_CSP = ("default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; "
             "frame-ancestors 'none'; object-src 'none'")  # the printable brief is static HTML with inline CSS, no script


@dataclass
class SecurityConfig:
    allowed_hosts: frozenset = frozenset({"127.0.0.1", "localhost", "[::1]"})
    max_body_bytes: int = 8 * 1024
    max_text_chars: int = 2000
    rate_per_minute: int = 120          # all endpoints, per client address
    classify_per_minute: int = 20       # the one POST endpoint
    max_tracked_clients: int = 5000
    api_key: str | None = None          # when set, /api/classify requires header X-API-Key
    behind_https: bool = False          # adds HSTS (only set when TLS is terminated in front of the app)
    trust_proxy: bool = False           # read the client address from X-Forwarded-For (only behind a trusted proxy)
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> SecurityConfig:
        hosts = {h.strip().lower() for h in os.environ.get("R5_ALLOWED_HOSTS", "").split(",") if h.strip()}
        cfg = cls()
        if hosts:
            cfg.allowed_hosts = frozenset(hosts | {"127.0.0.1", "localhost", "[::1]"})
        cfg.api_key = os.environ.get("R5_API_KEY") or None
        cfg.behind_https = os.environ.get("R5_HTTPS") == "1"
        cfg.trust_proxy = os.environ.get("R5_TRUST_PROXY") == "1"
        return cfg


class RateLimiter:
    """Fixed-window counter per (client, bucket) with bounded memory. In-process, so per worker."""

    def __init__(self, max_clients: int):
        self._lock = threading.Lock()
        self._hits: OrderedDict = OrderedDict()
        self._max = max_clients

    def allow(self, client: str, bucket: str, limit: int, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        window = int(now // 60)
        key = (client, bucket)
        with self._lock:
            w, n = self._hits.get(key, (window, 0))
            if w != window:
                w, n = window, 0
            n += 1
            self._hits[key] = (w, n)
            self._hits.move_to_end(key)
            while len(self._hits) > self._max:
                self._hits.popitem(last=False)
            return n <= limit


def _client_ip(cfg: SecurityConfig) -> str:
    if cfg.trust_proxy:
        fwd = request.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[-1].strip()[:64]  # the address added by our own proxy is the last one
    return (request.remote_addr or "unknown")[:64]


def _host_only(value: str) -> str:
    v = value.strip().lower()
    if v.startswith("["):                      # [::1]:8000
        return v.split("]")[0] + "]"
    return v.split(":")[0]


def _err(status: int, message: str) -> Response:
    resp = jsonify(error=message, request_id=getattr(g, "request_id", "-"))
    resp.status_code = status
    return resp


def install(app: Flask, cfg: SecurityConfig) -> None:
    limiter = RateLimiter(cfg.max_tracked_clients)
    app.config["MAX_CONTENT_LENGTH"] = cfg.max_body_bytes
    app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _guard():  # noqa: ANN202
        g.request_id = uuid.uuid4().hex[:12]
        g.t0 = time.time()
        host = _host_only(request.headers.get("Host", ""))
        if host not in cfg.allowed_hosts:                       # DNS-rebinding and host-header attacks
            return _err(400, "host not allowed")
        client = _client_ip(cfg)
        if not limiter.allow(client, "all", cfg.rate_per_minute):
            resp = _err(429, "too many requests")
            resp.headers["Retry-After"] = "60"
            return resp
        if request.method not in ("GET", "HEAD", "POST"):
            return _err(405, "method not allowed")
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and _host_only(urlsplit(origin).netloc) not in cfg.allowed_hosts:   # cross-site request
                return _err(403, "cross-origin request refused")
            if request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
                return _err(403, "cross-site request refused")
            if request.mimetype != "application/json":
                return _err(415, "content type must be application/json")
            if not limiter.allow(client, "classify", cfg.classify_per_minute):
                resp = _err(429, "too many classify requests")
                resp.headers["Retry-After"] = "60"
                return resp
            if cfg.api_key is not None:
                given = request.headers.get("X-API-Key", "")
                if not hmac.compare_digest(given.encode(), cfg.api_key.encode()):
                    return _err(401, "missing or wrong API key")
        return None

    @app.after_request
    def _headers(resp: Response) -> Response:
        path = request.path
        csp = PAGE_CSP if path in ("/", "/index.html") else BRIEF_CSP if path == "/brief" else JSON_CSP
        resp.headers["Content-Security-Policy"] = csp
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        resp.headers["Cache-Control"] = "no-store" if path.startswith("/api") else "no-cache"
        resp.headers.pop("Server", None)
        if cfg.behind_https:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # log method, path, status, time, request id. Never the query values, body or feedback text (privacy).
        log.info("%s %s %s %.0fms id=%s", request.method, path, resp.status_code, (time.time() - g.get("t0", time.time())) * 1000,
                 g.get("request_id", "-"))
        return resp

    @app.errorhandler(400)
    def _e400(_e):  # noqa: ANN001, ANN202
        return _err(400, "bad request")

    @app.errorhandler(404)
    def _e404(_e):  # noqa: ANN001, ANN202
        return _err(404, "not found")

    @app.errorhandler(405)
    def _e405(_e):  # noqa: ANN001, ANN202
        return _err(405, "method not allowed")

    @app.errorhandler(413)
    def _e413(_e):  # noqa: ANN001, ANN202
        return _err(413, "request too large")

    @app.errorhandler(Exception)
    def _e500(exc):  # noqa: ANN001, ANN202
        log.error("unhandled %s id=%s", type(exc).__name__, g.get("request_id", "-"))   # type only, never the message
        return _err(500, "internal error")
