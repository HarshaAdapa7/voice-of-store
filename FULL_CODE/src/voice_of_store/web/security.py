"""Security layer for the web app: headers, host allow-list, origin check, body limits, rate limiting, optional API key.

Threat model (stated plainly): the app serves read-only analytics over synthetic data and one stateless classify endpoint.
It has no accounts, cookies, database or file upload. The main risks are therefore XSS through feedback text, DNS rebinding
and cross-site requests against a localhost server, resource exhaustion, information leaks through errors or logs, and
supply-chain issues. Each has a control below; none of them replaces running behind a TLS-terminating reverse proxy when the
app is exposed beyond localhost.
"""

from __future__ import annotations

import base64
import binascii
import gzip
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
from werkzeug.security import check_password_hash

log = logging.getLogger("voice_of_store.web")

JSON_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
PAGE_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'; "
    "require-trusted-types-for 'script'; trusted-types 'none'"
)
BRIEF_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'; object-src 'none'"
)  # the printable brief is static HTML with inline CSS, no script


@dataclass
class SecurityConfig:
    """Every web security setting in one place; defaults are the strict ones."""

    allowed_hosts: frozenset = frozenset({"127.0.0.1", "localhost", "[::1]"})
    max_body_bytes: int = 8 * 1024
    max_text_chars: int = 2000
    max_url_chars: int = 512  # path plus query string; every legitimate request is far shorter
    rate_per_minute: int = 120  # all endpoints, per client address
    classify_per_minute: int = 20  # the one POST endpoint
    assistant_per_minute: int = 40  # POST /api/assistant
    max_tracked_clients: int = 5000
    api_key: str | None = None  # when set, /api/classify requires header X-API-Key
    auth_user: str | None = None  # when set together with auth_hash, every page and API route needs HTTP Basic auth
    auth_hash: str | None = None  # werkzeug password hash (scripts/make_auth_hash.py); the password is never stored
    auth_fail_per_minute: int = 10  # failed logins per client per minute before 429
    behind_https: bool = False  # adds HSTS (only set when TLS is terminated in front of the app)
    trust_proxy: bool = False  # read the client address from X-Forwarded-For (only behind a trusted proxy)
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> SecurityConfig:
        """Read the R5_* environment variables; refuses a half-configured login."""
        hosts = {h.strip().lower() for h in os.environ.get("R5_ALLOWED_HOSTS", "").split(",") if h.strip()}
        cfg = cls()
        if hosts:
            cfg.allowed_hosts = frozenset(hosts | {"127.0.0.1", "localhost", "[::1]"})
        cfg.api_key = os.environ.get("R5_API_KEY") or None
        cfg.auth_user = os.environ.get("R5_AUTH_USER") or None
        cfg.auth_hash = os.environ.get("R5_AUTH_HASH") or None
        if bool(cfg.auth_user) != bool(cfg.auth_hash):
            raise ValueError("set both R5_AUTH_USER and R5_AUTH_HASH, or neither")
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
        """True while the client is within its per-minute limit for the bucket."""
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
    if v.startswith("["):  # [::1]:8000
        return v.split("]")[0] + "]"
    return v.split(":")[0]


def _loggable(value: str, limit: int = 120) -> str:
    """A request path made safe for a log line: no control characters (log forging), bounded length."""
    cleaned = "".join(c if c.isprintable() and c not in "\r\n" else "?" for c in value)
    return cleaned[:limit] + ("..." if len(cleaned) > limit else "")


def _err(status: int, message: str) -> Response:
    resp = jsonify(error=message, request_id=getattr(g, "request_id", "-"))
    resp.status_code = status
    return resp


# A throw-away hash so a wrong user name costs the same time as a wrong password (no user-name oracle).
_DUMMY_HASH = "scrypt:32768:8:1$r5dummysalt0000$" + "0" * 128


def _credentials() -> tuple[str, str] | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return None
    try:
        user, _, password = base64.b64decode(header[6:], validate=True).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    return user, password


def _authorised(cfg: SecurityConfig) -> bool:
    creds = _credentials()
    if creds is None or cfg.auth_user is None or cfg.auth_hash is None:
        return False
    user, password = creds
    user_ok = hmac.compare_digest(user.encode(), cfg.auth_user.encode())
    try:
        pass_ok = check_password_hash(cfg.auth_hash if user_ok else _DUMMY_HASH, password)
    except ValueError:
        pass_ok = False
    return user_ok and pass_ok


def _login_required(limiter: RateLimiter, cfg: SecurityConfig, client: str) -> Response | None:
    """HTTP Basic auth for everything except /api/health. Failed attempts are rate-limited per client."""
    if cfg.auth_user is None or request.path == "/api/health":
        return None
    if _authorised(cfg):
        return None
    if not limiter.allow(client, "authfail", cfg.auth_fail_per_minute):
        resp = _err(429, "too many failed logins")
        resp.headers["Retry-After"] = "60"
        return resp
    resp = _err(401, "authentication required")
    resp.headers["WWW-Authenticate"] = 'Basic realm="Voice-of-Store", charset="UTF-8"'
    return resp


def _post_checks(cfg: SecurityConfig, limiter: RateLimiter, client: str) -> Response | None:
    origin = request.headers.get("Origin")
    if origin and _host_only(urlsplit(origin).netloc) not in cfg.allowed_hosts:  # cross-site request
        return _err(403, "cross-origin request refused")
    if request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
        return _err(403, "cross-site request refused")
    if request.mimetype != "application/json":
        return _err(415, "content type must be application/json")
    bucket, limit = (
        ("assistant", cfg.assistant_per_minute) if request.path == "/api/assistant" else ("classify", cfg.classify_per_minute)
    )
    if not limiter.allow(client, bucket, limit):
        resp = _err(429, "too many classify requests")
        resp.headers["Retry-After"] = "60"
        return resp
    if cfg.api_key is not None:
        given = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(given.encode(), cfg.api_key.encode()):
            return _err(401, "missing or wrong API key")
    return None


def _guard(cfg: SecurityConfig, limiter: RateLimiter) -> Response | None:
    g.request_id = uuid.uuid4().hex[:12]
    g.t0 = time.time()
    if _host_only(request.headers.get("Host", "")) not in cfg.allowed_hosts:  # DNS-rebinding and host-header attacks
        return _err(400, "host not allowed")
    if len(request.full_path) > cfg.max_url_chars:
        return _err(414, "request target too long")
    client = _client_ip(cfg)
    if not limiter.allow(client, "all", cfg.rate_per_minute):
        resp = _err(429, "too many requests")
        resp.headers["Retry-After"] = "60"
        return resp
    if request.method not in ("GET", "HEAD", "POST"):
        return _err(405, "method not allowed")
    denied = _login_required(limiter, cfg, client)
    if denied is not None:
        return denied
    return _post_checks(cfg, limiter, client) if request.method == "POST" else None


_COMPRESSIBLE = ("application/json", "text/html", "text/css", "text/javascript", "text/csv")


def _compress(resp: Response) -> None:
    """gzip text responses over 1 KiB. Nothing secret or user-specific is ever in a body, so BREACH does not apply."""
    if (
        resp.status_code != 200
        or resp.mimetype not in _COMPRESSIBLE
        or "gzip" not in request.headers.get("Accept-Encoding", "")
        or resp.headers.get("Content-Encoding")
    ):
        return
    resp.direct_passthrough = False
    body = resp.get_data()
    resp.headers.add("Vary", "Accept-Encoding")
    if len(body) < 1024:
        return
    resp.set_data(gzip.compress(body, compresslevel=6, mtime=0))
    resp.headers["Content-Encoding"] = "gzip"
    if resp.headers.get("ETag") and not resp.headers["ETag"].startswith("W/"):
        resp.headers["ETag"] = "W/" + resp.headers["ETag"]


def _add_headers(cfg: SecurityConfig, resp: Response) -> Response:
    path = request.path
    _compress(resp)
    csp = PAGE_CSP if path in ("/", "/index.html") else BRIEF_CSP if path in ("/brief", "/report") else JSON_CSP
    resp.headers["Content-Security-Policy"] = csp
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    resp.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    resp.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    resp.headers["X-Request-ID"] = g.get("request_id", "-")
    resp.headers["Cache-Control"] = "no-store" if path.startswith("/api") or cfg.auth_user else "no-cache"
    resp.headers.pop("Server", None)
    if cfg.behind_https:
        resp.headers["Content-Security-Policy"] += "; upgrade-insecure-requests"
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # log method, path, status, time, request id. Never the query values, body or feedback text (privacy).
    log.info(
        "%s %s %s %.0fms id=%s",
        request.method,
        _loggable(path),
        resp.status_code,
        (time.time() - g.get("t0", time.time())) * 1000,
        g.get("request_id", "-"),
    )
    return resp


def _register_errors(app: Flask) -> None:
    messages = {
        400: "bad request",
        401: "unauthorized",
        403: "forbidden",
        404: "not found",
        405: "method not allowed",
        413: "request too large",
        414: "request target too long",
        429: "too many requests",
    }
    for code, text in messages.items():
        app.register_error_handler(code, lambda _e, c=code, t=text: _err(c, t))

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception) -> Response:
        log.error(
            "unhandled %s id=%s", type(exc).__name__, g.get("request_id", "-"), exc_info=log.isEnabledFor(logging.DEBUG)
        )  # type only, never the message
        return _err(500, "internal error")


def install(app: Flask, cfg: SecurityConfig) -> None:
    """Attach every control to the app: guard before each request, headers after, generic error pages."""
    limiter = RateLimiter(cfg.max_tracked_clients)
    app.config["MAX_CONTENT_LENGTH"] = cfg.max_body_bytes
    app.before_request(lambda: _guard(cfg, limiter))
    app.after_request(lambda resp: _add_headers(cfg, resp))
    _register_errors(app)
