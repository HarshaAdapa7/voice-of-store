"""Optional Gemini paraphrasing for deterministic assistant results; never sends the original question or feedback."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

MAX_OUTPUT_CHARS = 1200
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)")


class GeminiError(RuntimeError):
    """A safe, user-facing Gemini request failure without provider details or credentials."""


class GeminiAssistant:
    """Turn an already-computed local answer into a short, clearly labeled summary."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        opener: Callable = urlopen,
        timeout: float = 12.0,
    ):
        self._api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        self._opener = opener
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    @staticmethod
    def _safe_result(result: Mapping, store_names: tuple[str, ...]) -> dict:
        """Pass only the deterministic response, with identifiers and contact details redacted."""

        def clean(value: object) -> str:
            text = str(value)
            for name in sorted(store_names, key=len, reverse=True):
                if name:
                    text = re.sub(re.escape(name), "[store]", text, flags=re.IGNORECASE)
            return _PHONE.sub("[phone]", _EMAIL.sub("[email]", text))[:500]

        safe = {
            key: clean(result[key])
            for key in ("intent", "reply", "week", "source")
            if result.get(key) is not None
        }
        safe_items = []
        for item in result.get("items", [])[:8]:
            if not isinstance(item, Mapping):
                continue
            safe_items.append(
                {
                    "title": clean(item.get("title", "")),
                    "lines": [clean(line) for line in item.get("lines", [])[:8]],
                }
            )
        safe["items"] = safe_items
        return safe

    def _call_model(self, model: str, body: dict) -> str | None:
        """Call one Gemini model; return text or None on 404 (model not found)."""
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(model, safe='')}:generateContent"
        )
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-goog-api-key": self._api_key},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
            candidates = payload.get("candidates") or []
            if not candidates:
                return None
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts if isinstance(p.get("text"), str)).strip()
            return text if text else None
        except HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (400, 401, 403):
                raise GeminiError("Gemini API key is invalid or lacks permission") from exc
            if exc.code == 429:
                raise GeminiError("Gemini API rate limit or quota exceeded") from exc
            raise GeminiError("Gemini summary is unavailable") from exc
        except (URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise GeminiError("Gemini summary is unavailable") from exc
        except Exception as exc:
            raise GeminiError("Gemini summary is unavailable") from exc

    def summarize(self, result: Mapping, store_names: tuple[str, ...] = ()) -> str:
        """Summarize local facts. The caller's question and raw feedback are never accepted by this API."""
        if not self.enabled:
            raise GeminiError("Gemini mode is not configured")

        facts = self._safe_result(result, store_names)
        body = {
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "Summarize the supplied deterministic Voice-of-Store result in at most 3 concise sentences. "
                            "Use only supplied facts. Do not infer causes, verify allegations, recommend actions, or invent "
                            "numbers. Preserve uncertainty and severity. Return plain text only."
                        )
                    }
                ]
            },
            "contents": [{"parts": [{"text": json.dumps(facts, ensure_ascii=True)}]}],
        }
        models = [self.model]
        for fallback in ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash"):
            if fallback not in models:
                models.append(fallback)

        last_error = None
        for m in models:
            try:
                text = self._call_model(m, body)
                if text:
                    return text[:MAX_OUTPUT_CHARS]
            except GeminiError as exc:
                last_error = exc
                if "invalid or lacks permission" in str(exc):
                    raise
        if last_error:
            raise last_error
        raise GeminiError("Gemini returned an empty summary")
