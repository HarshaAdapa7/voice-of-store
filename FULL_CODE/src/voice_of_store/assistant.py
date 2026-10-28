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
    "What is the escalation rule?",
    "How accurate is this?",
]
# Words a person is likely to use for an issue type, mapped to the taxonomy id (checked before the free-text match).
SYNONYMS = {
    "IT01": ("queue", "billing wait", "checkout", "long line"),
    "IT02": ("understaff", "short staffed", "staff shortage"),
    "IT04": ("misconduct", "abusive", "harass", "rude staff"),
    "IT06": ("hygiene", "pest", "cockroach", "rat ", "smell"),
    "IT08": ("safety hazard", "wet floor", "wiring", "slip"),
    "IT10": ("freezer", "fridge", "refrigerat", "cold chain", "cold-chain", "not cooling"),
    "IT14": ("out of stock", "empty shelf", "empty shelves", "stockout"),
    "IT15": ("fresh produce", "rotten", "stale vegetables"),
    "IT16": ("expired", "expiry", "near-expiry"),
    "IT17": ("foreign object", "contamination", "glass", "insect in"),
    "IT18": ("allergen", "allergy", "ingredient label"),
    "IT23": ("delivery delay", "late delivery", "missed slot"),
    "IT26": ("app crash", "login problem", "website bug"),
    "IT27": ("payment fail", "money debited", "payment problem"),
    "IT28": ("refund",),
}
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
    def ask(self, message: str) -> dict:
        q = clean_input(message, MAX_QUESTION_CHARS).lower()
        if not q:
            return _reply("help", "Ask me about a store, a region, emerging issues, who owns an issue, or the escalation rule.")
        if q.startswith("classify:") or q.startswith("classify "):
            return self._classify(clean_input(message, MAX_QUESTION_CHARS)[9:].strip(" :"))
        stores = self.ctx.store_ids_in_text(q)
        week, region, issue = self._week(q), self._region(q), self._issue(q)
        rules = (
            (r"\b(help|hello|hi|hey|what can you do)\b", lambda: self._help()),
            (r"escalat|\brule\b|how urgent|\bsla\b|how fast", lambda: self._escalation(issue)),
            (r"accura|precision|reliab|trust|how good", lambda: self._accuracy()),
            (r"\bwho\b.*(handle|own|responsible|fix|deal)|\bowner\b|which team", lambda: self._owner(issue)),
            (r"emerging|rising|early warning|\bflag|\balert|spike", lambda: self._emerging(week, region, stores)),
        )
        for pattern, handler in rules:
            if re.search(pattern, q):
                return handler()
        if stores:
            return self._store(stores[0], week)
        if region or re.search(r"\b(top|brief|issues?|problems?|summary|overview|worst)\b", q):
            return self._brief(week, region)
        return _reply(
            "unknown",
            "I can't tell what you are asking from that. I answer from the weekly briefs: try one of the questions below. "
            "To classify a comment, start with 'classify:'.",
        )

    def _help(self) -> dict:
        return _reply(
            "help",
            "I can show a store's status, a region's top issues, emerging-issue flags, who owns an issue type, the escalation "
            "rule and how accurate the numbers are. I answer from the weekly briefs only and cite the week.",
        )

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
            entries = self.ctx.brief(r, week)[: 3 if len(regions) == 1 else 1]
            for e in entries:
                lines = [
                    f"{e['count']} reports in {e['dedup']['incidents']} incident(s) · {e['owner']} · {e['tier']} · act {e['window']}"
                ]
                if e["emerging"]:
                    lines.append("Emerging at: " + ", ".join(e["emerging"]))
                items.append(dict(title=f"{r}: {e['issue']} ({e['severity']}) {e['trend']}", lines=lines))
        head = (
            f"Top issues for {region or 'every region'}, week of {week}:"
            if items
            else f"No actionable issues for week of {week}."
        )
        return _reply("brief", head, items, week, "weekly brief")

    def _emerging(self, week: str, region: str | None, stores: list[str]) -> dict:
        flags = self.ctx.flags_for(week)
        if stores:
            flags = [f for f in flags if f["store_id"] in stores]
        if region:
            flags = [f for f in flags if f["region"] == region]
        items = [
            dict(
                title=f"{f['issue']} at {f['store']}",
                lines=[f"{f['owner']} · {f['region']} · confidence score {f['confidence']} · review within 48 hours"],
            )
            for f in flags
        ]
        text = (
            f"{len(items)} emerging-issue flag(s) for the week of {week}:"
            if items
            else f"No emerging-issue flags for the week of {week}."
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
        text = (
            f"{o['name']} ({o['region']}), week of {week}: {o['reports_this_week']} actionable report(s), "
            f"{o['reports_previous_week']} the week before."
        )
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
        line = f"owner {r['owner']} · severity {r['severity']} · actionable {'yes' if r['actionable'] else 'no'} · confidence score {r['confidence']}"
        return _reply("classify", f"{r['issue_type']} · {r['issue']}", [dict(title="Result", lines=[line])], None, "classifier")
