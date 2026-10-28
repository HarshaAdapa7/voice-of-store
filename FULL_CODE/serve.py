#!/usr/bin/env python3
"""Run the web demo:  python FULL_CODE/serve.py [--data data] [--submission submission] [--port 8000] [--host 127.0.0.1]

Binds to 127.0.0.1 by default. To expose it, pass --host 0.0.0.0, set R5_ALLOWED_HOSTS to your public host name(s), put it behind
a TLS-terminating reverse proxy, and read the "Security" section of the README first. Uses waitress when installed.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from voice_of_store.web.security import SecurityConfig  # noqa: E402
from voice_of_store.web.server import create_app  # noqa: E402
from voice_of_store.web.state import AppState  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--submission", default="submission")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print("loading data and training the classifier (about 20 seconds)...", flush=True)
    state = AppState(Path(a.data), Path(a.submission))
    cfg = SecurityConfig.from_env()
    app = create_app(state, cfg)
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        if len(cfg.allowed_hosts) <= 3:
            raise SystemExit("exposing the app needs R5_ALLOWED_HOSTS=<your public host name> (host-header allow-list)")
        if cfg.api_key is None:
            logging.warning("R5_API_KEY is not set: /api/classify is open to anyone who can reach this port")
    print(f"serving on http://{a.host}:{a.port}", flush=True)
    try:
        from waitress import serve
        serve(app, host=a.host, port=a.port, threads=4, max_request_body_size=16 * 1024, cleanup_interval=10,
              channel_timeout=30, ident="")
    except ImportError:
        if a.host not in ("127.0.0.1", "localhost", "::1"):
            raise SystemExit("refusing to expose the Flask development server: install waitress (pip install waitress)") from None
        print("waitress not installed: using the Flask development server on localhost only", flush=True)
        from werkzeug.serving import WSGIRequestHandler

        class QuietHandler(WSGIRequestHandler):        # do not advertise Werkzeug and Python versions
            server_version = "r5"  # type: ignore[assignment]
            sys_version = ""

        app.run(host=a.host, port=a.port, debug=False, threaded=True, request_handler=QuietHandler)


if __name__ == "__main__":
    main()
