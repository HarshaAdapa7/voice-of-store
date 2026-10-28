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
    return str(taxonomy.loc[issue_type, "owner_function"])


def action_window(severity: str, issue_type: str, emerging: bool) -> str:
    if severity == "critical" or issue_type in SAFETY_TYPES:
        return "same day"
    if emerging or severity == "high":
        return "within 48 hours"
    return "weekly cycle"
