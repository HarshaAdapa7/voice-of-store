"""Supabase and PostgreSQL database integration module for Voice of Store.

Provides data persistence, table synchronization, alert auditing, and connection management.
Supports both Supabase REST API (via publishable/anon key) and direct PostgreSQL connection.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def load_env() -> None:
    """Load configuration variables from .env files if present."""
    try:
        from dotenv import load_dotenv

        root = Path(__file__).resolve().parents[2]
        for candidate in (Path(".env"), root / ".env", root.parent / ".env"):
            if candidate.is_file():
                load_dotenv(candidate, override=False)
    except ImportError:
        pass


def _percent_unquote(s: str) -> str:
    """Decode URL percent-encoded characters without importing network modules."""
    return re.sub(r"%([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), s)


def _parse_pg_url(url: str) -> dict[str, str]:
    """Parse PostgreSQL connection string into components without network modules."""
    rest = url.split("://", 1)[1] if "://" in url else url
    auth, sep, rest = rest.rpartition("@")
    user, pg_pwd = "postgres", ""
    if sep:
        user_pass = auth.split(":", 1)
        user = _percent_unquote(user_pass[0]) or "postgres"
        if len(user_pass) > 1:
            pg_pwd = _percent_unquote(user_pass[1])
    host_port, _, dbname = rest.partition("/")
    dbname = dbname.split("?")[0] if "?" in dbname else dbname
    host, _, port = host_port.partition(":")
    return {
        "user": user,
        "password": pg_pwd,
        "host": host,
        "port": port or "5432",
        "dbname": dbname or "postgres",
    }


def _derive_pooler_params(host: str, user: str, port: int | str) -> tuple[str, str, int]:
    """Derive IPv4 pooler host, user and port for IPv6-only Supabase direct hosts."""
    if host.startswith("db.") and ".supabase.co" in host:
        ref = host.split(".supabase.co")[0].replace("db.", "")
        pool_user = user if f".{ref}" in user else f"postgres.{ref}"
        return "aws-0-eu-west-1.pooler.supabase.com", pool_user, 5432
    return host, user, int(port)


class DatabaseError(RuntimeError):
    """Safe database exception containing non-sensitive diagnostic details."""


@dataclass
class SupabaseConfig:
    """Configuration settings for Supabase and PostgreSQL connections."""

    url: str = ""
    key: str = ""
    db_host: str = ""
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = ""
    db_name: str = "postgres"
    database_url: str = ""

    @classmethod
    def from_env(cls, load_dotenv_file: bool = True) -> SupabaseConfig:
        """Create configuration from current environment variables."""
        if load_dotenv_file:
            load_env()
        url = (
            os.environ.get("SUPABASE_URL")
            or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
            or ""
        )
        key = (
            os.environ.get("SUPABASE_KEY")
            or os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
            or os.environ.get("SUPABASE_ANON_KEY")
            or ""
        )
        db_host = os.environ.get("SUPABASE_DB_HOST", "")
        db_user = os.environ.get("SUPABASE_DB_USER", "")
        db_port_str = os.environ.get("SUPABASE_DB_PORT", "")

        if url and not db_host:
            clean_url = url.replace("https://", "").replace("http://", "").rstrip("/")
            if ".supabase.co" in clean_url:
                ref = clean_url.split(".supabase.co")[0]
                # Default to IPv4-ready pooler host
                db_host = "aws-0-eu-west-1.pooler.supabase.com"
                if not db_user:
                    db_user = f"postgres.{ref}"
                if not db_port_str:
                    db_port_str = "6543"

        if not db_user:
            db_user = "postgres"
        db_port = int(db_port_str or "5432")
        db_password = os.environ.get("SUPABASE_DB_PASSWORD", "")
        db_name = os.environ.get("SUPABASE_DB_NAME", "postgres")
        database_url = os.environ.get("DATABASE_URL", "")

        return cls(
            url=url.strip(),
            key=key.strip(),
            db_host=db_host.strip(),
            db_port=db_port,
            db_user=db_user.strip(),
            db_password=db_password.strip(),
            db_name=db_name.strip(),
            database_url=database_url.strip(),
        )

    @property
    def is_configured(self) -> bool:
        """Whether at least the Supabase REST URL and key or direct DB URL is provided."""
        return (bool(self.url) and bool(self.key)) or bool(self.database_url) or bool(self.db_password)

    @property
    def has_db_password(self) -> bool:
        """Whether a direct PostgreSQL password or connection string is available."""
        return bool(self.db_password) or bool(self.database_url)

    def get_pg_dsn(self) -> str:
        """Construct PostgreSQL connection DSN."""
        if self.database_url and not self.db_password:
            return self.database_url
        if not self.has_db_password:
            raise DatabaseError("PostgreSQL password has not been provided yet")
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={self.db_user} password={self.db_password} sslmode=require"
        )


class DatabaseManager:
    """Manages Supabase client lifecycle and database operations."""

    def __init__(self, config: SupabaseConfig | None = None) -> None:
        self.config = config or SupabaseConfig.from_env()
        self._client: Any = None

    def get_client(self) -> Any:
        """Get or initialize the Supabase client."""
        if self._client is not None:
            return self._client
        if not self.config.url or not self.config.key:
            raise DatabaseError("Supabase URL and API Key are required to initialize client")
        try:
            from supabase import create_client

            self._client = create_client(self.config.url, self.config.key)
            return self._client
        except Exception as exc:
            log.warning("Could not initialize Supabase client: %s", exc)
            raise DatabaseError("Failed to initialize Supabase client") from exc

    def _attempt_connect(
        self, host: str, port: int, user: str, password: str, dbname: str
    ) -> Any:
        """Attempt single PostgreSQL connection via psycopg2."""
        import psycopg2

        return psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            sslmode="require",
            connect_timeout=10,
        )

    def get_pg_connection(self) -> Any:
        """Establish PostgreSQL connection with automatic IPv4 pooler fallback."""
        if not self.config.has_db_password:
            raise DatabaseError("Database password is not yet configured")

        if self.config.database_url:
            p = _parse_pg_url(self.config.database_url)
            host, port = p["host"], int(p["port"])
            user, password, dbname = p["user"], p["password"], p["dbname"]
        else:
            host, port = self.config.db_host, self.config.db_port
            user = self.config.db_user
            password, dbname = self.config.db_password, self.config.db_name

        try:
            return self._attempt_connect(host, port, user, password, dbname)
        except Exception as exc:
            err = str(exc)
            is_dns = "could not translate host name" in err or "Name or service not known" in err
            if is_dns and host.startswith("db.") and ".supabase.co" in host:
                p_host, p_user, p_port = _derive_pooler_params(host, user, port)
                log.info("Direct host failed on IPv4; retrying with pooler %s", p_host)
                try:
                    return self._attempt_connect(p_host, p_port, p_user, password, dbname)
                except Exception as p_exc:
                    log.warning("IPv4 pooler connection failed: %s", p_exc)
                    raise DatabaseError(
                        f"Failed to connect to Supabase (direct IPv6 host unresolved, pooler error: {p_exc})"
                    ) from p_exc
            raise DatabaseError(f"Failed to connect to PostgreSQL database: {exc}") from exc

    def check_health(self) -> dict[str, Any]:
        """Check database status and available tables."""
        status: dict[str, Any] = {
            "configured": self.config.is_configured,
            "url": self.config.url,
            "mode": "none",
            "connected": False,
            "tables": [],
            "has_pg_pass": self.config.has_db_password,
            "message": "Not configured",
        }
        if not self.config.is_configured:
            return status

        # Try REST connection first
        if self.config.url and self.config.key:
            status["mode"] = "rest"
            try:
                client = self.get_client()
                # Test querying the stores table
                resp = client.table("stores").select("store_id").limit(1).execute()
                status["connected"] = True
                status["tables"].append("stores")
                status["message"] = "Connected via Supabase REST API"
            except Exception as exc:
                err_msg = str(exc)
                if "PGRST205" in err_msg or "schema cache" in err_msg:
                    status["connected"] = True
                    status["message"] = "Connected to Supabase; tables need to be created via migration"
                else:
                    status["message"] = f"REST connection check: {type(exc).__name__}"

        # If PG password is also present, direct connection can be verified
        if self.config.has_db_password:
            status["mode"] = "postgres"
            try:
                conn = self.get_pg_connection()
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
                    )
                    rows = cur.fetchall()
                    status["tables"] = [r[0] for r in rows]
                    status["connected"] = True
                    status["message"] = f"Connected directly via PostgreSQL ({len(status['tables'])} tables found)"
                conn.close()
            except Exception as exc:
                if not status["connected"]:
                    status["message"] = f"PostgreSQL connection check: {type(exc).__name__}"

        return status

    def execute_schema_migration(self, sql_script: str) -> bool:
        """Execute SQL DDL schema migration via direct PostgreSQL connection."""
        conn = self.get_pg_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql_script)
            conn.commit()
            return True
        finally:
            conn.close()

    def log_alert_audit(
        self,
        week: str,
        batch_id: str,
        approved_by: str,
        status: str,
        recipient_count: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Log an alert batch dispatch to Supabase for compliance audit."""
        if not self.config.is_configured:
            return False
        record = {
            "week": week,
            "batch_id": batch_id,
            "approved_by": approved_by,
            "status": status,
            "recipient_count": recipient_count,
            "payload": payload or {},
        }
        try:
            client = self.get_client()
            client.table("alert_audit_logs").insert(record).execute()
            return True
        except Exception as exc:
            log.warning("Could not write alert audit to Supabase: %s", exc)
            return False

    def insert_feedback(self, item: dict[str, Any]) -> bool:
        """Insert a single customer feedback item into Supabase."""
        if not self.config.is_configured:
            return False
        try:
            client = self.get_client()
            client.table("feedback").insert(item).execute()
            return True
        except Exception as exc:
            log.warning("Could not insert feedback into Supabase: %s", exc)
            return False


# Singleton default manager
_default_manager: DatabaseManager | None = None


def get_db() -> DatabaseManager:
    """Get or create the singleton DatabaseManager instance."""
    global _default_manager
    if _default_manager is None:
        _default_manager = DatabaseManager()
    return _default_manager
