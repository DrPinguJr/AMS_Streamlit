from __future__ import annotations

import pytest

from Flexar.whatsapp_request_processor.config import Settings
from Flexar.whatsapp_request_processor.database import Database
from Flexar.whatsapp_request_processor.request_engine import RequestEngine


@pytest.fixture()
def engine(tmp_path) -> RequestEngine:
    settings = Settings(
        database_path=tmp_path / "test.db",
        min_required_images=7,
        container_inactive_seconds=60,
        container_expiry_seconds=1800,
        require_operator_approval=False,
        automation_mode=True,
        auto_dispatch_complete_requests=True,
        auto_dispatch_in_simulation=True,
        simulation_mode=True,
        request_quiet_seconds=0,
    )
    db = Database(settings)
    return RequestEngine(db=db, settings=settings)
