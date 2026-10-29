"""Routing: owner function, severity and the written escalation rule."""

from __future__ import annotations

import pandas as pd

SAFETY_TYPES = ("IT04", "IT06", "IT08", "IT10", "IT16", "IT17", "IT18")  # policy floor 'high' in the taxonomy

ESCALATION_RULE = (
    "Escalation rule. (1) Critical severity, or any safety/allergen/food-safety/hygiene/misconduct type (policy: at least "
    "high regardless of volume): open a check with the owner the same day; a single report is shown as UNVERIFIED until a "
    "second independent report (different channel or different text) corroborates it. (2) An emerging-issue flag "
    "(small but rising at one store): owner reviews within 48 hours. (3) Anything else is ranked in the weekly brief "
    "and handled in the owner's normal cycle. Feedback is unverified: no report is treated as proof on its own."
)


def owner_of(issue_type: str, taxonomy: pd.DataFrame) -> str:
    """Owning function from the supplied taxonomy."""
    return str(taxonomy.loc[issue_type, "owner_function"])


def action_window(severity: str, issue_type: str, emerging: bool) -> str:
    """How soon the owner should act: same day for critical or safety types, 48 hours for high or emerging, else weekly."""
    if severity == "critical" or issue_type in SAFETY_TYPES:
        return "same day"
    if emerging or severity == "high":
        return "within 48 hours"
    return "weekly cycle"


# Recommended first step per safety type; a verification step always comes first because feedback is unverified.
_SAFETY_STEPS = {
    "IT04": "Store manager and HR call the store today; collect the staff roster and any CCTV or bill records; HR opens a conduct review if the facts hold.",
    "IT06": "Store manager inspects the area today and sends dated photos; pest-control or deep-clean the same day if confirmed.",
    "IT08": "Store manager checks and cordons off the hazard today; log the fix and the time it was made safe.",
    "IT10": "Store manager reads the freezer or chiller temperature log today; move or discard stock held above the safe limit; engineer visit.",
    "IT16": "Store team pulls all stock of the named product and checks expiry dates today; remove anything expired or near expiry.",
    "IT17": "Merchandising quarantines the product batch, keeps the item if the customer returns it, and starts a supplier check.",
    "IT18": "Merchandising checks the label against the product specification today; pull the product if the allergen declaration is wrong.",
}
_OWNER_STEPS = {
    "Store Ops": "Store Ops: ask the store manager to confirm and fix, then reply with what changed.",
    "Supply Chain": "Supply Chain: check stock and replenishment or delivery status for the named stores and reset the order.",
    "Merchandising": "Merchandising: review the product, price or offer set-up and correct it at the source.",
    "Digital": "Digital: reproduce the fault, check the error logs for the period and open a ticket with the evidence.",
    "HR": "HR: speak to the store manager about the staffing or conduct concern and agree a follow-up.",
}


def next_step(issue_type: str, owner: str, emerging: bool) -> str:
    """One recommended next step for the owner (the supplied taxonomy's owner decides who)."""
    step = _SAFETY_STEPS.get(issue_type) or _OWNER_STEPS.get(owner, "Owner: review the evidence and confirm with the store.")
    if emerging and issue_type not in _SAFETY_STEPS:
        step += " It is rising at one store, so start there."
    return step


def verification_status(issue_type: str, tier: str) -> str:
    """Words that keep an allegation from being read as an established fact."""
    kind = "serious allegation" if issue_type in SAFETY_TYPES else "report"
    if tier == "UNVERIFIED":
        return f"Unverified {kind}: a single source, not confirmed."
    if tier == "CORROBORATED":
        return f"Corroborated {kind}: several independent reports, still not a verified incident until the owner confirms."
    return f"Possible systemic {kind}: reported at 3 or more stores, still to be verified by the owner."
