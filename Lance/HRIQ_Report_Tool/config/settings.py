from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_DIR.parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _integer(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _path(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip()
    return Path(raw).expanduser() if raw else default


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    portal_url: str
    raw_rdl_dir: Path
    parsed_dir: Path
    index_path: Path
    log_dir: Path
    db_server: str
    db_name: str
    db_driver: str
    db_username: str
    db_password: str
    db_trust_certificate: str
    sql_row_limit: int
    sql_timeout_seconds: int
    download_workers: int
    archive_dir: Path
    state_path: Path
    development_mode: bool
    browser_headless: bool
    auth_mode: str
    ssrs_root_folder: str
    zip_max_entries: int
    zip_max_rdl_size_mb: int
    zip_max_total_uncompressed_mb: int
    zip_max_compression_ratio: int

    @property
    def database_configured(self) -> bool:
        return bool(self.db_server and self.db_name)

    def ensure_directories(self) -> None:
        for path in (
            self.raw_rdl_dir, self.parsed_dir, self.archive_dir,
            self.index_path.parent, self.state_path.parent, self.log_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    settings = Settings(
        portal_url=os.getenv("HRIQ_PORTAL_URL", "").strip(),
        raw_rdl_dir=_path("HRIQ_RDL_DIR", PROJECT_ROOT / "HR" / "RDL"),
        parsed_dir=_path("HRIQ_PARSED_DIR", PROJECT_ROOT / "HR" / "RDL_Parsed"),
        index_path=APP_DIR / "state" / "report_index.db",
        log_dir=APP_DIR / "logs",
        db_server=os.getenv("HRIQ_DB_SERVER", "").strip(),
        db_name=os.getenv("HRIQ_DB_NAME", "").strip(),
        db_driver=os.getenv("HRIQ_DB_DRIVER", "ODBC Driver 18 for SQL Server").strip(),
        db_username=os.getenv("HRIQ_DB_USERNAME", "").strip(),
        db_password=os.getenv("HRIQ_DB_PASSWORD", ""),
        db_trust_certificate=os.getenv("HRIQ_DB_TRUST_CERTIFICATE", "yes").strip(),
        sql_row_limit=_integer("SQL_ROW_LIMIT", 500),
        sql_timeout_seconds=_integer("SQL_TIMEOUT_SECONDS", 30),
        download_workers=_integer("DOWNLOAD_WORKERS", 3),
        archive_dir=_path("HRIQ_ARCHIVE_DIR", PROJECT_ROOT / "HR" / "RDL_Archives"),
        state_path=APP_DIR / "state" / "ssrs_state.db",
        development_mode=_boolean("HRIQ_DEVELOPMENT_MODE", False),
        browser_headless=_boolean("HRIQ_BROWSER_HEADLESS", True),
        auth_mode=os.getenv("HRIQ_AUTH_MODE", "automatic").strip().casefold(),
        ssrs_root_folder=os.getenv("HRIQ_SSRS_ROOT_FOLDER", "GOLDBELL").strip().strip("/"),
        zip_max_entries=_integer("ZIP_MAX_ENTRIES", 20_000),
        zip_max_rdl_size_mb=_integer("ZIP_MAX_RDL_SIZE_MB", 100),
        zip_max_total_uncompressed_mb=_integer("ZIP_MAX_TOTAL_UNCOMPRESSED_MB", 5_000),
        zip_max_compression_ratio=_integer("ZIP_MAX_COMPRESSION_RATIO", 200),
    )
    settings.ensure_directories()
    return settings
