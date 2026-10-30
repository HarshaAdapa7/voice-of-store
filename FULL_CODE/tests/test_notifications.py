"""Approved alert delivery is audited, quote-free, and never retries silently."""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from voice_of_store.notifications import AlertDelivery, AlertDeliveryError, SMTPSettings


def _settings(path):
    return SMTPSettings(
        host="smtp.example.test",
        port=587,
        username="operator",
        password="test_pw",
        sender="alerts@example.test",
        recipients=("ops@example.test",),
        audit_path=path,
    )


def _flags():
    return [
        {
            "store_id": "ST-ABCDE",
            "store": "Saffron Test",
            "region": "South",
            "issue_type": "IT10",
            "issue": "Refrigeration",
            "owner": "Store Ops",
            "confidence": 0.8,
            "change": {"summary": "2 reports against usual 0.5"},
            "next_step": "Check the temperature log.",
            "evidence": [{"text": "PRIVATE RAW FEEDBACK QUOTE"}],
        }
    ]


class FakeSMTP:
    def __init__(self, host, port, timeout):
        self.details = (host, port, timeout)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def starttls(self, context):
        self.tls_context = context

    def login(self, username, password):
        self.credentials = (username, password)

    def send_message(self, message, from_addr, to_addrs):
        assert isinstance(message, EmailMessage)
        self.message = message
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        return {}


def test_prepare_email_excludes_raw_feedback_and_delivery_requires_approval(tmp_path):
    delivery = AlertDelivery(_settings(tmp_path / "audit.jsonl"), smtp_factory=FakeSMTP)
    prepared = delivery.prepare("2026-09-21", _flags())
    assert prepared["flag_count"] == 1 and prepared["enabled"]
    assert "evidence" not in repr(prepared) and "PRIVATE RAW FEEDBACK QUOTE" not in repr(prepared)

    with pytest.raises(AlertDeliveryError, match="approval"):
        delivery.send("2026-09-21", _flags(), prepared["batch_id"], approved=False, approved_by="ops")
    assert not (tmp_path / "audit.jsonl").exists()


def test_send_uses_tls_audits_and_blocks_duplicate_batch(tmp_path):
    smtp = FakeSMTP("", 0, 0)
    delivery = AlertDelivery(_settings(tmp_path / "audit.jsonl"), smtp_factory=lambda *a, **k: smtp)
    prepared = delivery.prepare("2026-09-21", _flags())
    result = delivery.send("2026-09-21", _flags(), prepared["batch_id"], approved=True, approved_by="ops")
    email = smtp.message

    assert result["sent"] and result["recipient_count"] == 1
    assert smtp.to_addrs == ["ops@example.test"] and smtp.from_addr == "alerts@example.test"
    assert email["Message-ID"] == f"<r5-{prepared['batch_id']}@voice-of-store.local>"
    assert "unverified" in email.get_content().lower()
    assert "PRIVATE RAW FEEDBACK QUOTE" not in email.get_content()
    assert "2 reports against usual 0.5" in email.get_content()
    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    import json

    entries = [json.loads(line) for line in audit]
    assert [entry["status"] for entry in entries] == ["attempted", "sent"]
    assert all(entry["approved_by"] == "ops" for entry in entries)

    with pytest.raises(AlertDeliveryError, match="already attempted"):
        delivery.send("2026-09-21", _flags(), prepared["batch_id"], approved=True, approved_by="ops")


def test_changed_batch_and_missing_smtp_configuration_are_refused(tmp_path):
    delivery = AlertDelivery(_settings(tmp_path / "audit.jsonl"), smtp_factory=FakeSMTP)
    prepared = delivery.prepare("2026-09-21", _flags())
    changed_flags = _flags()
    changed_flags[0]["change"]["summary"] = "A different reviewed change"
    assert delivery.prepare("2026-09-21", changed_flags)["batch_id"] != prepared["batch_id"]
    with pytest.raises(AlertDeliveryError, match="changed"):
        delivery.send("2026-09-21", [], prepared["batch_id"], approved=True, approved_by="ops")

    disabled = AlertDelivery(SMTPSettings(audit_path=tmp_path / "disabled.jsonl"), smtp_factory=FakeSMTP)
    with pytest.raises(AlertDeliveryError, match="not configured"):
        disabled.send("2026-09-21", _flags(), prepared["batch_id"], approved=True, approved_by="ops")


def test_invalid_optional_environment_disables_mail_without_crashing(monkeypatch):
    from voice_of_store.notifications import SMTPSettings

    monkeypatch.setenv("R5_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("R5_SMTP_FROM", "not-an-address")
    monkeypatch.setenv("R5_ALERT_RECIPIENTS", "not-an-address")
    settings = SMTPSettings.from_env()
    assert not settings.enabled and settings.configuration_error
