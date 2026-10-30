"""Approved, audited SMTP delivery for weekly emerging-issue summaries."""

from __future__ import annotations

import hashlib
import json
import os
import re
import smtplib
import ssl
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

_EMAIL = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
_WEEK = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AlertDeliveryError(RuntimeError):
    """A safe notification error without SMTP details or credentials."""


@dataclass(frozen=True)
class SMTPSettings:
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    sender: str = ""
    recipients: tuple[str, ...] = ()
    audit_path: Path = Path("out/notification_audit.jsonl")
    configuration_error: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.sender and self.recipients and not self.configuration_error)

    @classmethod
    def from_env(cls) -> SMTPSettings:
        host = os.environ.get("R5_SMTP_HOST", "").strip()
        sender = os.environ.get("R5_SMTP_FROM", "").strip()
        raw_recipients = os.environ.get("R5_ALERT_RECIPIENTS", "")
        recipients = tuple(address.strip() for address in raw_recipients.split(",") if address.strip())
        username = os.environ.get("R5_SMTP_USERNAME", "")
        password = os.environ.get("R5_SMTP_PASSWORD", "")
        configuration_error = ""
        try:
            port = int(os.environ.get("R5_SMTP_PORT", "587"))
        except ValueError:
            port = 587
            configuration_error = "SMTP port configuration is invalid"
        if not 1 <= port <= 65535:
            port = 587
            configuration_error = "SMTP port configuration is invalid"
        if bool(username) != bool(password):
            configuration_error = "SMTP authentication configuration is incomplete"
        configured = any((host, sender, raw_recipients, username, password))
        if configured:
            if not (host and sender and recipients):
                configuration_error = "SMTP host, sender, and alert recipients must all be configured"
            if any(not _EMAIL.fullmatch(address) for address in (sender, *recipients)):
                configuration_error = "SMTP sender or recipient configuration is invalid"
        audit_path = Path(os.environ.get("R5_ALERT_AUDIT_PATH", "out/notification_audit.jsonl"))
        return cls(host, port, username, password, sender, recipients, audit_path, configuration_error)


class AlertDelivery:
    """Build redacted alert emails and send only after explicit per-batch approval."""

    def __init__(self, settings: SMTPSettings | None = None, smtp_factory=smtplib.SMTP):
        self.settings = settings or SMTPSettings.from_env()
        self._smtp_factory = smtp_factory
        self._lock = threading.Lock()

    def prepare(self, week: str, flags: list[dict]) -> dict:
        if not _WEEK.fullmatch(week):
            raise AlertDeliveryError("Invalid alert week")
        items = [
            {
                "store": str(flag.get("store", "")),
                "region": str(flag.get("region", "")),
                "issue": str(flag.get("issue", "")),
                "owner": str(flag.get("owner", "")),
                "confidence": float(flag.get("confidence", 0.0)),
                "change": str(flag.get("change", {}).get("summary", "")),
                "next_step": str(flag.get("next_step", "")),
            }
            for flag in flags
        ]
        canonical = json.dumps({"week": week, "items": items}, sort_keys=True, separators=(",", ":"))
        batch_id = hashlib.sha256(canonical.encode()).hexdigest()
        return {
            "week": week,
            "batch_id": batch_id,
            "flag_count": len(flags),
            "recipients": list(self.settings.recipients),
            "enabled": self.settings.enabled,
            "items": items,
        }

    def _audit(self, batch_id: str) -> set[str]:
        path = self.settings.audit_path
        seen: set[str] = set()
        try:
            if not path.exists():
                return seen
            with path.open(encoding="utf-8") as audit:
                for line in audit:
                    entry = json.loads(line)
                    if isinstance(entry, dict) and isinstance(entry.get("batch_id"), str):
                        seen.add(entry["batch_id"])
        except (OSError, ValueError) as exc:
            raise AlertDeliveryError("Notification audit is unavailable; delivery refused") from exc
        if batch_id in seen:
            raise AlertDeliveryError("This alert batch was already attempted; review the audit before retrying")
        return seen

    def _record(self, batch_id: str, week: str, status: str, approved_by: str | None = None) -> None:
        path = self.settings.audit_path
        entry = {
            "batch_id": batch_id,
            "week": week,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if approved_by:
            entry["approved_by"] = approved_by
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as audit:
                audit.write(json.dumps(entry, separators=(",", ":")) + "\n")
                audit.flush()
                os.fsync(audit.fileno())
        except OSError as exc:
            raise AlertDeliveryError("Notification audit could not be written; delivery refused") from exc

    @staticmethod
    def _message(week: str, batch_id: str, prepared: dict, settings: SMTPSettings) -> EmailMessage:
        message = EmailMessage()
        message["From"] = settings.sender
        message["To"] = ", ".join(settings.recipients)
        message["Subject"] = f"[Voice of Store] {prepared['flag_count']} emerging alert(s) for {week}"
        message["Message-ID"] = f"<r5-{batch_id}@voice-of-store.local>"
        lines = [
            f"Weekly emerging-issue review for {week}",
            "These are unverified feedback signals, not confirmed incidents.",
            "Evidence quotes are intentionally excluded; review the secured dashboard before acting.",
            "",
        ]
        for item in prepared["items"]:
            lines.extend(
                [
                    f"{item['issue']} | {item['store']} ({item['region']})",
                    f"Owner: {item['owner']} | Confidence: {item['confidence']:.3f}",
                    f"Change: {item['change']}",
                    f"Suggested next step: {item['next_step']}",
                    "",
                ]
            )
        message.set_content("\n".join(lines))
        return message

    def send(self, week: str, flags: list[dict], batch_id: str, approved: bool, approved_by: str) -> dict:
        if not approved:
            raise AlertDeliveryError("Human approval is required for every alert batch")
        if not approved_by or len(approved_by) > 80:
            raise AlertDeliveryError("An authenticated approver is required")
        if not self.settings.enabled:
            raise AlertDeliveryError("SMTP alert delivery is not configured")
        prepared = self.prepare(week, flags)
        if batch_id != prepared["batch_id"]:
            raise AlertDeliveryError("Alert batch changed; prepare and review it again")
        with self._lock:
            self._audit(batch_id)
            self._record(batch_id, week, "attempted", approved_by)
            message = self._message(week, batch_id, prepared, self.settings)
            try:
                with self._smtp_factory(self.settings.host, self.settings.port, timeout=15) as smtp:
                    smtp.starttls(context=ssl.create_default_context())
                    if self.settings.username:
                        smtp.login(self.settings.username, self.settings.password)
                    refused = smtp.send_message(
                        message,
                        from_addr=self.settings.sender,
                        to_addrs=list(self.settings.recipients),
                    )
                    if refused:
                        raise AlertDeliveryError("One or more alert recipients were refused")
            except Exception as exc:
                raise AlertDeliveryError("Alert delivery failed; review the audit before retrying") from exc
            self._record(batch_id, week, "sent", approved_by)
        return {"week": week, "batch_id": batch_id, "sent": True, "recipient_count": len(self.settings.recipients)}