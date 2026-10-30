"""Tests for Supabase database integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from voice_of_store.db import DatabaseError, DatabaseManager, SupabaseConfig


def test_supabase_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_DB_HOST", raising=False)
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "sb_test_publishable_key")

    cfg = SupabaseConfig.from_env(load_dotenv_file=False)
    assert cfg.url == "https://example.supabase.co"
    assert cfg.key == "sb_test_publishable_key"
    assert "pooler.supabase.com" in cfg.db_host
    assert cfg.is_configured is True
    assert cfg.has_db_password is False


def test_supabase_config_password_and_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "sb_test_key")
    monkeypatch.setenv("SUPABASE_DB_HOST", "aws-0-eu-west-1.pooler.supabase.com")
    monkeypatch.setenv("SUPABASE_DB_PASSWORD", "testpass")

    cfg = SupabaseConfig.from_env(load_dotenv_file=False)
    assert cfg.has_db_password is True
    dsn = cfg.get_pg_dsn()
    assert "host=aws-0-eu-west-1.pooler.supabase.com" in dsn
    assert "password=testpass" in dsn


def test_supabase_config_missing_password_raises() -> None:
    cfg = SupabaseConfig(url="https://example.supabase.co", key="sb_key", db_password="")
    assert cfg.has_db_password is False
    with pytest.raises(DatabaseError, match="password"):
        cfg.get_pg_dsn()


def test_db_manager_unconfigured() -> None:
    mgr = DatabaseManager(SupabaseConfig())
    assert mgr.config.is_configured is False
    with pytest.raises(DatabaseError):
        mgr.get_client()
    health = mgr.check_health()
    assert health["configured"] is False
    assert health["connected"] is False


def test_db_manager_health_safe_diagnostics() -> None:
    cfg = SupabaseConfig(
        url="https://example.supabase.co",
        key="sb_test_key",
        db_password="masked",
    )
    mgr = DatabaseManager(cfg)
    health = mgr.check_health()
    assert "masked" not in str(health)
    assert health["has_pg_pass"] is True
    assert health["configured"] is True


def test_sql_schema_file_integrity() -> None:
    schema_path = Path(__file__).resolve().parents[1] / "scripts" / "supabase_schema.sql"
    assert schema_path.is_file()
    sql = schema_path.read_text(encoding="utf-8")

    expected_tables = [
        "stores",
        "issue_taxonomy",
        "week_calendar",
        "feedback",
        "feedback_labels",
        "emerging_flags",
        "predictions",
        "alert_audit_logs",
    ]
    for table in expected_tables:
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in sql
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;" in sql


def test_log_alert_audit_fallback() -> None:
    mgr = DatabaseManager(SupabaseConfig())
    # Should safely return False without exception when unconfigured
    result = mgr.log_alert_audit("2026-01-05", "batch_abc", "admin", "delivered")
    assert result is False
