"""Security and API tests for the web app. The security tests use a stub state, so they need neither data nor a model."""
from __future__ import annotations

import logging

import pytest

pytest.importorskip("flask")

from voice_of_store.web.security import RateLimiter, SecurityConfig  # noqa: E402
from voice_of_store.web.server import create_app  # noqa: E402

WEEK, REGION = "2026-08-03", "South"
XSS = "<script>alert(1)</script>"


class StubState:
    regions = [REGION]
    weeks = [WEEK]

    def meta(self):
        return dict(regions=self.regions, weeks=self.weeks, test_weeks=self.weeks, channels=["in_app", "staff_shift_note"],
                    issue_types=[dict(id="IT10", name="Refrigeration", owner="Store Ops", floor="high")],
                    stores=[dict(id="ST-ABCDE", name="Saffron Market Test", region=REGION)])

    def brief(self, region, week):
        return [dict(issue="Refrigeration", owner="Store Ops", severity="high", tier="UNVERIFIED", window="same day", count=1,
                     channels=1, n_stores=1, stores=[("Saffron Market Test", 1)], trend="→", prev_count=0, emerging=[],
                     quotes=[("in_app", XSS)], dedup=dict(reports=1, incidents=1, cross_channel=0))]

    def week_rows(self, region, week):
        return 1

    def flags_for(self, week):
        return []

    def series(self, store_id, issue_type):
        return dict(weeks=self.weeks, store_counts=[0], chain_counts=[0], flagged_weeks=[])

    def validation(self):
        return dict(n_pred_actionable=1)

    def classify(self, text, channel):
        if text == "boom":
            raise RuntimeError("secret internal detail /etc/passwd")
        return dict(issue_type="IT10")


def make(**kw):
    cfg = SecurityConfig(**kw)
    app = create_app(StubState(), cfg)
    app.testing = False  # exercise the real error handlers
    return app.test_client()


@pytest.fixture()
def client():
    return make()


JSON = {"Content-Type": "application/json"}


def test_security_headers_everywhere(client):
    for path in ("/", "/app.js", "/style.css", "/api/health", "/api/meta", "/nope", f"/brief?region={REGION}&week={WEEK}"):
        r = client.get(path)
        assert r.headers["X-Content-Type-Options"] == "nosniff", path
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
        assert "Strict-Transport-Security" not in r.headers  # only behind HTTPS
    assert "script-src 'self'" in client.get("/").headers["Content-Security-Policy"]
    assert "unsafe-inline" not in client.get("/").headers["Content-Security-Policy"].replace("style-src 'unsafe-inline'", "")
    assert "script" not in client.get(f"/brief?region={REGION}&week={WEEK}").headers["Content-Security-Policy"]
    assert client.get("/api/meta").headers["Cache-Control"] == "no-store"


def test_hsts_only_when_declared_https():
    assert "Strict-Transport-Security" in make(behind_https=True).get("/api/health").headers


def test_host_header_attack_refused(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/health", headers={"Host": "localhost.evil.example"}).status_code == 400
    assert client.get("/api/health", headers={"Host": "localhost:8000"}).status_code == 200


def test_cross_site_post_refused(client):
    body = dict(text="hello", channel="in_app")
    assert client.post("/api/classify", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/classify", json=body, headers={"Origin": "null"}).status_code == 403
    assert client.post("/api/classify", json=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/classify", json=body, headers={"Origin": "http://localhost:8000"}).status_code == 200


def test_content_type_and_method_rules(client):
    assert client.post("/api/classify", data="text=hi", headers={"Content-Type": "text/plain"}).status_code == 415
    for m in ("put", "delete", "patch", "options"):
        assert getattr(client, m)("/api/meta").status_code == 405
    assert client.post("/api/meta", json={}).status_code == 405


@pytest.mark.parametrize("body", [
    {}, {"text": ""}, {"text": "   "}, {"text": 5}, {"text": "x", "channel": "fax"}, {"text": "x", "extra": 1},
    {"text": "x" * 2001}, [], "just a string",
])
def test_classify_rejects_bad_input(client, body):
    assert client.post("/api/classify", json=body).status_code == 400


def test_invalid_json_and_oversize_body(client):
    assert client.post("/api/classify", data="null", headers=JSON).status_code == 400
    assert client.post("/api/classify").status_code == 415
    assert client.post("/api/classify", data="{not json", headers=JSON).status_code == 400
    assert client.post("/api/classify", data=b'{"text":"' + b"a" * 20000 + b'"}', headers=JSON).status_code == 413


def test_query_parameters_use_allow_lists(client):
    bad = ["", "2026-08-03' OR '1'='1", "../../etc/passwd", "2026-8-3", "x" * 5000, "<script>", "2026-08-10"]
    for w in bad:
        assert client.get("/api/brief", query_string={"region": REGION, "week": w}).status_code == 400, w
        assert client.get("/api/flags", query_string={"week": w}).status_code == 400
    assert client.get("/api/brief", query_string={"region": "Mars", "week": WEEK}).status_code == 400
    assert client.get("/api/series", query_string={"store_id": "ST-ABCDE", "issue_type": "IT99"}).status_code == 400
    assert client.get("/api/series", query_string={"store_id": "ST-ABCDE", "issue_type": "IT10"}).status_code == 200


def test_only_allow_listed_static_files(client):
    for p in ("/../etc/passwd", "/..%2f..%2fetc/passwd", "/static/../server.py", "/server.py", "/state.py", "/%2e%2e/security.py",
              "/app.js/../security.py", "/index.html/", "/.git/config", "/.env"):
        assert client.get(p).status_code == 404, p
    assert client.get("/app.js").status_code == 200 and client.get("/style.css").status_code == 200


def test_user_content_is_escaped_in_printable_brief(client):
    html = client.get(f"/brief?region={REGION}&week={WEEK}").get_data(as_text=True)
    assert XSS not in html and "&lt;script&gt;" in html
    r = client.get(f"/api/brief?region={REGION}&week={WEEK}")
    assert r.mimetype == "application/json" and r.headers["X-Content-Type-Options"] == "nosniff"


def test_frontend_never_uses_html_injection():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "src/voice_of_store/web/static/app.js").read_text()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setTimeout(\""):
        assert bad not in js, bad
    html = (Path(__file__).resolve().parents[1] / "src/voice_of_store/web/static/index.html").read_text()
    assert "<script>" not in html and " onclick" not in html and "style=" not in html


def test_errors_do_not_leak_internals(client):
    r = client.post("/api/classify", json=dict(text="boom", channel="in_app"))
    assert r.status_code == 500
    body = r.get_data(as_text=True)
    assert "passwd" not in body and "RuntimeError" not in body and "Traceback" not in body and "request_id" in body


def test_logs_contain_no_user_text(client, caplog):
    secret = "my phone is 9876543210 and email a@b.com"
    with caplog.at_level(logging.INFO, logger="voice_of_store.web"):
        client.post("/api/classify", json=dict(text=secret, channel="in_app"))
        client.post("/api/classify", json=dict(text="boom", channel="in_app"))
        client.get("/api/brief", query_string={"region": "private-name", "week": WEEK})
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "9876543210" not in logged and "a@b.com" not in logged and "private-name" not in logged and "internal detail" not in logged


def test_rate_limits():
    c = make(rate_per_minute=5, classify_per_minute=3)
    codes = [c.get("/api/health").status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]
    assert c.get("/api/health").headers["Retry-After"] == "60"
    c2 = make(rate_per_minute=100, classify_per_minute=3)
    codes = [c2.post("/api/classify", json=dict(text="hello", channel="in_app")).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_rate_limiter_memory_is_bounded():
    rl = RateLimiter(max_clients=50)
    for i in range(1000):
        rl.allow(f"10.0.{i // 250}.{i % 250}", "all", 10, now=0.0)
    assert len(rl._hits) <= 50


def test_api_key_when_configured():
    c = make(api_key="s3cret-key-value")
    body = dict(text="hello", channel="in_app")
    assert c.post("/api/classify", json=body).status_code == 401
    assert c.post("/api/classify", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post("/api/classify", json=body, headers={"X-API-Key": "s3cret-key-value"}).status_code == 200
    assert c.get("/api/meta").status_code == 200     # read-only analytics stay open on the private network


def test_forwarded_header_ignored_unless_proxy_trusted():
    c = make(rate_per_minute=2)
    for i in range(3):  # a client cannot dodge the limit by spoofing X-Forwarded-For
        last = c.get("/api/health", headers={"X-Forwarded-For": f"1.2.3.{i}"}).status_code
    assert last == 429


def test_no_cookies_set(client):
    assert "Set-Cookie" not in client.get("/").headers
    assert "Set-Cookie" not in client.post("/api/classify", json=dict(text="hi", channel="in_app")).headers


# ---------------- with the real state (needs data/) ----------------
@pytest.fixture(scope="module")
def real(data_dir_module):
    from voice_of_store.web.state import AppState
    sub = data_dir_module.parent / "submission"
    if not (sub / "R5_emerging_flags.csv").exists():
        pytest.skip("submission files not present")
    state = AppState(data_dir_module, sub)
    return state, create_app(state, SecurityConfig()).test_client()


@pytest.fixture(scope="module")
def data_dir_module():
    from conftest import DATA
    if not (DATA / "feedback.csv").exists():
        pytest.skip("pack data not present in data/")
    return DATA


def test_real_classify_and_brief(real):
    state, c = real
    r = c.post("/api/classify", json=dict(text="frzr 3 not cooling since morning at Kothrud, ice cream melting", channel="staff_shift_note"))
    j = r.get_json()
    assert r.status_code == 200 and j["issue_type"] == "IT10" and j["severity"] in ("high", "critical")
    assert j["store_named"] and j["owner"] == "Store Ops" and j["key_terms"]
    week = state.test_weeks[-1]
    b = c.get("/api/brief", query_string={"region": state.regions[0], "week": week}).get_json()
    assert 1 <= len(b["entries"]) <= 5
    for e in b["entries"]:
        assert e["severity"] in ("low", "medium", "high", "critical") and e["dedup"]["incidents"] >= 1
    assert c.get("/api/validation").get_json()["n_pred_actionable"] > 0


def test_real_flags_match_submission_and_series(real):
    state, c = real
    total = 0
    for w in state.test_weeks:
        fl = c.get("/api/flags", query_string={"week": w}).get_json()["flags"]
        total += len(fl)
        for f in fl:
            assert len(f["evidence"]) >= 2
            s = c.get("/api/series", query_string={"store_id": f["store_id"], "issue_type": f["issue_type"]}).get_json()
            assert w in s["flagged_weeks"] and len(s["weeks"]) == len(s["store_counts"])
    assert total == int((state.flags["as_of_week_start"] >= state.test_weeks[0]).sum())
