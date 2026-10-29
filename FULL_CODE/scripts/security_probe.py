"""Attack battery against a RUNNING instance of the demo (default http://127.0.0.1:8000).

Usage: python FULL_CODE/scripts/security_probe.py [base_url]
Sends hostile requests and checks that each is refused or neutralised. Exit code 1 if any check fails.
Only use it against your own instance.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
PAYLOADS = ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "' OR 1=1 --", "{{7*7}}", "../../etc/passwd", "\x00"]


def call(method: str, path: str, body: object = None, headers: dict | None = None, raw: bytes | None = None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)  # noqa: S310 (own URL)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


def main() -> int:
    results: list[tuple[str, bool]] = []

    def check(name: str, ok: bool) -> None:
        results.append((name, ok))

    s, h, _ = call("GET", "/")
    check("page has CSP without unsafe-inline", "'unsafe-inline'" not in h.get("Content-Security-Policy", "") and s == 200)
    check("security headers present", all(k in h for k in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy")))
    check("no server version header", "Server" not in h or "Werkzeug" not in h.get("Server", ""))
    check("trusted types enforced", "require-trusted-types-for" in h.get("Content-Security-Policy", ""))
    check("cross-origin isolation headers", h.get("Cross-Origin-Embedder-Policy") == "require-corp" and "X-Request-ID" in h)
    check("over-long URL refused", call("GET", "/api/health?a=" + "b" * 700)[0] == 414)
    check("unknown query parameter refused", call("GET", "/api/meta?debug=1")[0] == 400)
    check("export week is allow-listed", call("GET", "/api/export?week=x%0d%0aSet-Cookie:a=1")[0] == 400)
    s, h, b = call("GET", "/report")
    check(
        "report page has no script and a locked-down CSP",
        s == 200 and "<script" not in b.lower() and "script-src" not in h.get("Content-Security-Policy", ""),
    )
    check("report refuses query parameters", call("GET", "/report?debug=1")[0] == 400)
    check("bad Host refused", call("GET", "/api/health", headers={"Host": "evil.example"})[0] == 400)
    check(
        "cross-origin POST refused",
        call("POST", "/api/assistant", {"message": "hi"}, {"Origin": "https://evil.example"})[0] == 403,
    )
    check(
        "text/plain POST refused",
        call("POST", "/api/assistant", headers={"Content-Type": "text/plain"}, raw=b"message=hi")[0] == 415,
    )
    check("oversize body refused", call("POST", "/api/assistant", raw=b'{"message":"' + b"a" * 20000 + b'"}')[0] in (400, 413))
    check("PUT/DELETE refused", all(call(m, "/api/meta")[0] == 405 for m in ("PUT", "DELETE", "PATCH")))
    check("path traversal not served", call("GET", "/../../etc/passwd")[0] in (400, 404))
    check("unknown static file 404", call("GET", "/server.py")[0] == 404)
    for p in PAYLOADS:
        s, _, b = call("POST", "/api/assistant", {"message": p})
        check(f"assistant neutralises {p[:18]!r}", s in (200, 400) and "<script" not in b and "<img" not in b)
        s, _, b = call("GET", "/api/brief?region=" + urllib.request.quote(p) + "&week=2026-09-07")
        check(f"brief rejects {p[:18]!r}", s == 400 and p not in b)
    s, _, b = call("POST", "/api/assistant", {"message": "hi", "role": "admin"})
    check("unknown JSON field refused", s == 400)
    s, _, b = call("POST", "/api/assistant", raw=b"{not json")
    check("malformed JSON gives generic 400", s == 400 and "Traceback" not in b)
    statuses = [call("POST", "/api/assistant", {"message": "hello"})[0] for _ in range(60)]
    check("assistant rate limit engages", 429 in statuses)

    bad = [n for n, ok in results if not ok]
    for n, ok in results:
        print(("PASS  " if ok else "FAIL  ") + n)  # noqa: T201
    print(f"\n{len(results) - len(bad)}/{len(results)} checks passed")  # noqa: T201
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
