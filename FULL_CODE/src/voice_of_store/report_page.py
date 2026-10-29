"""The evaluation report as one self-contained page: inline CSS and inline SVG only, no script, every value escaped."""

from __future__ import annotations

import html

from .routing import ESCALATION_RULE

CSS = """
:root{--bg:#fff;--fg:#1d2330;--mut:#5b6475;--bd:#d9dde5;--card:#f7f8fa;--hi:#b42318;--acc:#175cd3;--ok:#067647}
@media(prefers-color-scheme:dark){:root{--bg:#12151c;--fg:#e8ebf2;--mut:#9aa3b5;--bd:#2a3040;--card:#1a1f2a;--hi:#f97066;--acc:#84adff;--ok:#47cd89}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;margin:0 auto;max-width:980px;padding:16px}
h1{font-size:22px;margin:0}h2{font-size:17px;margin:24px 0 6px;border-bottom:1px solid var(--bd);padding-bottom:4px}h3{font-size:14px;margin:12px 0 4px}
.sub,.meta{color:var(--mut)}.meta{font-size:12.5px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px;margin:12px 0}
.tile{border:1px solid var(--bd);border-radius:8px;padding:8px 10px;background:var(--card)}.tile b{display:block;font-size:22px}
.tile span{color:var(--mut);font-size:12px}
table{border-collapse:collapse;width:100%;margin:6px 0;font-size:13px}td,th{border-bottom:1px solid var(--bd);padding:4px 6px;text-align:left}
th{color:var(--mut);font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.callout{border-left:4px solid var(--acc);background:var(--card);padding:8px 12px;margin:10px 0;border-radius:4px}
.warn{border-left-color:var(--hi)}.bar{fill:var(--acc)}.flagbar{fill:var(--hi)}svg{display:block}
ul{margin:4px 0;padding-left:20px}@media print{body{padding:0}h2{break-after:avoid}table{break-inside:avoid}}
"""


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def _ci(c: list[float] | None) -> str:
    return "" if not c else f" ({_pct(c[0])} to {_pct(c[1])})"


def _table(head: list[str], rows: list[list[str]], numeric: set[int] | None = None) -> str:
    esc, num = html.escape, numeric or set()
    th = "".join(f"<th class='{'n' if i in num else ''}'>{esc(h)}</th>" for i, h in enumerate(head))
    body = "".join(
        "<tr>" + "".join(f"<td class='{'n' if i in num else ''}'>{esc(str(c))}</td>" for i, c in enumerate(r)) + "</tr>"
        for r in rows
    )
    return f"<table><tr>{th}</tr>{body}</table>"


def _spark(values: list[int], flags: list[int], width: int = 520, height: int = 70) -> str:
    n, top = len(values), max(1, max(values, default=1))
    bw = width / max(1, n)
    bars = []
    for i, v in enumerate(values):
        h = (v / top) * (height - 16)
        cls = "flagbar" if flags[i] else "bar"
        bars.append(
            f"<rect class='{cls}' x='{i * bw + 1:.1f}' y='{height - h - 12:.1f}' width='{max(1, bw - 2):.1f}' height='{h:.1f}'/>"
        )
    return f"<svg viewBox='0 0 {width} {height}' width='100%' height='{height}' role='img' aria-label='Weekly volume, red where a flag was raised'>{''.join(bars)}</svg>"


def _summary(rep: dict) -> str:
    v, e, d, dd = rep["validation"], rep["escalation"], rep["detection"], rep["dedup"]
    lead = next((i for i in d["incidents"] if i["lead_weeks"] is not None), None)
    parts = [
        f"On forward-in-time validation the classifier scores {v['classification']:.3f}.",
        f"Of the {e['by_confidence'][0]['escalated']} records it escalated (actionable and high or critical), "
        f"{_pct(e['by_confidence'][0]['precision'])} were truly actionable.",
    ]
    sr = e["safety_recall"]
    if sr["recall"] is not None:
        parts.append(
            f"It caught {sr['caught']} of {sr['truly_safety']} truly safety-type reports ({_pct(sr['recall'])}); the rest are the main known risk."
        )
    if lead:
        parts.append(f"On the public worked incident the detector flagged {lead['lead_weeks']} week(s) before the naive rule.")
    parts.append(f"De-duplication turns {dd['reports']:,} actionable reports into {dd['incidents']:,} incidents.")
    return " ".join(parts)


def _safety_text(sr: dict, q: dict) -> str:
    where = "; ".join(f"{n} as {k}" for k, n in sr["missed_as"].items()) or "none missed"
    return (
        f"{sr['caught']} of {sr['truly_safety']} truly safety-type actionable reports were escalated as a safety type at high or above "
        f"({_pct(sr['recall'])}, 95% interval {_ci(sr['ci']).strip(' ()')}). The missed ones were predicted as: {where}. "
        f"Separately, {q['safety_no_store']:,} records look like safety types but name no store; the pack labels such records not actionable, "
        "so they are not escalated to a store. The weekly brief lists every safety-type entry beyond the top 5."
    )


def _classification(c: dict) -> str:
    weak = _table(
        ["Type", "Name", "Support", "Precision", "Recall", "F1"],
        [[t["id"], t["name"], t["support"], t["precision"], t["recall"], t["f1"]] for t in c["weakest"]],
        {2, 3, 4, 5},
    )
    conf = _table(["True type", "Predicted as", "Count"], [[x["true"], x["predicted"], x["count"]] for x in c["confusions"]], {2})
    sev = c["severity_labels"]
    cm = _table(
        ["True \\ predicted", *sev],
        [[sev[i], *row] for i, row in enumerate(c["severity_confusion"])],
        set(range(1, len(sev) + 1)),
    )
    ch = _table(
        ["Channel", "Records", "Issue accuracy", "Actionable precision"],
        [[x["channel"], x["n"], _pct(x["issue_accuracy"]), _pct(x["actionable_precision"])] for x in c["channels"]],
        {1, 2, 3},
    )
    return (
        f"<h3>Weakest issue types (at least 5 test records)</h3>{weak}<h3>Most frequent mix-ups</h3>{conf}"
        f"<h3>Severity: true against predicted</h3>{cm}<h3>By channel</h3>{ch}"
    )


def _escalation(e: dict) -> str:
    conf = _table(
        ["Confidence at least", "Escalated", "Truly actionable", "95% interval"],
        [[x["threshold"], x["escalated"], _pct(x["precision"]), _ci(x["ci"]).strip(" ()")] for x in e["by_confidence"]],
        {0, 1, 2},
    )
    own = _table(
        ["Owner", "Escalated", "Truly actionable", "95% interval"],
        [[x["owner"], x["escalated"], _pct(x["precision"]), _ci(x["ci"]).strip(" ()")] for x in e["by_owner"]],
        {1, 2},
    )
    return f"<h3>By confidence score (a ranking score, not a probability)</h3>{conf}<h3>By owning function</h3>{own}"


def _detection(d: dict) -> str:
    rows = [
        [
            i["incident"],
            i["store"],
            i["issue_type"],
            i["onset"],
            i["naive_detection"],
            i["our_first_flag"] or "never",
            i["lead_weeks"],
        ]
        for i in d["incidents"]
    ]
    table = (
        _table(["Incident", "Store", "Type", "Onset week", "Naive rule flags", "Our first flag", "Lead (weeks)"], rows, {6})
        if rows
        else "<p>No worked-example incident file was available.</p>"
    )
    return (
        f"{table}<p class='meta'>Replayed over all {d['weeks']} weeks; the statistic is sequential, so each flag uses only data up to its week, but the classifier here is trained on all public labels, so the count can differ a little from the submission file. "
        f"Other flags raised: {d.get('other_flags', 0)} ({d.get('flags_per_week', 0)} a week over the whole calendar; the budget is 3). "
        "Only one incident is public, so this is an example, not a score; the three hidden incidents are unknown.</p>"
    )


def _weeks(w: list[dict]) -> str:
    chart = _spark([x["actionable"] for x in w], [x["flags"] for x in w])
    rows = [[x["week"], x["records"], x["actionable"], x["incidents"], x["safety_reports"], x["flags"]] for x in w]
    return f"{chart}<p class='meta'>Actionable reports per week; red bars mark weeks with an emerging-issue flag.</p>" + _table(
        ["Week", "Records", "Actionable", "Incidents", "Safety-type reports", "Flags"], rows, {1, 2, 3, 4, 5}
    )


def render_report(rep: dict) -> str:
    """Render the report dict as one script-free HTML page; every value is escaped."""
    esc = html.escape
    v, e, q, dd = rep["validation"], rep["escalation"], rep["quality"], rep["dedup"]
    top = e["by_confidence"][0]
    sr = e["safety_recall"]
    tiles = [
        (f"{v['classification']:.3f}", "classification score (time-split)"),
        (_pct(top["precision"]), f"escalated issues truly actionable (n={top['escalated']})"),
        (_pct(sr["recall"]), f"safety-type reports caught (n={sr['truly_safety']})"),
        (f"{dd['reports_per_incident']}", "reports per incident after de-duplication"),
        (f"{q['store_resolved_share'] * 100:.1f}%", "records tied to a store"),
    ]
    tile_html = "".join(f"<div class='tile'><b>{esc(a)}</b><span>{esc(b)}</span></div>" for a, b in tiles)
    lo, hi = v["ci_actionable_high"]
    precision = (
        f"Of {v['n_pred_actionable_high']} records escalated (marked actionable and high or critical), "
        f"{v['precision_actionable_high']:.1%} were truly actionable (95% interval {lo:.1%} to {hi:.1%}). "
        f"Of all {v['n_pred_actionable']} records marked actionable, {v['precision_actionable']:.1%} were."
    )
    limits = [
        "Feedback is unverified: a report may be wrong, partial or one person's experience. Nothing here proves an incident.",
        "The labelled sample (3,000 records) over-represents rare issue types, so precision describes the sample, not the whole stream.",
        f"Only {q['labelled_rows']:,} of {q['records']:,} records have public labels; everything else is predicted.",
        f"{(1 - q['store_resolved_share']) * 100:.1f}% of records name no store the system can resolve; they cannot be routed to a store.",
        "Store comparisons use average weekly footfall from the store master. No per-store transaction counts were supplied, so rates are approximate.",
        "De-duplication is a stated heuristic (same store and type within 72 hours); the pack has no duplicate ground truth, so it is not scored.",
        "The detector lead is shown on one public incident. Three hidden incidents decide the real lead score.",
        "Confidence is a ranking score from the classifier margin, not a calibrated probability.",
    ]
    lim = "".join(f"<li>{esc(x)}</li>" for x in limits)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Voice-of-Store evaluation report</title><style>{CSS}</style></head><body>"
        "<h1>Voice-of-Store: evaluation report</h1><p class='sub'>How well it classifies, how precise its escalations are, how early it spots "
        "emerging issues, and where it is weak. Synthetic data.</p>"
        f"<div class='callout'><b>In one paragraph.</b> {esc(_summary(rep))}</div><div class='tiles'>{tile_html}</div>"
        f"<h2>Precision statement</h2><div class='callout'>{esc(precision)}</div>"
        f"<p class='meta'>Trained on labelled rows of weeks 1-9 ({v['n_train']}), tested on labelled rows of weeks 10-13 ({v['n_test']}).</p>"
        f"<h2>Escalation precision</h2>{_escalation(e)}"
        f"<div class='callout warn'><b>Safety recall.</b> {esc(_safety_text(sr, q))}</div>"
        f"<h2>Classification: where it is strong and weak</h2>{_classification(rep['classification'])}"
        f"<h2>Emerging-issue detection</h2>{_detection(rep['detection'])}"
        f"<h2>De-duplication (stretch)</h2><p>{dd['reports']:,} actionable reports became {dd['incidents']:,} incidents "
        f"({dd['reports_per_incident']} reports per incident). {dd['multi_report_incidents']:,} incidents have two or more reports, "
        f"{dd['cross_channel_incidents']:,} were seen in two or more channels and {dd['four_channel_incidents']:,} in all four. "
        f"{esc(dd['note'])}</p>"
        f"<h2>Week by week</h2>{_weeks(rep['weeks'])}"
        f"<h2>Escalation rule</h2><p>{esc(ESCALATION_RULE)}</p>"
        f"<h2>Limits you should know about</h2><ul>{lim}</ul></body></html>"
    )
