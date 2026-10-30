# Security notes for the Voice-of-Store web demo

This page states what the web demo defends against, how, and what it does not do. It covers `FULL_CODE/serve.py` and
`FULL_CODE/src/voice_of_store/web/`. The detector and classifier (`detect.py`, `make_submission.py`) have no network code at all.

## What the app is
A read-only analytics page over synthetic data plus stateless analytics, assistant, and optional notification endpoints. It has no cookies, database, or uploads. The detector and local assistant make no outbound calls. Optional Gemini summary mode and SMTP alert delivery are isolated opt-ins; both are disabled unless configured, and SMTP additionally requires authenticated per-batch human approval.

## Threat model and controls

| Risk | Control | Test |
|---|---|---|
| XSS through feedback text (texts are attacker-controlled in real life) | The page builds the DOM with `textContent` only (no `innerHTML`, `eval`, inline script or inline style); the printable brief escapes every value; CSP `script-src 'self'` with no `unsafe-inline` on the app page; the brief page has no script permission at all | `test_user_content_is_escaped...`, `test_frontend_never_uses_html_injection`, `test_security_headers_everywhere` |
| Clickjacking | `X-Frame-Options: DENY` and CSP `frame-ancestors 'none'` | headers test |
| MIME sniffing | `X-Content-Type-Options: nosniff`; JSON responses carry `application/json` | headers test |
| DNS rebinding and host-header attacks against a localhost server | Host allow-list (`127.0.0.1`, `localhost`, `[::1]` plus `R5_ALLOWED_HOSTS`) | `test_host_header_attack_refused` |
| Cross-site requests (CSRF) | The only state-free POST requires `Content-Type: application/json` (a cross-site form cannot send it without a CORS pre-flight, and OPTIONS is refused with 405); `Origin` must be an allowed host; `Sec-Fetch-Site` must be same-origin or none; there are no cookies or sessions to ride on | `test_cross_site_post_refused`, `test_content_type_and_method_rules`, `test_no_cookies_set` |
| Resource exhaustion | Body limit 8 KiB (waitress 16 KiB); text limit 2,000 characters; per-client rate limits (120 requests a minute, 20 classify a minute, 40 assistant questions a minute) with bounded memory; waitress channel timeout 30 s; a stateless classifier of fixed cost | rate-limit and oversize tests |
| Injection and path traversal | Every query value must be in an allow-list built at start-up (regions, weeks, store ids, issue types, channels); static files come from a fixed table of three names, never from the URL; no SQL, no shell, no `eval`, no template rendering of user input | `test_query_parameters_use_allow_lists`, `test_only_allow_listed_static_files` |
| Information leaks through errors | One generic JSON error handler; exception messages and stack traces are never returned; each error carries a random request id for support | `test_errors_do_not_leak_internals` |
| Personal data in logs | The app's own log lines hold method, path, status, duration and request id only: never query values, request bodies or feedback text. (The Flask development server also writes its own access line with the request path and query string; those values are restricted to the allow-lists, and POST bodies are never logged. waitress does not write access logs by default.) Texts shown to a person pass through `redact()` (emails, phone numbers, long digit runs) | `test_logs_contain_no_user_text`, `test_redact_and_clean_input` |
| Unauthorised access to the data pages and API | Optional login for every page and API route (`R5_AUTH_USER` + `R5_AUTH_HASH`, a salted scrypt hash made by `scripts/make_auth_hash.py`; the password is never stored or logged); user-name and password are checked in constant time with a dummy hash for unknown users; failed logins are limited to 10 a minute per client; the server refuses to expose a login over plain HTTP unless `R5_HTTPS=1`; `/api/health` stays open for container health checks and returns no data | `test_login_*`, `test_failed_logins_are_rate_limited`, `test_exposure_rules` |
| Abuse of the classify endpoint | Optional `R5_API_KEY` (header `X-API-Key`, compared in constant time); the server refuses to start on a non-loopback address unless `R5_ALLOWED_HOSTS` is set, and warns if no API key is set | `test_api_key_when_configured` |
| Spoofed client address behind a proxy | `X-Forwarded-For` is ignored unless `R5_TRUST_PROXY=1`; when trusted, only the last (proxy-added) entry is used | `test_forwarded_header_ignored...` |
| Downgrade to plain HTTP | `Strict-Transport-Security` is added when `R5_HTTPS=1` (set only when TLS is terminated in front of the app) | `test_hsts_only_when_declared_https` |
| Information disclosure through fingerprinting | No `Server` version string (waitress `ident=""`; custom handler for the development server); `Referrer-Policy: no-referrer`; `Permissions-Policy` denies camera, microphone, geolocation, payment and USB; `Cache-Control: no-store` on API responses | headers test |
| Insecure deserialisation | No pickle or joblib anywhere; the classifier is trained at start-up from the labelled CSV (checked by `package_check.py`) | package check |
| Supply chain | Dependencies pinned in `requirements.txt`; run `pip-audit -r FULL_CODE/requirements.txt` before deployment (needs internet; not run in the build sandbox); ruff with the bandit (`S`) rules is part of CI-style checks | lint |
| Secrets | None in the repo; `.env` is git-ignored; configuration is read from environment variables; `.env.example` lists them | package check scans for secret-like strings |
| Container | `Dockerfile` runs as a non-root user, copies no data and no `.git`, has a health check | review |

## Configuration (environment variables)

| Variable | Meaning |
|---|---|
| `R5_ALLOWED_HOSTS` | Comma-separated public host names accepted in the `Host` header (required to expose the app) |
| `R5_AUTH_USER`, `R5_AUTH_HASH` | Turn on the login (both or neither). Make the hash with `python FULL_CODE/scripts/make_auth_hash.py <user>` |
| `R5_API_KEY` | When set, `POST /api/classify` needs the header `X-API-Key: <value>` |
| `R5_HTTPS` | `1` when TLS is terminated in front of the app: adds HSTS |
| `R5_TRUST_PROXY` | `1` only behind a trusted reverse proxy: use its `X-Forwarded-For` for rate limiting |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Optional assistant summary; sends only redacted deterministic answer fields, never the question or raw feedback |
| `R5_SMTP_HOST`, `R5_SMTP_PORT`, `R5_SMTP_FROM`, `R5_ALERT_RECIPIENTS` | Optional SMTP delivery; STARTTLS is required and exact recipients are shown for each human approval |
| `R5_SMTP_USERNAME`, `R5_SMTP_PASSWORD` | Optional SMTP authentication; set both or neither |
| `R5_ALERT_AUDIT_PATH` | Local append-only JSONL audit file; default `out/notification_audit.jsonl` |

## What this does NOT do (read before exposing it)
- Authentication is one shared login (or none, by default on localhost). There are no user accounts, roles, password reset or
  single sign-on. If the data were real, use SSO behind a reverse proxy. The demo data is synthetic.
- It does not terminate TLS. Use a reverse proxy (Caddy, nginx, a cloud load balancer) for HTTPS when it leaves localhost.
- Rate limits live in process memory and are per worker. Behind several workers use the proxy's limits as well.
- It has not had an independent penetration test. The tests above check each stated control; they do not prove absence of flaws.
- `waitress` could not be installed in the build sandbox, so the production-server path was reviewed but not run there.

## Reporting
Open an issue on the team repository or contact the team lead. Do not post exploit details publicly.

## Store assistant (`POST /api/assistant`)
- Default mode is deterministic and local: it matches the question to an intent (brief, store, emerging, owner, escalation, accuracy, classify) and reads from the same in-memory data as the dashboard. Instruction-like text is treated as an unknown question.
- Optional `mode: "gemini"` adds a generated summary of the deterministic response. Only allow-listed response fields are sent, with store names, email addresses, and phone numbers redacted; the question and raw feedback are never sent. The original local answer remains available beside the generated summary.
- Body accepts `{"message": "<string>"}` or `{"message": "<string>", "mode": "local|gemini"}` (1-300 characters, no extra fields); same JSON-only, Origin, Sec-Fetch-Site, rate-limit, and login checks as the classify endpoint.
- `GET /api/store` uses the same allow-lists as the other query endpoints (store id and week must be in the start-up lists).
- Live check: start the server, then `python FULL_CODE/scripts/security_probe.py http://127.0.0.1:8000` (32 checks, run against this build: all passed).

## Approved head-office alerts
- `GET /api/alerts/preview?week=<allow-listed-week>` builds a quote-free draft from current emerging flags. Preview and send require `R5_AUTH_USER`/`R5_AUTH_HASH` authentication.
- `POST /api/alerts/send` accepts only the week, preview batch ID, and explicit approval. It rebuilds the current flags, rejects stale previews, sends through SMTP STARTTLS, and records the approver and attempt in the audit file before delivery. Repeated attempts for the same batch fail closed; inspect the audit before any manual retry.
- The alert email identifies reports as unverified, omits raw evidence quotes, and lists only the configured recipients. The browser asks for confirmation on every batch. Configure server-side SMTP settings before enabling this feature; no live destination or credentials are provided by default.

## Hardening round 2 (what was added and why)
| Gap closed | Control | Test |
|---|---|---|
| DOM XSS through script sinks | CSP `require-trusted-types-for 'script'` (the UI has no sink anyway; this makes a future one fail closed) | `test_extra_security_headers_and_trusted_types` |
| Log forging via the request path | Control characters replaced and length bounded before a path is logged | `test_log_forging_through_the_path_is_neutralised` |
| Parameter pollution and probing | Every route accepts exactly its own query keys, each once; URLs over 512 characters get 414 | `test_unknown_or_repeated_query_parameters_are_refused`, `test_overlong_urls_are_refused` |
| Spreadsheet formula injection in the CSV export | Cells starting with `= + - @` tab or CR get a leading apostrophe; the week in the file name is allow-listed (no header injection) | `test_csv_export_neutralises_formulas_and_downloads`, `test_csv_export_uses_allow_list` |
| Cross-origin leaks and legacy plugins | `Cross-Origin-Embedder-Policy`, `X-Permitted-Cross-Domain-Policies: none`; `upgrade-insecure-requests` behind HTTPS | `test_extra_security_headers_and_trusted_types`, `test_https_mode_adds_upgrade_insecure_requests` |
| Support traceability | `X-Request-ID` on every response, matching the log line | same |
| Unknown unknowns | A seeded fuzz test sends 1,200 hostile requests to four endpoints and asserts no 500, no traceback, no reflection; malformed JSON bodies get 400 | `test_fuzzed_requests_never_crash_or_reflect` |

**What "secure" means here, stated honestly.** No system can be proved 100 percent secure; this one removes every issue found by
review, tests, a fuzzer and a live attack script, and keeps the attack surface small (no database, uploads, cookies, outbound
calls, LLM or pickle). Still open: no independent penetration test, `pip-audit` not run (needs internet), one shared login, TLS must be
supplied by a reverse proxy, and per-process rate limits (one worker).

## Report pages
`GET /report` and `GET /api/report` are read-only, take no parameters (any query string gets 400), need the same login as every other route, and the page has inline CSS and SVG only: no script, CSP `default-src 'none'`. Every value is escaped (`test_report_page_escapes_every_value_and_has_no_script`). `scripts/security_probe.py` checks both (32 checks, all passed).
