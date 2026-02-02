import os
from typing import Any, Dict, Optional

import httpx

DEFAULT_PLUGIN_SLUG = "BrainDriveDiscordChatbotCommunity"
DEFAULT_API_URL = "http://localhost:8000"


def build_message_payload(
    *,
    user_id: str,
    target_user_id: Optional[str] = None,
    settings_instance_id: Optional[str] = None,
    service_secret: Optional[str] = None,
    guild_id: Optional[str],
    channel_id: Optional[str],
    message_id: Optional[str],
    text: str,
    rag_collection_id: Optional[str] = None,
    model: Optional[str] = None,
    persona_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "user_id": user_id,
        "guild_id": guild_id,
        "channel_id": channel_id,
        "message_id": message_id,
        "text": text,
    }
    if target_user_id:
        payload["target_user_id"] = target_user_id
    if settings_instance_id:
        payload["settings_instance_id"] = settings_instance_id
    if service_secret:
        payload["service_secret"] = service_secret
    if rag_collection_id:
        payload["rag_collection_id"] = rag_collection_id
    if model:
        payload["model"] = model
    if persona_id:
        payload["persona_id"] = persona_id
    if config:
        payload["config"] = config
    return payload


async def post_discord_message(payload: Dict[str, Any]) -> Dict[str, Any]:
    api_url = os.getenv("BRAINDRIVE_API_URL", DEFAULT_API_URL).rstrip("/")
    plugin_slug = os.getenv("BRAINDRIVE_PLUGIN_SLUG", DEFAULT_PLUGIN_SLUG)
    auth_token = os.getenv("BRAINDRIVE_AUTH_TOKEN")

    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    url = f"{api_url}/api/v1/plugin-api/{plugin_slug}/discord/message"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
