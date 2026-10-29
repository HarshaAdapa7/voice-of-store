# Requirements traceability

Every requirement we were given, where it is met in the code, and the test that proves it. Run all tests with
`cd FULL_CODE && python -m pytest -q`; run the rubric self-audit with `python FULL_CODE/scripts/self_audit.py --full`.

## Deliverables (pack README, "Your job")

| ID | Requirement | Implemented in | Test |
|---|---|---|---|
| D1 | Weekly one-page brief per region: top 5, evidence quotes, affected stores, trend arrow | `brief.py` (`build_region_week`, `render_html`), `briefing.py` | `test_d1_brief_per_region_has_top5_with_quotes_stores_and_trend`, `test_brief_html_keeps_every_required_element_and_is_compact`; one A4 page checked by `scripts/check_brief_pages.py` (65 of 65) |
| D2 | Owner and severity on every issue; escalation rule stated | `routing.py`, `classify.py` (policy floors) | `test_d2_every_issue_has_owner_severity_and_the_rule_is_stated` |
| D3 | Emerging-issue detection for small, rising issues at one store | `detect.py`, `pipeline.py`, `evidence.py` | `test_fr11_small_rising_issues_are_flagged_outside_the_top_five`, `test_future_rows_do_not_change_flags` |
| D4 | `evaluate.py` score | `tools/evaluate.py` (organiser file, unmodified), `submission.py` | `test_pack_every_row_is_predicted_once_with_valid_values`, `test_pack_flags_cite_two_existing_ids_within_the_budget` |
| D5 | Precision statement | `report.py`, `analysis.py`, `report_page.py` | `test_real_report_is_consistent`, `test_report_page_escapes_every_value_and_has_no_script` |
| S1 | Stretch: de-duplicate one incident across channels | `dedup.py` | `test_stretch_deduplication_collapses_reports_into_incidents` |

## Pack rules

| Rule | Where | Test |
|---|---|---|
| Predict every row of `feedback.csv` | `submission.py` | `test_pack_every_row_is_predicted_once_with_valid_values` |
| A flag cites at least 2 ids that exist, share the store (or its named locality), the week and the type | `evidence.py` re-implements the checks | `test_pack_flags_cite_two_existing_ids_within_the_budget`, evidence tests in `test_units.py` |
| Flags use only data up to that week's Sunday | `pipeline.py`, `detect.py` (sequential statistic) | `test_future_rows_do_not_change_flags` |
| Detector command shape, no internet, under 10 minutes, no hard-coded dates or ids | `detect.py`, `submission/detector_cmd.txt` | `test_pack_detector_command_shape`, `test_detector_accepts_a_folder_or_the_file`, disguised-copy test; `package_check.py` scans for dates and ids; measured about 20 s |
| At most 3 flags a week on average | `detect._cap_flags` | `test_pack_flags_cite_two_existing_ids_within_the_budget` |
| Normalise for store size | `detect.expected_counts` (footfall exposure) | detector tests |

## Functional requirements FR-07 to FR-11

| ID | Requirement | Implemented in | Test |
|---|---|---|---|
| FR-07 | Safety, allergen, hygiene, misconduct always at least high; dedicated escalation; allegation is not a verified incident | `routing.py` (`SAFETY_TYPES`, `action_window`, `verification_status`), `brief.build_region_week` (safety never cut), `classify.py` | `test_fr07_policy_floor_and_safety_types_are_high_on_every_predicted_row`, `test_fr07_safety_types_are_never_dropped_from_a_brief`, `test_status_never_presents_a_report_as_established_fact` |
| FR-08 | Quotes, count, stores, channels, times, independence, confidence, status | `brief._issue_entry`, `dedup.py` | `test_fr08_and_fr09_each_issue_carries_evidence_status_and_next_step` |
| FR-09 | Owner from the taxonomy, severity, rule, evidence, next step | `routing.next_step`, `brief.py` | same, `test_every_issue_type_has_a_next_step_and_safety_types_get_specific_ones` |
| FR-10 | Unverified feedback and store-size normalisation, limits disclosed | `detect.py` (footfall), `brief.py` (per-10,000 rates and disclosure line) | `test_fr10_store_size_is_used_and_the_limit_is_disclosed` |
| FR-11 | Flag low-volume rising issues and explain what changed, where, how fast, with evidence | `detect.py`, `web/state._change` | `test_real_flags_explain_what_changed_and_brief_shows_evidence_fields` |

## Non-functional requirements

| Area | How it is met | Evidence |
|---|---|---|
| Security | CSP with Trusted Types, host allow-list, origin and fetch-metadata checks, strict query keys, rate limits, optional scrypt login and API key, generic errors, no secrets, no unsafe deserialisation, CSV formula guard, log-forging guard | `SECURITY.md`, `tests/test_web.py` (fuzz and header tests), `scripts/security_probe.py` (32 live checks) |
| Performance | One detector run for one week takes about 20 s (limit 600 s); web start-up about 20 s then every request is an indexed lookup; gzip and caches | `scripts/self_audit.py --full` times it |
| Reproducibility | Fixed seed, no randomness at run time, submission regenerates byte-identical from a fresh clone | `tests/test_end_to_end.py` |
| Privacy | Synthetic data only; contact details masked before display; feedback text never logged | `text.redact`, `test_logs_contain_no_user_text` |
| Reliability | Clear errors for missing or malformed files, edge cases (empty, tiny, unseen channel) | `tests/test_edge_cases.py` |
| Usability and accessibility | Keyboard-operable tabs, skip link, live regions, dark mode, reduced motion, printable one-page briefs | `static/`, `scripts/check_brief_pages.py` |
| Maintainability | Modules by job, functions under 70 lines, full type hints, ruff and mypy clean | `scripts/self_audit.py` |
| Portability | Python 3.12 or newer, pinned requirements, Dockerfile | `README.md` |
| Honesty | Limits, unverified feedback and approximations are stated on every output | `report_page.py`, `brief.py` |
