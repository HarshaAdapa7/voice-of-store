#!/usr/bin/env python3
"""Run the web demo:  python FULL_CODE/serve.py [--data data] [--submission submission] [--port 8000] [--host 127.0.0.1]

Binds to 127.0.0.1 by default. To expose it: pass --host 0.0.0.0, set R5_ALLOWED_HOSTS to your public host name(s), put it
behind a TLS-terminating reverse proxy (and set R5_HTTPS=1), and read SECURITY.md first. Uses waitress when installed.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from voice_of_store import config as C  # noqa: E402
from voice_of_store.io import DataError  # noqa: E402
from voice_of_store.logs import setup_logging  # noqa: E402
from voice_of_store.web.security import SecurityConfig  # noqa: E402
from voice_of_store.web.server import create_app  # noqa: E402
from voice_of_store.web.state import AppState  # noqa: E402

log = logging.getLogger("serve")


def check_exposure(host: str, cfg: SecurityConfig) -> None:
    """Refuse unsafe ways of exposing the app beyond this computer."""
    if host in C.LOOPBACK_HOSTS:
        return
    if len(cfg.allowed_hosts) <= len(C.LOOPBACK_HOSTS):
        raise SystemExit("exposing the app needs R5_ALLOWED_HOSTS=<your public host name> (host-header allow-list)")
    if cfg.auth_user and not cfg.behind_https:
        raise SystemExit("login over plain HTTP would send the password in clear: terminate TLS in front and set R5_HTTPS=1")
    if cfg.api_key is None and cfg.auth_user is None:
        log.warning("neither R5_AUTH_USER/R5_AUTH_HASH nor R5_API_KEY is set: the app is open to anyone who can reach this port")


def run_server(app, host: str, port: int) -> None:
    try:
        from waitress import serve
    except ImportError:
        if host not in C.LOOPBACK_HOSTS:
            raise SystemExit("refusing to expose the Flask development server: install waitress (pip install waitress)") from None
        from werkzeug.serving import WSGIRequestHandler

        class QuietHandler(WSGIRequestHandler):  # do not advertise Werkzeug and Python versions
            server_version = "r5"  # type: ignore[assignment]
            sys_version = ""

        log.warning("waitress not installed: using the Flask development server on localhost only")
        app.run(host=host, port=port, debug=False, threaded=True, request_handler=QuietHandler)
        return
    serve(
        app, host=host, port=port, threads=4, max_request_body_size=16 * 1024 * 1024, cleanup_interval=10, channel_timeout=30, ident=""
    )


def _load_env_file() -> None:
    """Read key-value pairs from .env or FULL_CODE/.env into os.environ if not already set."""
    candidates = (Path(".env"), Path("FULL_CODE/.env"), Path(__file__).resolve().parent / ".env")
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                k_clean = k.strip()
                v_clean = v.strip().strip("'\"")
                if k_clean and k_clean not in os.environ:
                    os.environ[k_clean] = v_clean


def main() -> None:
    _load_env_file()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data")
    ap.add_argument("--submission", default="submission")
    ap.add_argument("--host", default=C.WEB_HOST)
    ap.add_argument("--port", type=int, default=C.WEB_PORT)
    ap.add_argument("--gemini-api-key", default=None, help="Google Gemini API key for assistant summaries")
    a = ap.parse_args()
    if a.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = a.gemini_api_key
    setup_logging()
    try:
        cfg = SecurityConfig.from_env()
        check_exposure(a.host, cfg)
        log.info("loading data and training the classifier (about 20 seconds)")
        state = AppState(Path(a.data), Path(a.submission))
    except (DataError, ValueError, FileNotFoundError) as exc:
        raise SystemExit(f"error: {exc}") from None
    threading.Thread(target=state.warm, name="warm-briefs", daemon=True).start()
    log.info("serving on http://%s:%d", a.host, a.port)
    run_server(create_app(state, cfg), a.host, a.port)


if __name__ == "__main__":
    main()
