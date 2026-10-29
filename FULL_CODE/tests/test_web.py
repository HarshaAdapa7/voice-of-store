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
        return dict(
            regions=self.regions,
            weeks=self.weeks,
            test_weeks=self.weeks,
            channels=["in_app", "staff_shift_note"],
            issue_types=[dict(id="IT10", name="Refrigeration", owner="Store Ops", floor="high")],
            stores=[dict(id="ST-ABCDE", name="Saffron Market Test", region=REGION)],
        )

    def brief(self, region, week):
        return [
            dict(
                issue="Refrigeration",
                owner="Store Ops",
                severity="high",
                tier="UNVERIFIED",
                window="same day",
                count=1,
                channels=1,
                n_stores=1,
                stores=[("Saffron Market Test", 1)],
                trend="→",
                prev_count=0,
                emerging=[],
                beyond_top5=False,
                quotes=[("in_app", XSS, "Mon 03 Aug 09:00")],
                status="Unverified serious allegation: a single source, not confirmed.",
                next_step="Store manager reads the temperature log today.",
                safety=True,
                confidence=0.9,
                first_seen="Mon 03 Aug 09:00",
                last_seen="Mon 03 Aug 09:00",
                by_channel=[("in_app", 1)],
                rates={"Saffron Market Test": 1.0},
                dedup=dict(reports=1, incidents=1, cross_channel=0),
            )
        ]

    def week_rows(self, region, week):
        return 1

    def flags_for(self, week):
        return []

    def series(self, store_id, issue_type):
        return dict(weeks=self.weeks, store_counts=[0], chain_counts=[0], flagged_weeks=[])

    def validation(self):
        return dict(n_pred_actionable=1)

    def store_overview(self, store_id, week):
        return dict(store_id=store_id, week=week, name="Saffron Market Test", region=REGION, top=[], weeks=self.weeks)

    def store_ids_in_text(self, text):
        return []

    def issue_catalogue(self):
        return []

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


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"text": ""},
        {"text": "   "},
        {"text": 5},
        {"text": "x", "channel": "fax"},
        {"text": "x", "extra": 1},
        {"text": "x" * 2001},
        [],
        "just a string",
    ],
)
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
        assert client.get("/api/brief", query_string={"region": REGION, "week": w}).status_code in (400, 414), w
        assert client.get("/api/flags", query_string={"week": w}).status_code in (400, 414)
    assert client.get("/api/brief", query_string={"region": "Mars", "week": WEEK}).status_code == 400
    assert client.get("/api/series", query_string={"store_id": "ST-ABCDE", "issue_type": "IT99"}).status_code == 400
    assert client.get("/api/series", query_string={"store_id": "ST-ABCDE", "issue_type": "IT10"}).status_code == 200


def test_only_allow_listed_static_files(client):
    for p in (
        "/../etc/passwd",
        "/..%2f..%2fetc/passwd",
        "/static/../server.py",
        "/server.py",
        "/state.py",
        "/%2e%2e/security.py",
        "/app.js/../security.py",
        "/index.html/",
        "/.git/config",
        "/.env",
    ):
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
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", 'setTimeout("'):
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
    assert (
        "9876543210" not in logged
        and "a@b.com" not in logged
        and "private-name" not in logged
        and "internal detail" not in logged
    )


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
    assert c.get("/api/meta").status_code == 200  # read-only analytics stay open on the private network


def test_forwarded_header_ignored_unless_proxy_trusted():
    c = make(rate_per_minute=2)
    for i in range(3):  # a client cannot dodge the limit by spoofing X-Forwarded-For
        last = c.get("/api/health", headers={"X-Forwarded-For": f"1.2.3.{i}"}).status_code
    assert last == 429


def test_no_cookies_set(client):
    assert "Set-Cookie" not in client.get("/").headers
    assert "Set-Cookie" not in client.post("/api/classify", json=dict(text="hi", channel="in_app")).headers


def _auth_client(**kw):
    from werkzeug.security import generate_password_hash

    h = generate_password_hash("correct horse battery", method="scrypt:4096:8:1")  # cheap cost: this is a test
    return make(auth_user="judge", auth_hash=h, **kw)


def _basic(user, password):
    import base64

    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def test_login_protects_every_page_and_api():
    c = _auth_client()
    for path in ("/", "/app.js", "/style.css", "/api/meta", "/api/validation", f"/brief?region={REGION}&week={WEEK}"):
        r = c.get(path)
        assert r.status_code == 401 and r.headers["WWW-Authenticate"].startswith("Basic"), path
    assert c.post("/api/classify", json=dict(text="hi", channel="in_app")).status_code == 401
    assert c.get("/api/health").status_code == 200  # health check only, no data
    good = _basic("judge", "correct horse battery")
    assert c.get("/api/meta", headers=good).status_code == 200
    assert c.post("/api/classify", json=dict(text="hi", channel="in_app"), headers=good).status_code == 200
    assert c.get("/api/meta", headers=good).headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "hdr",
    [
        {},
        {"Authorization": "Bearer abc"},
        {"Authorization": "Basic !!!notbase64"},
        {"Authorization": "Basic " + "QQ=="},
        {"Authorization": "Basic"},
    ],
)
def test_login_rejects_malformed_credentials(hdr):
    assert _auth_client().get("/api/meta", headers=hdr).status_code == 401


def test_login_rejects_wrong_user_or_password():
    c = _auth_client()
    assert c.get("/api/meta", headers=_basic("judge", "wrong password!!")).status_code == 401
    assert c.get("/api/meta", headers=_basic("admin", "correct horse battery")).status_code == 401
    assert c.get("/api/meta", headers=_basic("judge", "")).status_code == 401


def test_failed_logins_are_rate_limited():
    c = _auth_client(auth_fail_per_minute=3)
    codes = [c.get("/api/meta", headers=_basic("judge", "bad")).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]
    # the limiter also stops a correct password being tried after many failures from the same client only for failures;
    # a correct login still works
    assert c.get("/api/meta", headers=_basic("judge", "correct horse battery")).status_code == 200


def test_auth_env_needs_both_values(monkeypatch):
    monkeypatch.setenv("R5_AUTH_USER", "judge")
    monkeypatch.delenv("R5_AUTH_HASH", raising=False)
    with pytest.raises(ValueError):
        SecurityConfig.from_env()


def test_exposure_rules(monkeypatch):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("serve", Path(__file__).resolve().parents[1] / "serve.py")
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)
    serve.check_exposure("127.0.0.1", SecurityConfig())  # loopback is always fine
    with pytest.raises(SystemExit):
        serve.check_exposure("0.0.0.0", SecurityConfig())  # needs a host allow-list  # noqa: S104
    public = SecurityConfig(allowed_hosts=frozenset({"127.0.0.1", "localhost", "[::1]", "demo.example.com"}))
    serve.check_exposure("0.0.0.0", public)  # noqa: S104
    with pytest.raises(SystemExit):  # login over plain HTTP is refused
        serve.check_exposure("0.0.0.0", SecurityConfig(allowed_hosts=public.allowed_hosts, auth_user="u", auth_hash="h"))  # noqa: S104
    https_login = SecurityConfig(allowed_hosts=public.allowed_hosts, auth_user="u", auth_hash="h", behind_https=True)
    serve.check_exposure("0.0.0.0", https_login)  # noqa: S104


def test_assistant_endpoint_validates_input(client):
    ok = client.post("/api/assistant", json={"message": "hello"})
    assert ok.status_code == 200 and ok.get_json()["intent"] == "help"
    for body in [
        {},
        {"message": ""},
        {"message": "  "},
        {"message": 5},
        {"message": "x" * 301},
        {"message": "hi", "extra": 1},
        [],
        "text",
    ]:
        assert client.post("/api/assistant", json=body).status_code == 400, body
    assert client.post("/api/assistant", data="message=hi", headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post("/api/assistant", json={"message": "hi"}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_assistant_has_its_own_rate_limit():
    c = make(assistant_per_minute=3, classify_per_minute=100, rate_per_minute=100)
    codes = [c.post("/api/assistant", json={"message": "hello"}).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert c.post("/api/classify", json=dict(text="hello", channel="in_app")).status_code == 200  # buckets are separate


def test_assistant_and_store_need_login_when_configured():
    c = _auth_client()
    assert c.post("/api/assistant", json={"message": "hello"}).status_code == 401
    assert c.get("/api/store", query_string={"store_id": "ST-ABCDE", "week": WEEK}).status_code == 401
    good = _basic("judge", "correct horse battery")
    assert c.post("/api/assistant", json={"message": "hello"}, headers=good).status_code == 200


def test_store_endpoint_uses_allow_lists(client):
    assert client.get("/api/store", query_string={"store_id": "ST-ABCDE", "week": WEEK}).status_code == 200
    for sid in ["", "ST-ZZZZZ", "../x", "ST-ABCDE' OR 1=1", "x" * 500]:
        assert client.get("/api/store", query_string={"store_id": sid, "week": WEEK}).status_code in (400, 414), sid
    assert client.get("/api/store", query_string={"store_id": "ST-ABCDE", "week": "2030-01-07"}).status_code == 400


def test_logs_never_contain_assistant_questions(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="voice_of_store.web"):
        client.post("/api/assistant", json={"message": "how is secret-store-name doing, my phone is 9876543210"})
    assert "9876543210" not in " ".join(r.getMessage() for r in caplog.records)


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
    r = c.post(
        "/api/classify",
        json=dict(text="frzr 3 not cooling since morning at Kothrud, ice cream melting", channel="staff_shift_note"),
    )
    j = r.get_json()
    assert r.status_code == 200 and j["issue_type"] == "IT10" and j["severity"] in ("high", "critical")
    assert j["store_named"] and j["owner"] == "Store Ops" and j["key_terms"]
    week = state.test_weeks[-1]
    b = c.get("/api/brief", query_string={"region": state.regions[0], "week": week}).get_json()
    assert 1 <= len([e for e in b["entries"] if not e["beyond_top5"]]) <= 5
    assert all(e["safety"] for e in b["entries"] if e["beyond_top5"])
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


def test_real_store_page_and_assistant(real):
    state, c = real
    store = state.flags["store_id"].iloc[0]
    o = c.get("/api/store", query_string={"store_id": store, "week": state.weeks[-1]}).get_json()
    assert o["store_id"] == store and len(o["weekly_reports"]) == len(o["weeks"]) and o["reports_this_week"] >= 0
    name = state.store_name[store].split(" ", 2)[2]
    r = c.post("/api/assistant", json={"message": f"How is {name} doing?"}).get_json()
    assert r["intent"] == "store" and state.store_name[store] in r["reply"]
    r = c.post("/api/assistant", json={"message": "Any emerging issues this week?"}).get_json()
    assert r["intent"] == "emerging" and r["week"] == state.weeks[-1]
    r = c.post("/api/assistant", json={"message": "classify: frzr 3 not cooling since morning, ice cream melting"}).get_json()
    assert r["intent"] == "classify" and "IT10" in r["reply"]


def test_warm_up_fills_the_brief_cache(real):
    state, _ = real
    state.warm()
    assert len(state._brief_cache) == len(state.regions) * len(state.test_weeks)


# ---------------- hardening round 2 ----------------
class FlagStub(StubState):
    def flags_for(self, week):
        return [
            dict(
                store_id="ST-ABCDE",
                store='=HYPERLINK("http://x")',
                region=REGION,
                issue_type="IT10",
                issue="Refrigeration",
                owner="Store Ops",
                confidence=0.7,
                evidence=[dict(channel="in_app", text="a"), dict(channel="in_app", text="b")],
            )
        ]


def _flag_client():
    return create_app(FlagStub(), SecurityConfig()).test_client()


def test_csv_export_neutralises_formulas_and_downloads():
    r = _flag_client().get("/api/export", query_string={"week": WEEK})
    assert r.status_code == 200 and r.mimetype == "text/csv"
    assert r.headers["Content-Disposition"] == f'attachment; filename="r5_flags_{WEEK}.csv"'
    lines = r.get_data(as_text=True).splitlines()
    assert lines[0].startswith("week_start,store_id") and "'=HYPERLINK" in lines[1] and ",2" in lines[1]
    assert not any(cell.startswith("=") for cell in lines[1].split(","))


def test_csv_export_uses_allow_list(client):
    for bad in [{}, {"week": "2030-01-07"}, {"week": WEEK + "\r\nSet-Cookie: x=1"}, {"week": WEEK, "x": "1"}]:
        assert client.get("/api/export", query_string=bad).status_code == 400, bad


def test_unknown_or_repeated_query_parameters_are_refused(client):
    assert client.get("/api/brief?region=South&week=" + WEEK + "&debug=1").status_code == 400
    assert client.get("/api/brief?region=South&region=South&week=" + WEEK).status_code == 400
    assert client.get("/api/meta?x=1").status_code == 400
    assert client.get("/api/health?x=1").status_code == 400
    assert client.get("/api/brief?region=South&week=" + WEEK).status_code == 200


def test_overlong_urls_are_refused(client):
    assert client.get("/api/health?" + "a=" + "b" * 600).status_code == 414


def test_log_forging_through_the_path_is_neutralised(client, caplog):
    with caplog.at_level(logging.INFO, logger="voice_of_store.web"):
        client.get("/x%0d%0a2026-01-01 INFO forged line id=0")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "\n" not in text and "\r" not in text and "forged" in text  # present, but on the same line


def test_extra_security_headers_and_trusted_types(client):
    r = client.get("/")
    csp = r.headers["Content-Security-Policy"]
    assert "require-trusted-types-for 'script'" in csp and "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
    assert r.headers["Cross-Origin-Embedder-Policy"] == "require-corp"
    assert r.headers["X-Permitted-Cross-Domain-Policies"] == "none" and len(r.headers["X-Request-ID"]) == 12


def test_https_mode_adds_upgrade_insecure_requests():
    c = make(behind_https=True)
    assert "upgrade-insecure-requests" in c.get("/").headers["Content-Security-Policy"]


def test_gzip_only_when_asked_and_only_for_large_text(client):
    big = client.get("/app.js", headers={"Accept-Encoding": "gzip"})
    assert big.headers.get("Content-Encoding") == "gzip" and "Accept-Encoding" in big.headers["Vary"]
    import gzip

    assert b"use strict" in gzip.decompress(big.data)
    assert client.get("/app.js").headers.get("Content-Encoding") is None
    assert client.get("/api/health", headers={"Accept-Encoding": "gzip"}).headers.get("Content-Encoding") is None


def test_fuzzed_requests_never_crash_or_reflect():
    import random

    rng = random.Random(7)
    c = make(rate_per_minute=10**6, assistant_per_minute=10**6, classify_per_minute=10**6)
    alphabet = "abcXYZ<>\"'`{}$%&=;:/\\.-_ \t\n\x00\x7f‮\U0001f600é"
    for _ in range(300):
        junk = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
        for r in (
            c.post("/api/assistant", json={"message": junk or "x"}),
            c.post("/api/classify", json={"text": junk or "x", "channel": "in_app"}),
            c.get("/api/brief", query_string={"region": junk, "week": junk}),
            c.get("/api/store", query_string={"store_id": junk, "week": junk}),
        ):
            assert r.status_code in (200, 400, 429), (r.status_code, junk)
            body = r.get_data(as_text=True)
            assert "Traceback" not in body and (not junk.strip() or "<" not in junk or junk not in body)
    for raw in (b"", b"{", b"[]", b"null", b'{"message":' + b"[" * 500, b"\xff\xfe\x00"):
        assert c.post("/api/assistant", data=raw, headers={"Content-Type": "application/json"}).status_code == 400


def test_real_flags_explain_what_changed_and_brief_shows_evidence_fields(real):
    state, c = real
    week = state.weeks[-1]
    flags = c.get("/api/flags", query_string={"week": week}).get_json()["flags"]
    assert flags, "the last week should carry at least one flag in the shipped submission"
    for f in flags:
        ch = f["change"]
        assert ch["this_week"] >= 2 and ch["days_span"] >= 1 and "against a usual" in ch["summary"]
        assert f["next_step"] and f["status"] and f["owner"]
    b = c.get("/api/brief", query_string={"region": state.regions[0], "week": week}).get_json()["entries"]
    for e in b:
        assert e["next_step"] and e["status"] and e["first_seen"] and e["by_channel"] and 0 <= e["confidence"] <= 1
        assert all(len(q) == 3 for q in e["quotes"])
        if e["safety"] and e["tier"] == "UNVERIFIED":
            assert "allegation" in e["status"]
    page = c.get("/brief", query_string={"region": state.regions[0], "week": week}).get_data(as_text=True)
    assert "Next step:" in page and "Per 10,000 weekly visits" in page and "approximation" in page
