"""FastAPI webhook receiver for local and future WAAPI testing."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query

from .config import get_settings
from .database import Database
from .models import display_state, utc_now
from .request_engine import RequestEngine
from .worker import DueRequestWorker


settings = get_settings()
db = Database(settings)
engine = RequestEngine(db=db, settings=settings)
worker = DueRequestWorker(engine)
LOGGER = logging.getLogger(__name__)
APPLICATION_STARTED_AT: datetime | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global APPLICATION_STARTED_AT
    APPLICATION_STARTED_AT = utc_now()
    worker.start()
    LOGGER.info("AMS_COMPONENT=API FastAPI application is ready")
    try:
        yield
    finally:
        worker.stop()
        LOGGER.info("AMS_COMPONENT=API FastAPI application stopped")


app = FastAPI(title="Flexar WhatsApp Request Processor", version="0.3.0", lifespan=lifespan)


def _process(body: dict[str, Any]) -> dict[str, Any]:
    results = engine.process_webhook_payload(body)
    engine.process_due_dispatches()
    if not results:
        raise HTTPException(status_code=400, detail="No processable messages found")
    if len(results) == 1:
        result = results[0].model_dump()
        result.setdefault("display_state", display_state(result.get("container_state")))
        LOGGER.info(
            "AMS_COMPONENT=API Simulator event accepted; request=%s state=%s",
            str(result.get("container_uuid") or "-")[:8],
            result.get("container_state") or result.get("status") or "unknown",
        )
        return result
    return {
        "status": "processed",
        "event_ids": [event_id for result in results for event_id in result.event_ids],
        "results": [result.model_dump() for result in results],
        "timestamp": utc_now().astimezone(timezone.utc).isoformat(),
    }


@app.get("/health")
def health() -> dict[str, Any]:
    checks = engine.health()
    pending_requests = db.fetch_one(
        "SELECT COUNT(*) AS count FROM request_containers WHERE state IN ('COLLECTING', 'READY_WAITING_QUIET', 'DISPATCHING', 'PAUSED', 'NEEDS_REVIEW', 'MANUAL_REVIEW') AND deleted_at IS NULL"
    )
    failed_actions = db.fetch_one("SELECT COUNT(*) AS count FROM outbound_actions WHERE status = 'FAILED'")
    last_simulator = db.fetch_one("SELECT MAX(received_at) AS received_at FROM incoming_events WHERE source = 'SIMULATOR'")
    worker_online = worker.is_alive
    return {
        "service": "ams-whatsapp-request-processor",
        "status": "ok" if checks["ok"] else "error",
        "database": checks["sqlite"],
        "worker": {"status": "online" if worker_online else "offline", "running": worker_online},
        "application_started_at": APPLICATION_STARTED_AT.isoformat() if APPLICATION_STARTED_AT else None,
        "simulation_mode": settings.simulation_mode,
        "waapi": {
            "status": "disabled" if not settings.waapi_enabled else "configured",
            "outbound_enabled": bool(settings.waapi_enabled and settings.waapi_outbound_enabled and not settings.simulation_mode),
            "rider_reply_enabled": settings.waapi_rider_reply_enabled,
            "ops_update_enabled": settings.waapi_ops_update_enabled,
        },
        "mode": "simulation" if settings.simulation_mode or not settings.waapi_enabled else "waapi-enabled",
        "pending_request_count": int((pending_requests or {}).get("count") or 0),
        "failed_action_count": int((failed_actions or {}).get("count") or 0),
        "last_inbound_simulator_event_at": (last_simulator or {}).get("received_at"),
        "timestamp": utc_now().isoformat(),
        "checks": checks,
    }


@app.post("/webhooks/waapi")
def waapi_webhook(payload: dict[str, Any], x_waapi_secret: str | None = Header(default=None)) -> dict[str, Any]:
    if settings.waapi_webhook_secret and x_waapi_secret != settings.waapi_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    payload = {**payload, "source": payload.get("source") or "WAAPI"}
    return _process(payload)


@app.post("/test/payload")
def test_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.simulation_mode:
        raise HTTPException(status_code=403, detail="Test payload endpoint is disabled outside simulation mode")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    body = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    body = {**body, "source": body.get("source") or "SIMULATOR"}
    return _process(body)


@app.get("/containers")
def containers(
    state: str | None = Query(default=None),
    sender: str | None = Query(default=None),
    lp: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    rows = engine.list_containers(include_completed=True)
    if state:
        rows = [row for row in rows if row["state"] == state]
    if sender:
        rows = [row for row in rows if sender.lower() in row["sender_id"].lower()]
    if lp:
        rows = [row for row in rows if lp.upper() in str(row.get("detected_licence_plate") or "").upper()]
    return rows


@app.get("/outbound")
def outbound(
    status: str | None = Query(default=None),
    action_type: str | None = Query(default=None),
    container: str | None = Query(default=None),
) -> dict[str, list[dict[str, Any]]]:
    requests = engine.list_outbound()
    actions = engine.list_outbound_actions(status=status)
    if action_type:
        actions = [row for row in actions if row["action_type"] == action_type]
    if container:
        requests = [row for row in requests if row["container_uuid"] == container]
        actions = [row for row in actions if row["container_uuid"] == container]
    return {"requests": requests, "actions": actions}


@app.post("/outbound/{action_id}/simulate")
def simulate_outbound_action(action_id: int) -> dict[str, Any]:
    try:
        return engine.outbound.simulate_action(action_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
