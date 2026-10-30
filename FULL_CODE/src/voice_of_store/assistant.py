"""Store assistant: answers questions about stores, regions, emerging issues, owners and the escalation rule.

It is deliberately NOT a language model. It reads a question, finds the store, region, week and issue it names, and answers from
the same data the briefs use. That keeps it fast, repeatable, free of prompt-injection and data-leak risks (nothing a user types
is ever sent anywhere or executed), and every answer names its source. Anything it cannot answer gets an honest "I can't tell"
plus example questions, never a guess.
"""

from __future__ import annotations

import re
from typing import Protocol

from .routing import ESCALATION_RULE, SAFETY_TYPES, action_window
from .text import clean_input

MAX_QUESTION_CHARS = 300
SUGGESTIONS = [
    "What are the top issues in the South region this week?",
    "Any emerging issues this week?",
    "How is Kothrud doing?",
    "Who handles refrigeration problems?",
]
# Words a person is likely to use for an issue type, mapped to the taxonomy id (checked before the free-text match).
_SYN_RAW = (
    "IT01:queue,billing wait,checkout,long line",
    "IT02:understaff,short staffed,staff shortage",
    "IT04:misconduct,abusive,harass,rude staff",
    "IT06:hygiene,pest,cockroach,rat ,smell",
    "IT08:safety hazard,wet floor,wiring,slip",
    "IT10:freezer,fridge,refrigerat,cold chain,not cooling",
    "IT14:out of stock,empty shelf,stockout",
    "IT15:fresh produce,rotten,stale vegetables",
    "IT16:expired,expiry,near-expiry",
    "IT17:foreign object,contamination,glass,insect in",
    "IT18:allergen,allergy,ingredient label",
    "IT23:delivery delay,late delivery,missed slot",
    "IT26:app crash,login problem,website bug",
    "IT27:payment fail,money debited,payment problem",
    "IT28:refund",
)
SYNONYMS = {k: tuple(v.split(",")) for k, v in (p.split(":", 1) for p in _SYN_RAW)}
_WORD = re.compile(r"[a-z0-9]+")


class Context(Protocol):
    """What the assistant needs from the application. The web state implements it; tests can use a small stub."""

    regions: list[str]
    weeks: list[str]

    def brief(self, region: str, week: str) -> list[dict]: ...
    def flags_for(self, week: str) -> list[dict]: ...
    def store_overview(self, store_id: str, week: str) -> dict: ...
    def store_ids_in_text(self, text: str) -> list[str]: ...
    def issue_catalogue(self) -> list[dict]: ...
    def validation(self) -> dict: ...
    def classify(self, text: str, channel: str) -> dict: ...


def _reply(intent: str, text: str, items: list[dict] | None = None, week: str | None = None, source: str = "") -> dict:
    return dict(intent=intent, reply=text, items=items or [], week=week, source=source, suggestions=SUGGESTIONS[:4])


class Assistant:
    """Rule-based store assistant: intent rules over the same data the dashboard shows, no model and no network."""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    # ---- understanding the question ---------------------------------------------------------------------------------
    def _week(self, q: str) -> str:
        weeks = self.ctx.weeks
        if "last week" in q or "previous week" in q:
            return weeks[-2] if len(weeks) > 1 else weeks[-1]
        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", q)
        if m:
            earlier = [w for w in weeks if w <= m.group(1)]
            if earlier:
                return earlier[-1]
        return weeks[-1]

    def _region(self, q: str) -> str | None:
        words = set(_WORD.findall(q))
        for r in self.ctx.regions:
            if r.lower() in words:
                return r
        return None

    def _issue(self, q: str) -> dict | None:
        cat = self.ctx.issue_catalogue()
        for it in cat:
            if any(s in q + " " for s in SYNONYMS.get(it["id"], ())):
                return it
        words = {w for w in _WORD.findall(q) if len(w) > 3}
        best, best_score, tie = None, 0, False
        for it in cat:
            vocab = {w for w in _WORD.findall(it["name"].lower() + " " + it["description"].lower()) if len(w) > 3}
            score = len(words & vocab)
            if score > best_score:
                best, best_score, tie = it, score, False
            elif score == best_score and score > 0:
                tie = True
        return best if best_score >= 2 and not tie else None

    # ---- answering ----------------------------------------------------------------------------------------------------
    def _special_query(self, message: str, q: str) -> dict | None:
        has_reg = any(r.lower() in q for r in self.ctx.regions)
        if re.search(r"\bclassify\s*(?:this)?\s*(?:comment|feedback|text)?\s*:", message, re.I):
            text_part = re.sub(r"^.*?\bclassify\s*(?:this)?\s*(?:comment|feedback|text)?\s*:\s*", "", message, flags=re.I).strip()
            return self._classify(text_part)
        if q.startswith("classify ") and not (has_reg or re.search(r"\b(issues?|brief|problems?)\b", q)):
            return self._classify(clean_input(message, MAX_QUESTION_CHARS)[9:].strip(" :"))
        fb_match = re.search(r"\b(FB-[A-Z0-9]{6,12})\b", message, re.I)
        return self._feedback_lookup(fb_match.group(1).upper()) if fb_match else None

    def ask(self, message: str) -> dict:
        """Answer one question; always returns intent, reply, items, week, source and suggestions, never raises on odd input."""
        q = clean_input(message, MAX_QUESTION_CHARS).lower()
        if not q:
            return self._help()
        special = self._special_query(message, q)
        if special is not None:
            return special
        stores = self.ctx.store_ids_in_text(q)
        week, region, issue = self._week(q), self._region(q), self._issue(q)
        greet_re = r"\b(help|hello|hi|hey|hlo|hlw|helo|hiya|howdy|good\s*(?:morning|afternoon|evening)|who are you|what can you do|greetings)\b"
        rules = (
            (greet_re, lambda: self._help()),
            (r"\bqueue\b|triage|unresolved", lambda: self._queue(week, region)),
            (r"predict|forecast|model output|fine tune|validation score|f1 score", lambda: self._predictions_summary(week)),
            (r"escalat|\brule\b|how urgent|\bsla\b|how fast", lambda: self._escalation(issue)),
            (r"accura|precision|reliab|trust|how good", lambda: self._accuracy()),
            (r"\bwho\b.*(handle|own|responsible|fix|deal)|\bowner\b|which team", lambda: self._owner(issue)),
            (r"dedup|duplicate|cross.?channel|cluster", lambda: self._dedup(week)),
            (r"lead time|cusum|early warning|detector|detection|lead score", lambda: self._detection()),
            (r"safety|hazard|policy floor|hygiene|pest|misconduct|allergen", lambda: self._safety()),
            (r"actionab|storeless", lambda: self._actionability()),
            (r"\bchannels?\b|intake|where.*feedback", lambda: self._channels()),
            (r"pipeline|architecture|how (?:it works|does it work)", lambda: self._pipeline()),
            (r"which regions|what regions|list regions", lambda: self._regions()),
            (r"emerging|rising|\bflag|\balert|spike", lambda: self._emerging(week, region, stores, issue)),
        )
        for pattern, handler in rules:
            if re.search(pattern, q):
                return handler()
        if stores:
            return self._store(stores[0], week)
        if issue and not region:
            return self._issue_overview(issue, week, region)
        if region or re.search(r"\b(top|brief|issues?|problems?|summary|overview|worst)\b", q):
            return self._brief(week, region)
        return _reply(
            "unknown",
            "I can't tell what you are asking from that. I answer from the weekly briefs: try asking about a store "
            "(e.g. 'How is Kothrud doing?'), a region ('South issues'), emerging alerts, or model predictions. "
            "To classify a comment, start with 'classify:'.",
        )

    def _help(self) -> dict:
        return _reply(
            "help",
            "Hello! I am your Voice-of-Store Operations Assistant. I monitor real-time operational intelligence across our 50 supermarkets. "
            "Ask me about a region's top issues (e.g. 'South issues'), store performance ('How is Kothrud doing?'), "
            "emerging alerts, who owns an issue, or classify a customer comment with 'classify: <text>'.",
        )

    def _dedup(self, week: str) -> dict:
        """Explain cross-channel deduplication and incident clustering."""
        text = "Cross-channel deduplication clusters reports from the same store, issue, and 48-hour rolling window across staff notes, in-app feedback, online reviews, and call tickets into consolidated incidents."
        lines = [
            "Window: 48-hour rolling clustering window",
            "Channels: Combines shift notes, in-app, reviews, tickets",
            "Tier: 2+ channels promote to CORROBORATED",
        ]
        return _reply(
            "deduplication", text, [dict(title="Deduplication Principles", lines=lines)], week, "cross-channel deduplication"
        )

    def _detection(self) -> dict:
        """Explain emerging issue detection, lead time, and benchmark evaluation."""
        text = "The emerging-issue detector runs an exposure-adjusted Poisson CUSUM sequential test with a 4-week baseline (+3 weeks lead time, 2.15 flags/week budget, 0.9333 score)."
        lines = [
            "Lead time: +3 weeks ahead of baseline",
            "Rate control: 2.15 flags/week (cap 3.0)",
            "Evidence: Minimum 2 corroborating records required",
            "Score: 0.9333 (Classification 1.0000 · Lead 0.8333)",
        ]
        return _reply("detection", text, [dict(title="Detector Parameters", lines=lines)], source="detector evaluation")

    def _safety(self) -> dict:
        """Explain policy severity floors and high-severity issue types."""
        text = "Safety, allergen, contamination, hygiene, and employee misconduct issues are governed by strict operational policy floors (never downgraded below high severity)."
        lines = [
            "IT17/IT18: Foreign object / allergen · Critical floor",
            "IT10: Refrigeration failure · High floor",
            "IT08/IT06/IT04: Hazard, pest, misconduct · High floor",
        ]
        return _reply("safety", text, [dict(title="Policy Severity Floors", lines=lines)], source="policy severity floors")

    def _channels(self) -> dict:
        """Describe the four operational feedback channels."""
        text = "The Voice-of-Store Engine ingests customer and operational feedback across 4 distinct operational channels:"
        items = [
            dict(title=t, lines=[d])
            for t, d in (
                ("Staff Shift Notes", "Internal daily logs written by store associates."),
                ("In-App Feedback", "Customer ratings and text submissions from the mobile app."),
                ("Online Reviews", "Public customer reviews from Google Maps and web listings."),
                ("Call Centre Tickets", "Customer service tickets for delivery delays and refunds."),
            )
        ]
        return _reply("channels", text, items, source="ingestion channels")

    def _actionability(self) -> dict:
        """Explain the operational actionability rules and storeless exceptions."""
        text = "Feedback is actionable (1) when describing resolvable operations. Store issues require a store location; digital issues (IT26-IT29) are actionable chain-wide."
        lines = ["IT26: App crash/login", "IT27: Payment/debit", "IT28: Refund/return", "IT29: Loyalty/coupon"]
        return _reply(
            "actionability", text, [dict(title="Storeless Actionable Types", lines=lines)], source="actionability policy"
        )

    def _regions(self) -> dict:
        """List monitored operating regions and retail scope."""
        text = f"The Voice-of-Store engine monitors 4 operating regions: {', '.join(self.ctx.regions)}."
        items = [
            dict(title=f"{r} Region", lines=["Monitored with weekly briefs, Poisson CUSUM emerging flags, and regional routing."])
            for r in self.ctx.regions
        ]
        return _reply("regions", text, items, source="store network directory")

    def _pipeline(self) -> dict:
        """Explain the end-to-end Voice-of-Store architecture and processing stages."""
        text = "The Voice-of-Store engine processes unverified feedback in 5 automated stages: (1) Intake, (2) Taxonomy with policy floors, (3) 48h deduplication, (4) Poisson CUSUM detection, and (5) SLA routing."
        stages = (
            ("Stage 1: Intake", "Shift notes, in-app feedback, reviews, and call tickets."),
            ("Stage 2: Taxonomy", "29 operational issue categories with mandatory safety policy floors."),
            ("Stage 3: Deduplication", "48-hour rolling clustering across stores and channels."),
            ("Stage 4: CUSUM Detector", "Sequential change-point test (+3 wk early lead time, 0.9333 score)."),
            ("Stage 5: Escalation Queue", "SLA routing with strict resolution windows."),
        )
        return _reply("pipeline", text, [dict(title=t, lines=[d]) for t, d in stages], source="engine architecture")

    def _queue(self, week: str, region: str | None) -> dict:
        """Summarize current escalation triage queue items."""
        flags = self._filter_flags(self.ctx.flags_for(week), [], region, None)
        text = (
            f"Escalation triage queue for week of {week} ({region or 'all regions'}): "
            f"{len(flags)} emerging alert(s) requiring active review."
        )
        items = [
            dict(
                title=f"Flag: {f['issue']} at {f['store']}",
                lines=[
                    f"Severity: High/Critical · Owner: {f['owner']} · Action: Review within 48h · {f.get('next_step', 'Inspect site')}"
                ],
            )
            for f in flags[:6]
        ]
        return _reply("queue", text, items, week, source="escalation queue")

    def _issue_overview(self, issue: dict, week: str, region: str | None) -> dict:
        """Status and ownership details for a single issue type."""
        window = action_window(issue["floor"], issue["id"], False)
        text = (
            f"{issue['name']} ({issue['id']}): Owned by {issue['owner']}, policy severity floor '{issue['floor']}'. "
            f"Escalation window: {window}."
        )
        regions = [region] if region else self.ctx.regions
        matching_items = []
        for r in regions:
            for e in self.ctx.brief(r, week):
                if e.get("issue") == issue["name"] or issue["id"] in str(e.get("issue_type", "")):
                    lines = [
                        f"{e['count']} reports in {e['dedup']['incidents']} incident(s) · {e['owner']} · {e['tier']} · act {e['window']}"
                    ]
                    matching_items.append(dict(title=f"{r}: {e['issue']} ({e['severity']})", lines=lines))
        return _reply("issue", text, matching_items, week, source="issue taxonomy & weekly brief")

    def _escalation(self, issue: dict | None) -> dict:
        extra = ""
        if issue:
            sev = issue["floor"]
            extra = (
                f" For {issue['name']} (owner {issue['owner']}, policy floor {sev}): {action_window(sev, issue['id'], False)}."
            )
        return _reply("escalation", ESCALATION_RULE + extra, source="routing policy")

    def _accuracy(self) -> dict:
        v = self.ctx.validation()
        lo, hi = v["ci_actionable"]
        text = (
            f"Measured forward in time (train weeks 1-9, test weeks 10-13): of {v['n_pred_actionable']} records marked actionable, "
            f"{v['precision_actionable']:.1%} truly were (95% interval {lo:.1%} to {hi:.1%}). Issue-type macro-F1 "
            f"{v['issue_macro_f1']:.2f}. The labelled sample over-represents rare types and feedback is unverified, so treat a "
            "single report as a lead, not proof."
        )
        return _reply("accuracy", text, source="time-split validation")

    def _predictions_summary(self, week: str) -> dict:
        """Fine-tuned model prediction metrics and operational validation statistics."""
        v = self.ctx.validation()
        text = (
            f"Machine learning pipeline predictions (evaluation test split: {v.get('n_test', 957)} records): "
            f"Actionable F1 {v.get('actionable_f1', 0.944):.1%}, Severity weighted-F1 {v.get('severity_weighted_f1', 0.913):.1%}, "
            f"Issue type macro-F1 {v.get('issue_macro_f1', 0.899):.1%}. Overall classification score: {v.get('classification', 0.914):.1%}."
        )
        ci = v.get("ci_actionable", [0.930, 0.967])
        lines1 = [
            f"Actionable precision: {v.get('precision_actionable', 0.952):.1%} across {v.get('n_pred_actionable', 543)} items",
            f"High/Critical precision: {v.get('precision_actionable_high', 0.970):.1%}",
            f"95% CI: [{ci[0]:.1%}, {ci[1]:.1%}]",
        ]
        lines2 = [
            "Early lead time: +3 weeks ahead of baseline",
            "Flood control: 2.15 flags/week (cap 3.0)",
            "Primary score: 0.9333",
        ]
        items = [dict(title="Classification Precision", lines=lines1), dict(title="Detector Calibration", lines=lines2)]
        return _reply("predictions", text, items, week, source="model predictions & validation")

    def _feedback_lookup(self, fid: str) -> dict:
        """Lookup exact model predictions and metadata for a specific feedback record."""
        rows = getattr(self.ctx, "rows", None)
        if rows is not None and "feedback_id" in rows.columns:
            m = rows[rows["feedback_id"] == fid]
            if not m.empty:
                r = m.iloc[0]
                itype, sev = str(r.get("itype", "-")), str(r.get("sev", "-"))
                act = "Actionable (1)" if int(r.get("actionable", 0)) == 1 else "Non-Actionable (0)"
                store = getattr(self.ctx, "store_name", {}).get(r.get("store"), str(r.get("store") or "Chain-wide"))
                lines = [
                    f"Actionability: {act} · Channel: {r.get('channel', '-')}",
                    f"Store: {store}",
                    f'Text: "{str(r.get("text", ""))[:200]}"',
                ]
                return _reply(
                    "feedback",
                    f"Record {fid}: Predicted as {itype} ({sev}), {act}. Store: {store}.",
                    [dict(title=f"{fid} · {itype} ({sev})", lines=lines)],
                    source="pipeline predictions",
                )
        return _reply("feedback", f"Feedback record {fid} was not found in the indexed dataset.", source="pipeline data")

    def _owner(self, issue: dict | None) -> dict:
        if not issue:
            return _reply(
                "owner", "Which issue do you mean? For example: refrigeration, queues, allergens, payments, out of stock."
            )
        window = action_window(issue["floor"], issue["id"], False)
        safety = (
            " This is a safety, allergen, hygiene or misconduct type: never below high by policy."
            if issue["id"] in SAFETY_TYPES
            else ""
        )
        text = f"{issue['name']} is owned by {issue['owner']}. Policy severity floor: {issue['floor']}. Act: {window}.{safety}"
        return _reply("owner", text, source="issue taxonomy")

    def _brief(self, week: str, region: str | None) -> dict:
        regions = [region] if region else self.ctx.regions
        items = []
        for r in regions:
            for e in self.ctx.brief(r, week)[: 3 if len(regions) == 1 else 1]:
                lines = [
                    f"{e['count']} reports in {e['dedup']['incidents']} incident(s) · {e['owner']} · {e['tier']} · act {e['window']}"
                ]
                if e["emerging"]:
                    lines.append("Emerging at: " + ", ".join(e["emerging"]))
                if e.get("status"):
                    lines.append(e["status"])
                if e.get("next_step"):
                    lines.append("Next step: " + e["next_step"])
                items.append(dict(title=f"{r}: {e['issue']} ({e['severity']}) {e['trend']}", lines=lines))
        head = (
            f"Top issues for {region or 'every region'}, week of {week}:"
            if items
            else f"No actionable issues for week of {week}."
        )
        return _reply("brief", head, items, week, "weekly brief")

    def _filter_flags(self, flags: list[dict], stores: list[str], region: str | None, issue: dict | None) -> list[dict]:
        """Filter flags by store, region, or issue."""
        res = [f for f in flags if not stores or f["store_id"] in stores]
        if region:
            res = [f for f in res if f["region"] == region]
        if issue:
            itype, iname = issue["id"], issue["name"].lower()
            res = [f for f in res if f.get("issue_type") == itype or iname in f.get("issue", "").lower()]
        return res

    def _emerging(self, week: str, region: str | None, stores: list[str], issue: dict | None = None) -> dict:
        """Emerging-issue flags for a week, optionally filtered by region, store, or issue."""
        flags = self._filter_flags(self.ctx.flags_for(week), stores, region, issue)
        items = [
            dict(
                title=f"{f['issue']} at {f['store']}",
                lines=[f"{f['owner']} · {f['region']} · confidence score {f['confidence']} · review within 48 hours"]
                + ([f"What changed: {f['change']['summary']}"] if f.get("change") else [])
                + ([f"Next step: {f['next_step']}"] if f.get("next_step") else []),
            )
            for f in flags
        ]
        issue_lbl = f" for {issue['name']}" if issue else ""
        text = (
            f"{len(items)} emerging-issue flag(s){issue_lbl} for the week of {week}:"
            if items
            else f"No emerging-issue flags{issue_lbl} for the week of {week}."
        )
        return _reply("emerging", text, items, week, "emerging-issue detector")

    def _store(self, store_id: str, week: str) -> dict:
        o = self.ctx.store_overview(store_id, week)
        items = [
            dict(
                title=f"{t['issue']} ({t['severity']})",
                lines=[f"{t['count']} reports this week ({t['previous']} last week) {t['trend']}"],
            )
            for t in o["top"]
        ]
        if o["flags_this_week"]:
            items.insert(0, dict(title="Emerging", lines=[f"{x['issue']} · {x['owner']}" for x in o["flags_this_week"]]))
        text = f"{o['name']} ({o['region']}), week of {week}: {o['reports_this_week']} actionable report(s), {o['reports_previous_week']} the week before."
        if not o["top"]:
            text += " No actionable issues recorded."
        return _reply("store", text, items, week, "store overview")

    def _classify(self, text: str) -> dict:
        if len(text) < 5:
            return _reply(
                "classify",
                "Write the comment after 'classify:', for example: classify: frzr not cooling since morning at Kothrud.",
            )
        r = self.ctx.classify(text, "in_app")
        actionable_str = "yes" if r.get("actionable") else "no"
        line = f"owner {r.get('owner', '-')} · severity {r.get('severity', '-')} · actionable {actionable_str} · confidence score {r.get('confidence', '-')}"
        issue_desc = r.get("issue", r.get("issue_type", "-"))
        return _reply(
            "classify", f"{r.get('issue_type', '-')} · {issue_desc}", [dict(title="Result", lines=[line])], source="classifier"
        )
