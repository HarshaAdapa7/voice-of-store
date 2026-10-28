"""Weekly one-page brief per region: top 5 issues, evidence quotes, affected stores, trend arrow, owner, severity."""

from __future__ import annotations

import html

import pandas as pd

from . import config as C
from .dedup import summarise
from .io import monday_of
from .routing import ESCALATION_RULE, SAFETY_TYPES, action_window, owner_of
from .text import redact

TIER_ORDER = {"POSSIBLE SYSTEMIC": 2, "CORROBORATED": 1, "UNVERIFIED": 0}


def _tier(g: pd.DataFrame) -> str:
    if g["store"].nunique() >= 3:
        return "POSSIBLE SYSTEMIC"
    if g["channel"].nunique() >= 2 and len(g) >= 2:
        return "CORROBORATED"
    if len(g) >= 3 and g["text"].nunique() >= 3:
        return "CORROBORATED"
    return "UNVERIFIED"


def trend_arrow(this_n: float, prev_n: float) -> str:
    if this_n - prev_n >= 2 and this_n >= 1.25 * prev_n:
        return "↑"
    if prev_n - this_n >= 2 and this_n <= 0.75 * prev_n:
        return "↓"
    return "→"


def severity_rank(itype: str, severities: pd.Series) -> int:
    """Safety types keep the worst report (policy: never averaged away); other types use the 75th percentile so one
    outlier report does not set the severity of a whole group."""
    ranks = sorted(C.SEV_RANK[s] for s in severities)
    if itype in SAFETY_TYPES or len(ranks) == 1:
        return ranks[-1]
    return ranks[int(0.75 * (len(ranks) - 1))]


def _issue_entry(itype: str, g: pd.DataFrame, prev_count: int, emerging: list[str], names: dict, taxonomy: pd.DataFrame) -> dict:
    sev_rank = severity_rank(itype, g["severity"])
    sev = C.SEVERITIES[sev_rank]
    tier = _tier(g)
    per_store = g.groupby("store").size().sort_values(ascending=False)
    quotes = g.sort_values(["conf", "feedback_id"], ascending=[False, True]).drop_duplicates("text").head(3)
    return dict(
        issue_type=itype,
        issue=str(taxonomy.loc[itype, "issue_type"]),
        owner=owner_of(itype, taxonomy),
        severity=sev,
        tier=tier,
        count=len(g),
        channels=g["channel"].nunique(),
        n_stores=g["store"].nunique(),
        stores=[(names[s], int(n)) for s, n in per_store.head(4).items()],
        trend=trend_arrow(len(g), prev_count),
        prev_count=prev_count,
        emerging=[names[s] for s in emerging],
        window=action_window(sev, itype, bool(emerging)),
        quotes=[(r.channel, redact(r.text[:220])) for r in quotes.itertuples()],
        dedup=summarise(g),
        key=(-sev_rank, -TIER_ORDER[tier], -(len(g) + 3 * len(emerging)), -g["store"].nunique(), itype),
    )


def build_region_week(
    rows: pd.DataFrame, flags: pd.DataFrame, stores: pd.DataFrame, taxonomy: pd.DataFrame, region: str, week: str
) -> list[dict]:
    """Top-5 issue entries for one region and week. `rows` needs store (resolved), itype, severity, actionable, week,
    text, channel, conf, created_at."""
    ids = set(stores[stores["region"] == region]["store_id"])
    names = dict(zip(stores["store_id"], stores["store_name"]))
    prev_week = str((monday_of(week) - pd.Timedelta(days=7)).date())
    base = rows[(rows["actionable"] == 1) & ~rows["itype"].isin(C.NON_ISSUE) & rows["store"].isin(ids)]
    cur, prev = base[base["week"] == week], base[base["week"] == prev_week]
    fl = flags[(flags["as_of_week_start"] == week) & flags["store_id"].isin(ids)]
    flagged = {(r.store_id, r.issue_type_id) for r in fl.itertuples()}
    prev_counts = prev.groupby("itype").size()
    entries = [
        _issue_entry(itype, g, int(prev_counts.get(itype, 0)), [s for (s, t) in sorted(flagged) if t == itype], names, taxonomy)
        for itype, g in cur.groupby("itype")
    ]
    entries.sort(key=lambda e: e["key"])
    return entries[:5]


PAGE_CSS = """
:root{--bg:#fff;--fg:#1d2330;--mut:#5b6475;--bd:#d9dde5;--hi:#b42318;--md:#b54708;--lo:#475467}
@media(prefers-color-scheme:dark){:root{--bg:#12151c;--fg:#e8ebf2;--mut:#9aa3b5;--bd:#2a3040;--hi:#f97066;--md:#fdb022;--lo:#98a2b3}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0 auto;max-width:860px;padding:16px}
h1{font-size:20px;margin:0 0 2px}h2{font-size:15px;margin:0 0 4px}.sub,.meta{color:var(--mut)}.meta{font-size:12.5px}
.card{border:1px solid var(--bd);border-left:4px solid var(--lo);border-radius:6px;padding:8px 12px;margin:8px 0;break-inside:avoid}
.sev-critical,.sev-high{border-left-color:var(--hi)}.sev-medium{border-left-color:var(--md)}
ul{margin:4px 0 0;padding-left:18px}li{margin:2px 0}.ch{color:var(--mut);font-size:11.5px;text-transform:uppercase}
.em{color:var(--hi);font-weight:600;font-size:12.5px}.trend{float:right}footer{color:var(--mut);font-size:11.5px;margin-top:10px}
@media print{body{padding:0}}
"""


def _card_html(i: int, e: dict) -> str:
    esc = html.escape
    quotes = "".join(f"<li><span class='ch'>{esc(c)}</span> “{esc(q)}”</li>" for c, q in e["quotes"])
    stores = ", ".join(f"{esc(n)} ({c})" for n, c in e["stores"])
    emerg = f"<div class='em'>Emerging at: {esc(', '.join(e['emerging']))}</div>" if e["emerging"] else ""
    d = e["dedup"]
    return (
        f"<section class='card sev-{esc(e['severity'])}'><h2>{i}. {esc(e['issue'])} <span class='trend'>{esc(e['trend'])}</span></h2>"
        f"<div class='meta'><b>{esc(e['owner'])}</b> · severity <b>{esc(e['severity'])}</b> · {esc(e['tier'])} · act: {esc(e['window'])}</div>"
        f"<div class='meta'>{e['count']} reports in {d['incidents']} incident(s) ({d['cross_channel']} seen in 2+ channels) "
        f"({e['prev_count']} last week) · {e['channels']} channel(s) · {e['n_stores']} store(s): {stores}</div>"
        f"{emerg}<ul>{quotes}</ul></section>"
    )


def render_html(region: str, week: str, entries: list[dict], n_rows: int) -> str:
    """One printable page. Every value is escaped; the page carries inline CSS only and no script."""
    esc = html.escape
    end = (monday_of(week) + pd.Timedelta(days=6)).date()
    body = "".join(_card_html(i, e) for i, e in enumerate(entries, 1)) or "<p>No actionable issues this week.</p>"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(region)} brief {esc(week)}</title><style>{PAGE_CSS}</style></head><body>"
        f"<h1>{esc(region)} region · week of {esc(week)} to {end}</h1>"
        '<div class="sub">Top 5 actionable issues, ranked by severity, then evidence strength, then number of stores. '
        "Arrow = report count vs previous week (up if it grew by at least 25% and 2 reports).</div>"
        f"{body}<footer>{esc(ESCALATION_RULE)}<br>Based on {n_rows} feedback records up to the week's Sunday. "
        "Feedback is unverified; UNVERIFIED means a single source.</footer></body></html>"
    )
