"""Text preparation. Light on purpose: the char n-grams absorb typos, SMS spellings and transliteration."""
from __future__ import annotations

import re

import pandas as pd

_URL = re.compile(r"https?://\S+|www\.\S+")
_WS = re.compile(r"\s+")
_DIGITS = re.compile(r"\d{4,}")


def normalise(text: str) -> str:
    t = str(text).lower()
    t = _URL.sub(" url ", t)
    t = _DIGITS.sub(" num ", t)  # redacted ids / phone numbers carry no signal
    return _WS.sub(" ", t).strip()


def model_input(df: pd.DataFrame) -> pd.Series:
    """Channel prefix + normalised text: channels write differently and cover different issues."""
    return df["channel"].astype(str) + " || " + df["text"].map(normalise)
