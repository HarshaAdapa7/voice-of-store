# Coding Guidelines v1.1: compliance, rule by rule

Status: **Met** = done and checked; **Met, not run here** = done but a step could not be run in the build sandbox;
**N/A** = the rule is about something this project does not use. Commands are run from the project root.

| # | Rule | Status | Evidence |
|---|---|---|---|
| 1 | Readable code, clear names | Met | Modules by job under `src/voice_of_store/` (`classify`, `detect`, `evidence`, `stores`, `routing`, `brief`, `dedup`, `report`, `io`, `text`, `web/`). Functions are short with one job (the long ones were split: `run_statistic`, `build_region_week`, `render_html`, `create_app`, `install`). |
| 1 | Formatter and linter, warnings fixed | Met | `ruff format --check FULL_CODE` and `ruff check FULL_CODE` pass (rules E, F, W, I, B, UP, S). `tools/evaluate.py` is the organisers' file and is excluded unmodified. |
| 1 | Type hints | Met | All code is annotated; `mypy` passes on `src` and the entry scripts. |
| 1 | No dead code, commented-out blocks or debug prints | Met | CLI status goes through `logging` (`logs.py`); the only `print` calls are the help text in `main.py`, the result lines of `package_check.py` and `injection_grid.py`, and the output of `make_auth_hash.py`. |
| 1 | Don't repeat logic | Met | One pipeline (`pipeline.py`) is used by `detect.py` and `make_submission.py`, so both give identical flags (tested). |
| 2 | One folder `FULL_CODE/`, only `README.md`, `.gitignore`, `submission/`, `LICENSE` beside it | Met | `python FULL_CODE/main.py check` (`scripts/package_check.py`) checks the tracked top level. |
| 2 | UI, routes, business logic, data access in separate modules | Met | `web/static` (UI), `web/server.py` (routes), `web/security.py` (controls), `web/state.py` and `io.py` (data), core logic outside `web/`; the check fails if core code imports the web layer. |
| 2 | One obvious entry point | Met | `python FULL_CODE/main.py <submission\|briefs\|serve\|detect\|check\|grid>`. `detect.py` stays a script because `detector_cmd.txt` calls it. |
| 2 | Settings in one config or env vars | Met | Constants in `config.py`; web options in environment variables (`.env.example`). No hard-coded absolute paths, dates or ids (checked by `package_check.py`). |
| 2 | Database schema and seed files; no DB files committed | Met | Supabase PostgreSQL schema in scripts/supabase_schema.sql; sync CLI in scripts/supabase_sync.py; .env git-ignored; no DB files committed. |
| 3 | No secrets in code; `.env.example` committed; `.env` ignored | Met | `.env.example` lists every variable with dummy or commented values; `.gitignore` lists `.env`; `package_check.py` scans for secret-like strings. No keys exist in the project. |
| 3 | Never print secrets or personal records in logs or errors | Met | Logs hold method, path, status, time and request id only; errors are generic; `redact()` masks contact details before display (`test_logs_contain_no_user_text`, `test_errors_do_not_leak_internals`). |
| 4 | Validate every input (users, files, APIs) | Met | Web: allow-lists, type, length and shape checks (`test_classify_rejects_bad_input`, `test_query_parameters_use_allow_lists`, `test_assistant_endpoint_validates_input`, `test_store_endpoint_uses_allow_lists`). Files: `io.load_data` checks columns, ids, timestamps, enums (`test_load_data_rejects_bad_files_with_clear_message`). CLI: dates (`monday_of`). |
| 4 | Parameterised queries | Met | Supabase PostgREST client and parameterized queries via db module. |
| 4 | Server-side permission checks | Met | Optional login on every page and API route, plus an API key for the POST endpoint; checked on the server, not hidden in the UI (`test_login_protects_every_page_and_api`). |
| 4 | Restrict CORS, debug off, certificate checks on | Met | No CORS headers are sent (same-origin only; cross-origin POSTs are refused); `debug=False`; the app makes no outbound calls. |
| 4 | No eval, exec, shell or pickle on user input | Met | None used (`test_frontend_never_uses_html_injection`, forbidden-import check in `package_check.py`). |
| 5 | Lockfile committed | Met | `FULL_CODE/requirements.txt` pins every dependency except `waitress` (see below). The guidelines accept pinned `requirements.txt`; `uv.lock` could not be produced because the sandbox cannot reach PyPI. |
| 5 | Only libraries actually used; run the package audit | Partly | Dependencies are the ones imported (plus Flask's own pinned dependencies). `pip-audit -r FULL_CODE/requirements.txt` **was not run** (needs internet): run it before submitting. `waitress` is given as a minimum version because it could not be installed here. |
| 5 | Licences respected, LICENSE present | Met | MIT `LICENSE`; third-party libraries and licences listed in the README. |
| 6 | Meaningful tests on core logic, edge cases, real assertions | Met | `tests/`: units, edge cases (empty, invalid, boundary, missing files), detector causality, evidence rules, disguised-copy equality, classifier policy, web security and API. One command: `cd FULL_CODE && python -m pytest -q`. |
| 6 | Mock LLM and external API calls | N/A | No LLM or external API is used. |
| 7 | Git with meaningful commits; proper `.gitignore`; no junk | Met | `.gitignore` covers data, models, env, venv, caches, logs, zips, `.DS_Store`. History is short because the work was built in a few sessions; messages describe each change. |
| 7 | Synthetic data only | Met | The pack is synthetic; no real personal data anywhere. |
| 8 | Specific exceptions; no silent swallowing | Met | `DataError`, `NotEnoughLabels` are caught at the entry points and shown as `error: ...` without a traceback (`test_detector_cli_reports_problems_without_traceback`). The one catch-all is the web error handler, which logs the exception type and returns a generic message. No `except: pass`. |
| 8 | Timeouts, retries, fallbacks for network calls | N/A | There are no network, database or API calls. The server sets a channel timeout (waitress) and a body limit. |
| 8 | Logging library, not print | Met | `logging` throughout (`logs.py`, level from `R5_LOG_LEVEL`). |
| 9 | LLM and AI API rules | N/A | No LLM is used at run time, including the store assistant, which is rule-based (`assistant.py`): no prompts, no external calls, no user text sent anywhere. |
| 10 | Agent and MCP rules | N/A | No agents, tools or MCP servers in the product. |
| 11 | Fixed seeds, no leakage, time-based split | Met | `SEED` in `config.py`; validation trains on weeks 1-9 and tests on weeks 10-13 (`report.time_split_validation`); at run time the classifier sees only labels dated before the as-of cutoff (`test_future_rows_do_not_change_flags`). |
| 11 | Baseline comparison, suitable metrics | Met | Macro-F1, weighted-F1, actionable F1 and precision with intervals; organisers' baseline quoted in the README. |
| 11 | Safe model loading | Met | No pickle or joblib; the model is trained at start-up from the public CSV. |
| 11 | No large data or weights committed | Met | `data/` and `models/` are ignored; the repo holds only code and the three small submission files. |
| 12 | README with what, how to run, tests, architecture, AI usage, pre-built code, limitations | Met | `README.md` has each section (checked by `package_check.py`) plus Security and a causal statement. |
| 12 | Comments explain why; docstrings on key functions | Met | Docstrings on public functions; comments state reasons (for example why the leave-one-out chain factor exists). |
| FP | Declare AI assistants, pre-built code, copied snippets | Met | README "AI usage" and "Pre-built and third-party code". `tools/evaluate.py` is declared as the organisers' file. |
| FP | Team can explain the code | Team action | Read `README.md`, `DEMO_SCRIPT.md` and this table before the demo. |

## Submission checklist (page 4)

| Item | Status |
|---|---|
| Fresh `git clone` zipped as `teamID_psID.zip` | Team ID 120: `120_R5.zip` |
| Code in `FULL_CODE/`, own README next to it | Met |
| No secrets; `.env` excluded; `.env.example` included | Met |
| No `node_modules`, virtual environments, build output, large data or model files | Met |
| Lockfile committed | Met (pinned `requirements.txt`) |
| Formatter and linter run, warnings fixed | Met |
| Tests included with the command to run them | Met |
| README covers what, how to run, architecture, AI usage, pre-built code, limitations | Met |
| Notebooks run top to bottom | N/A (no notebooks) |

## Known gaps, stated plainly
- `pip-audit` and the `waitress` production-server path were not run (no internet in the build sandbox).
- The Dockerfile was written and reviewed but not built.
- Tested on Python 3.13 only; the stated minimum is 3.12 (the pinned libraries need it).
- No independent security test; the controls are checked by this project's own tests and by `scripts/security_probe.py` against a running instance.
- `mypy` is clean and 148 tests pass (95.0% line coverage of src/) on Python 3.13 in the build sandbox.
