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


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
_LONGNUM = re.compile(r"(?<!\d)\d{9,}(?!\d)")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def redact(text: str) -> str:
    """Defence in depth for anything shown to a person: mask emails, phone numbers and long digit runs."""
    t = _EMAIL.sub("[email]", str(text))
    t = _PHONE.sub("[phone]", t)
    return _LONGNUM.sub("[number]", t)


def clean_input(text: str, max_len: int) -> str:
    """Strip control characters, collapse whitespace and cap the length (for text typed into the web app)."""
    t = _CTRL.sub(" ", str(text))
    return _WS.sub(" ", t).strip()[:max_len]


def csv_safe(value: object) -> str:
    """Neutralise spreadsheet formula injection: a cell starting with = + - @ tab or CR is prefixed with an apostrophe."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
