# Security notes for the Voice-of-Store web demo

This page states what the web demo defends against, how, and what it does not do. It covers `FULL_CODE/serve.py` and
`FULL_CODE/src/voice_of_store/web/`. The detector and classifier (`detect.py`, `make_submission.py`) have no network code at all.

## What the app is
A read-only analytics page over synthetic data plus one stateless endpoint (`POST /api/classify`). It has no accounts, no
cookies, no database, no uploads and no file writes. It makes no outbound network calls. No LLM or external API is used.

## Threat model and controls

| Risk | Control | Test |
|---|---|---|
| XSS through feedback text (texts are attacker-controlled in real life) | The page builds the DOM with `textContent` only (no `innerHTML`, `eval`, inline script or inline style); the printable brief escapes every value; CSP `script-src 'self'` with no `unsafe-inline` on the app page; the brief page has no script permission at all | `test_user_content_is_escaped...`, `test_frontend_never_uses_html_injection`, `test_security_headers_everywhere` |
| Clickjacking | `X-Frame-Options: DENY` and CSP `frame-ancestors 'none'` | headers test |
| MIME sniffing | `X-Content-Type-Options: nosniff`; JSON responses carry `application/json` | headers test |
| DNS rebinding and host-header attacks against a localhost server | Host allow-list (`127.0.0.1`, `localhost`, `[::1]` plus `R5_ALLOWED_HOSTS`) | `test_host_header_attack_refused` |
| Cross-site requests (CSRF) | The only state-free POST requires `Content-Type: application/json` (a cross-site form cannot send it without a CORS pre-flight, and OPTIONS is refused with 405); `Origin` must be an allowed host; `Sec-Fetch-Site` must be same-origin or none; there are no cookies or sessions to ride on | `test_cross_site_post_refused`, `test_content_type_and_method_rules`, `test_no_cookies_set` |
| Resource exhaustion | Body limit 8 KiB (waitress 16 KiB); text limit 2,000 characters; per-client rate limits (120 requests a minute, 20 classify a minute) with bounded memory; waitress channel timeout 30 s; a stateless classifier of fixed cost | rate-limit and oversize tests |
| Injection and path traversal | Every query value must be in an allow-list built at start-up (regions, weeks, store ids, issue types, channels); static files come from a fixed table of three names, never from the URL; no SQL, no shell, no `eval`, no template rendering of user input | `test_query_parameters_use_allow_lists`, `test_only_allow_listed_static_files` |
| Information leaks through errors | One generic JSON error handler; exception messages and stack traces are never returned; each error carries a random request id for support | `test_errors_do_not_leak_internals` |
| Personal data in logs | Logs hold method, path, status, duration and request id only: never query values, request bodies or feedback text. Texts shown to a person pass through `redact()` (emails, phone numbers, long digit runs) | `test_logs_contain_no_user_text`, `test_redact_and_clean_input` |
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
| `R5_API_KEY` | When set, `POST /api/classify` needs the header `X-API-Key: <value>` |
| `R5_HTTPS` | `1` when TLS is terminated in front of the app: adds HSTS |
| `R5_TRUST_PROXY` | `1` only behind a trusted reverse proxy: use its `X-Forwarded-For` for rate limiting |

## What this does NOT do (read before exposing it)
- It has no user authentication. Read-only endpoints are open to anyone who can reach the port. If the data were real, put it
  behind SSO or a reverse proxy with authentication. The demo data is synthetic.
- It does not terminate TLS. Use a reverse proxy (Caddy, nginx, a cloud load balancer) for HTTPS when it leaves localhost.
- Rate limits live in process memory and are per worker. Behind several workers use the proxy's limits as well.
- It has not had an independent penetration test. The tests above check each stated control; they do not prove absence of flaws.
- `waitress` could not be installed in the build sandbox, so the production-server path was reviewed but not run there.

## Reporting
Open an issue on the team repository or contact the team lead. Do not post exploit details publicly.
