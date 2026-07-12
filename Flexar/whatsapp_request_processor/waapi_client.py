"""Future WAAPI outbound adapter with simulation enabled by default."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import Settings, get_settings


LOGGER = logging.getLogger(__name__)


class WAAPIClient:
    """Keep all WAAPI URL construction and HTTP behaviour in one place."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def validate_configuration(self) -> None:
        if not self.settings.waapi_enabled or self.settings.simulation_mode:
            return
        missing = []
        if not self.settings.waapi_instance_id:
            missing.append("WAAPI_INSTANCE_ID")
        if not self.settings.waapi_token:
            missing.append("WAAPI_TOKEN")
        if not self.settings.waapi_base_url:
            missing.append("WAAPI_BASE_URL")
        if missing:
            raise ValueError(f"Missing WAAPI configuration: {', '.join(missing)}")

    def health_check(self) -> dict[str, Any]:
        if not self.settings.waapi_enabled or self.settings.simulation_mode:
            return {"ok": True, "simulated": True, "message": "WAAPI is disabled or simulation mode is enabled."}
        try:
            self.validate_configuration()
        except ValueError as exc:
            return {"ok": False, "simulated": False, "error": str(exc)}
        return {"ok": True, "simulated": False, "message": "Configuration present; live WAAPI endpoint not yet verified."}

    def send_text_message(self, chat_id: str, message_text: str) -> dict[str, Any]:
        payload = {"chatId": chat_id, "message": message_text}
        return self._send_action("send-message", payload)

    def send_media_message(self, chat_id: str, media_payload: dict[str, Any], caption: str = "") -> dict[str, Any]:
        payload = {"chatId": chat_id, "media": media_payload, "caption": caption}
        return self._send_action("send-media", payload)

    def send_rider_reply(self, chat_id: str, message_text: str) -> dict[str, Any]:
        return self.send_text_message(chat_id, message_text)

    def send_ops_group_update(self, chat_id: str, message_text: str, media: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if media:
            return self.send_media_message(chat_id, {"items": media}, caption=message_text)
        return self.send_text_message(chat_id, message_text)

    def send_completed_request(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        """Backward-compatible wrapper used by older callers."""

        destination = str(request_payload.get("chat_id") or request_payload.get("destination_id") or "")
        message = str(request_payload.get("message_text") or request_payload.get("cleaned_message") or request_payload)
        return self.send_text_message(destination, message)

    def _send_action(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.waapi_enabled or self.settings.simulation_mode:
            return {
                "ok": True,
                "simulated": True,
                "status": "SIMULATED_SENT",
                "action": action,
                "message": "No external WAAPI request was made.",
            }

        self.validate_configuration()
        url = f"{self.settings.waapi_base_url}/api/v1/instances/{self.settings.waapi_instance_id}/client/action/{action}"
        headers = {
            "Authorization": f"Bearer {self.settings.waapi_token}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=20) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
            return {"ok": True, "simulated": False, "response": response.json()}
        except httpx.HTTPError as exc:
            LOGGER.warning("WAAPI request failed for action %s: %s", action, exc)
            return {"ok": False, "simulated": False, "error": str(exc)}

