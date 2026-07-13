"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parent
REPO_ROOT = PROJECT_DIR.parents[1]


def _to_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the prototype."""

    waapi_enabled: bool = False
    waapi_outbound_enabled: bool = False
    waapi_rider_reply_enabled: bool = False
    waapi_ops_update_enabled: bool = False
    waapi_instance_id: str = ""
    waapi_token: str = ""
    waapi_base_url: str = ""
    waapi_webhook_secret: str = ""
    ops_group_chat_id: str = ""
    min_required_images: int = 4
    container_inactive_seconds: int = 60
    container_expiry_seconds: int = 1800
    request_quiet_seconds: int = 8
    request_inactive_seconds: int = 60
    late_media_grace_seconds: int = 120
    default_action: str = ""
    database_path: Path = Path()
    simulation_mode: bool = True
    automation_mode: bool = True
    require_operator_approval: bool = False
    auto_dispatch_complete_requests: bool = True
    auto_dispatch_in_simulation: bool = True
    require_location_reference: bool = True
    require_parking_position: bool = True
    require_deck_for_mscp: bool = True
    require_lot_number: bool = False
    auto_send_complete_requests: bool = True
    simulator_default_delay_seconds: float = 1.0
    log_level: str = "INFO"
    api_base_url: str = "http://127.0.0.1:8000"

    @property
    def container_timeout_seconds(self) -> int:
        """Backward-compatible alias used by older tests and UI code."""

        return self.container_expiry_seconds


def default_database_path() -> Path:
    """Resolve the safest default DB location for an actively written SQLite file."""

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "AMS_Streamlit" / "Flexar" / "flexar_requests.db"
    return PROJECT_DIR / "data" / "flexar_requests.db"


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value


def get_settings(env_file: str | Path | None = None) -> Settings:
    """Load settings from .env, environment variables, and defaults."""

    if env_file:
        load_dotenv(env_file, override=False)
    else:
        load_dotenv(REPO_ROOT / ".env", override=False)
        load_dotenv(PROJECT_DIR / ".env", override=False)

    db_value = _env("DATABASE_PATH")
    if db_value:
        db_path = Path(db_value)
        if not db_path.is_absolute():
            db_path = PROJECT_DIR / db_path
    else:
        db_path = default_database_path()

    return Settings(
        waapi_enabled=_to_bool(os.getenv("WAAPI_ENABLED"), False),
        waapi_outbound_enabled=_to_bool(os.getenv("WAAPI_OUTBOUND_ENABLED"), False),
        waapi_rider_reply_enabled=_to_bool(os.getenv("WAAPI_RIDER_REPLY_ENABLED"), False),
        waapi_ops_update_enabled=_to_bool(os.getenv("WAAPI_OPS_UPDATE_ENABLED"), False),
        waapi_instance_id=os.getenv("WAAPI_INSTANCE_ID", ""),
        waapi_token=os.getenv("WAAPI_TOKEN", ""),
        waapi_base_url=_env("WAAPI_BASE_URL").rstrip("/"),
        waapi_webhook_secret=os.getenv("WAAPI_WEBHOOK_SECRET", ""),
        ops_group_chat_id=os.getenv("OPS_GROUP_CHAT_ID", ""),
        min_required_images=int(os.getenv("MIN_REQUIRED_IMAGES", "4")),
        container_inactive_seconds=int(os.getenv("CONTAINER_INACTIVE_SECONDS", "60")),
        container_expiry_seconds=int(os.getenv("CONTAINER_EXPIRY_SECONDS", os.getenv("CONTAINER_TIMEOUT_SECONDS", "1800"))),
        request_quiet_seconds=int(os.getenv("REQUEST_QUIET_SECONDS", "8")),
        request_inactive_seconds=int(os.getenv("REQUEST_INACTIVE_SECONDS", os.getenv("CONTAINER_INACTIVE_SECONDS", "60"))),
        late_media_grace_seconds=int(os.getenv("LATE_MEDIA_GRACE_SECONDS", "120")),
        default_action=os.getenv("DEFAULT_ACTION", "").strip().upper(),
        database_path=db_path,
        simulation_mode=_to_bool(os.getenv("SIMULATION_MODE"), True),
        automation_mode=_to_bool(os.getenv("AUTOMATION_MODE"), True),
        require_operator_approval=_to_bool(os.getenv("REQUIRE_OPERATOR_APPROVAL"), False),
        auto_dispatch_complete_requests=_to_bool(os.getenv("AUTO_DISPATCH_COMPLETE_REQUESTS"), True),
        auto_dispatch_in_simulation=_to_bool(os.getenv("AUTO_DISPATCH_IN_SIMULATION"), True),
        require_location_reference=_to_bool(os.getenv("REQUIRE_LOCATION_REFERENCE"), True),
        require_parking_position=_to_bool(os.getenv("REQUIRE_PARKING_POSITION"), True),
        require_deck_for_mscp=_to_bool(os.getenv("REQUIRE_DECK_FOR_MSCP"), True),
        require_lot_number=_to_bool(os.getenv("REQUIRE_LOT_NUMBER"), False),
        auto_send_complete_requests=_to_bool(os.getenv("AUTO_SEND_COMPLETE_REQUESTS"), True),
        simulator_default_delay_seconds=float(os.getenv("SIMULATOR_DEFAULT_DELAY_SECONDS", "1")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        api_base_url=os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
    )
