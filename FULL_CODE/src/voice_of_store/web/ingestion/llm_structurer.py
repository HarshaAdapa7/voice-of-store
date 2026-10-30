"""LLM document structurer using Google AI Studio Gemini API.

Converts unstructured feedback text chunks into candidate structured feedback records
following the target schema (feedback_id, channel, created_at, store_id, text).
"""

from __future__ import annotations

import json
import logging
import os
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .parser import DocumentChunk

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a specialized retail feedback extraction system for Saffron Retail stores.
Your task is to parse unstructured feedback documents (customer complaints, manager notes, call logs, reviews)
and extract distinct feedback records into a strict JSON structure.

ALLOWED CHANNELS:
- "online_review" (Google reviews, web reviews, ratings)
- "in_app" (App feedback, digital ordering complaints, app delivery issues)
- "staff_shift_note" (Internal store logs, duty manager handovers, maintenance records)
- "call_centre_ticket" (Customer service phone calls, agent logs, helpline transcripts)

STRICT ACCURACY RULES:
1. Do NOT invent dates: If an explicit date or timestamp is mentioned (e.g., 'YYYY-MM-DD', 'June 14'), format it as 'YYYY-MM-DD HH:MM:SS'. If no date is mentioned, output null.
2. Do NOT invent stores: If a store name, locality, or store ID is mentioned, put it in store_mention. If none is mentioned, output null.
3. Extract each distinct complaint, remark, or incident as a separate record.
4. Clean text: preserve verbatim complaints without embellishment or hallucination.

RETURN ONLY VALID JSON matching this schema:
{
  "records": [
    {
      "source_reference": "exact chunk reference",
      "channel": "online_review" | "in_app" | "staff_shift_note" | "call_centre_ticket",
      "created_at": "YYYY-MM-DD HH:MM:SS" or null,
      "store_mention": "store name or locality" or null,
      "text": "verbatim feedback text excerpt",
      "confidence": "high" | "medium" | "low"
    }
  ]
}
"""


class LLMStructurer:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        """Initialize structurer with configured Gemini models."""
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        primary = model or os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        candidates = [primary, "gemini-2.0-flash", "gemini-1.5-flash"]
        seen: set[str] = set()
        self.models: list[str] = []
        for m in candidates:
            if m not in seen:
                seen.add(m)
                self.models.append(m)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 10)

    @staticmethod
    def _classify_raw_channel(raw_chan: str) -> str:
        """Map raw channel text to canonical channel identifier."""
        if "review" in raw_chan:
            return "online_review"
        if "app" in raw_chan:
            return "in_app"
        if any(k in raw_chan for k in ("shift", "handover", "staff", "note", "duty")):
            return "staff_shift_note"
        if any(k in raw_chan for k in ("call", "ticket", "helpline", "centre", "center")):
            return "call_centre_ticket"
        return "in_app"

    def _heuristic_extract(self, raw_text: str, source_ref: str, default_date: str | None = None) -> list[dict]:
        """Deterministic pattern extractor when Gemini API is unconfigured or unreachable."""
        records: list[dict] = []
        blocks = re.split(r"\n(?=(?:[^\n]+:.*?\n)?Date:\s*\d{4}-\d{2}-\d{2})", raw_text)
        for b in blocks:
            b = b.strip()
            if not b:
                continue
            m_date = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?)", b)
            m_chan = re.search(r"Channel:\s*([^|\n]+)", b)
            m_store = re.search(r"Store:\s*([^|\n]+)", b)
            chan = self._classify_raw_channel(m_chan.group(1).strip().lower() if m_chan else "")
            lines = [
                line.strip()
                for line in b.splitlines()
                if not line.startswith("Date:")
                and not ("|" in line and "Channel:" in line)
                and not line.startswith("Monthly feedback")
                and not line.startswith("Saffron Retail Chain")
            ]
            text = " ".join(lines).strip()
            if text:
                records.append(
                    {
                        "created_at": m_date.group(1).strip() if m_date else (default_date or ""),
                        "channel": chan,
                        "store_mention": m_store.group(1).strip() if m_store else "",
                        "text": text,
                        "source_reference": source_ref,
                    }
                )
        return records

    def structure_chunk(
        self,
        chunk: DocumentChunk,
        store_names_hint: list[str] | None = None,
        default_date: str | None = None,
    ) -> list[dict]:
        """Call Gemini or fallback heuristic parser to convert chunk into structured records."""
        if not self.enabled:
            return self._heuristic_extract(chunk.raw_text, chunk.source_reference, default_date)

        hint_text = ""
        if store_names_hint:
            sample_stores = ", ".join(store_names_hint[:30])
            hint_text = f"\nKnown store names / localities in chain: {sample_stores}\n"
        if default_date:
            hint_text += f"\nDocument fallback date context (use only if no specific date is given in line): {default_date}\n"

        user_content = (
            f"Chunk Reference: {chunk.source_reference}\n"
            f"{hint_text}\n"
            f"--- DOCUMENT TEXT BEGIN ---\n"
            f"{chunk.raw_text}\n"
            f"--- DOCUMENT TEXT END ---\n"
            f"Extract all distinct feedback items from this text into JSON."
        )

        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": user_content}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1,
            },
        }

        try:
            return self._extract_with_fallback(body, chunk.source_reference)
        except Exception as exc:
            log.warning("Gemini extraction error (%s); falling back to heuristic parsing", exc)
            return self._heuristic_extract(chunk.raw_text, chunk.source_reference, default_date)

    def _extract_with_fallback(self, body: dict, source_ref: str) -> list[dict]:
        """Try candidate Gemini models sequentially."""
        last_err: Exception | None = None
        for model_name in self.models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
            req = Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(req, timeout=30) as resp:  # noqa: S310
                    data = json.loads(resp.read().decode("utf-8"))
                    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    parsed = json.loads(text)
                    records = parsed.get("records", [])
                    for r in records:
                        if not r.get("source_reference"):
                            r["source_reference"] = source_ref
                    return records
            except HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                log.warning("Gemini model %s failed (%s): %s", model_name, e.code, err_body[:200])
                last_err = e
            except Exception as e:
                log.warning("Gemini model %s request error: %s", model_name, e)
                last_err = e

        raise RuntimeError(f"Failed to extract structured records: {last_err}")
