from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote_plus

from Lance.HRIQ_Report_Tool.config.settings import Settings


def build_odbc_string(settings: Settings) -> str:
    if not settings.database_configured:
        raise RuntimeError("Database not configured")
    parts = [
        f"DRIVER={{{settings.db_driver}}}",
        f"SERVER={settings.db_server}",
        f"DATABASE={settings.db_name}",
        "Encrypt=yes",
        f"TrustServerCertificate={settings.db_trust_certificate}",
    ]
    if settings.db_username:
        parts.extend([f"UID={settings.db_username}", f"PWD={settings.db_password}"])
    else:
        parts.append("Trusted_Connection=yes")
    return ";".join(parts)


@lru_cache(maxsize=2)
def _engine(odbc_string: str, timeout: int):
    try:
        from sqlalchemy import create_engine, event
    except ImportError as exc:
        raise RuntimeError("SQL support is not installed. Install the project requirements.") from exc
    url = f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc_string)}"
    engine = create_engine(url, pool_pre_ping=True, connect_args={"timeout": timeout})

    @event.listens_for(engine, "before_cursor_execute")
    def set_timeout(_conn, cursor, _statement, _parameters, _context, _executemany):
        cursor.timeout = timeout

    return engine


def get_engine(settings: Settings):
    return _engine(build_odbc_string(settings), settings.sql_timeout_seconds)
