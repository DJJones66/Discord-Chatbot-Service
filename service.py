import os
import asyncio
from typing import Any, Dict, Optional, List

import discord
from fastapi import FastAPI, Body
import uvicorn

from db import init_db, log_message
from client import build_message_payload, post_discord_message

app = FastAPI()

SERVICE_NAME = "discord_chatbot_service"

init_db()

BOT_STATE = {
    "enabled": False,
    "connected": False,
    "last_error": None,
}

BOT_CLIENT: Optional[discord.Client] = None
BOT_TASK: Optional[asyncio.Task] = None
BOT_CONFIG: Dict[str, Any] = {}

@app.get("/health")
async def health():
    return {"ok": True, "service": SERVICE_NAME}

@app.get("/bot/status")
async def bot_status():
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "enabled": BOT_STATE.get("enabled", False),
        "connected": BOT_STATE.get("connected", False),
        "last_error": BOT_STATE.get("last_error"),
        "config": {
            "mention_only": BOT_CONFIG.get("mention_only", True),
            "guild_allowlist": BOT_CONFIG.get("guild_allowlist", []),
            "channel_allowlist": BOT_CONFIG.get("channel_allowlist", []),
            "settings_instance_id": BOT_CONFIG.get("settings_instance_id"),
        },
    }

@app.post("/bot/connect")
async def bot_connect(payload: dict = Body(default=None)):
    payload = payload or {}
    token = (payload.get("token") or "").strip()
    if not token:
        return {"ok": False, "error": "Missing Discord bot token"}
    await start_bot(token, payload)
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "enabled": BOT_STATE.get("enabled", False),
        "connected": BOT_STATE.get("connected", False),
    }

@app.post("/bot/disconnect")
async def bot_disconnect(payload: dict = Body(default=None)):
    await stop_bot()
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "enabled": BOT_STATE.get("enabled", False),
        "connected": BOT_STATE.get("connected", False),
    }

def _string_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


async def _handle_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    if BOT_CLIENT is None or BOT_CLIENT.user is None:
        return

    mention_only = bool(BOT_CONFIG.get("mention_only", True))
    if mention_only and BOT_CLIENT.user not in message.mentions:
        return

    guild_allowlist = set(_string_list(BOT_CONFIG.get("guild_allowlist")))
    channel_allowlist = set(_string_list(BOT_CONFIG.get("channel_allowlist")))
    if guild_allowlist and message.guild and str(message.guild.id) not in guild_allowlist:
        return
    if channel_allowlist and str(message.channel.id) not in channel_allowlist:
        return

    content = message.content or ""
    if mention_only:
        content = content.replace(f"<@{BOT_CLIENT.user.id}>", "").replace(
            f"<@!{BOT_CLIENT.user.id}>", ""
        ).strip()
    if not content:
        return

    user_id = BOT_CONFIG.get("user_id") or os.getenv("BRAINDRIVE_USER_ID", "")
    target_user_id = BOT_CONFIG.get("target_user_id") or None
    settings_instance_id = BOT_CONFIG.get("settings_instance_id") or None
    service_secret = BOT_CONFIG.get("service_secret") or None

    payload = build_message_payload(
        user_id=user_id,
        target_user_id=target_user_id,
        settings_instance_id=settings_instance_id,
        service_secret=service_secret,
        guild_id=str(message.guild.id) if message.guild else None,
        channel_id=str(message.channel.id),
        message_id=str(message.id),
        text=content,
        rag_collection_id=BOT_CONFIG.get("rag_collection_id"),
        model=BOT_CONFIG.get("model"),
        persona_id=BOT_CONFIG.get("persona_id"),
        config=BOT_CONFIG.get("config"),
    )

    try:
        response = await post_discord_message(
            payload,
            api_url=BOT_CONFIG.get("api_url"),
            plugin_slug=BOT_CONFIG.get("plugin_slug"),
            auth_token=BOT_CONFIG.get("auth_token"),
        )
        reply_text = (
            response.get("response")
            if isinstance(response, dict)
            else str(response)
        )
        if reply_text:
            # Discord limits messages to 2000 chars
            for chunk in [reply_text[i:i + 1900] for i in range(0, len(reply_text), 1900)]:
                await message.channel.send(chunk)
        log_message(
            message_id=payload.get("message_id") or "discord-message",
            user_id=target_user_id or user_id,
            guild_id=payload.get("guild_id"),
            channel_id=payload.get("channel_id"),
            prompt=payload.get("text") or "",
            response=reply_text or "",
            rag_collection=payload.get("rag_collection_id"),
            model=payload.get("model"),
            persona_id=payload.get("persona_id"),
        )
    except Exception as exc:
        BOT_STATE["last_error"] = str(exc)


async def _run_bot(token: str) -> None:
    global BOT_CLIENT

    intents = discord.Intents.default()
    intents.guilds = True
    intents.messages = True
    intents.message_content = True

    client = discord.Client(intents=intents)
    BOT_CLIENT = client

    @client.event
    async def on_ready():
        BOT_STATE["connected"] = True
        BOT_STATE["last_error"] = None

    @client.event
    async def on_disconnect():
        BOT_STATE["connected"] = False

    @client.event
    async def on_message(message: discord.Message):
        await _handle_message(message)

    try:
        await client.start(token)
    except Exception as exc:
        BOT_STATE["connected"] = False
        BOT_STATE["last_error"] = str(exc)
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def start_bot(token: str, payload: Dict[str, Any]) -> None:
    global BOT_TASK, BOT_CONFIG
    if BOT_TASK and not BOT_TASK.done():
        if BOT_CONFIG.get("token") == token:
            BOT_STATE["enabled"] = True
            return
        await stop_bot()

    BOT_CONFIG = {
        "token": token,
        "mention_only": bool(payload.get("mention_only", True)),
        "guild_allowlist": payload.get("guild_allowlist") or [],
        "channel_allowlist": payload.get("channel_allowlist") or [],
        "user_id": payload.get("user_id") or os.getenv("BRAINDRIVE_USER_ID", ""),
        "target_user_id": payload.get("target_user_id"),
        "settings_instance_id": payload.get("settings_instance_id"),
        "service_secret": payload.get("service_secret"),
        "rag_collection_id": payload.get("rag_collection_id"),
        "model": payload.get("model"),
        "persona_id": payload.get("persona_id"),
        "config": payload.get("config") or {},
        "api_url": payload.get("api_url") or os.getenv("BRAINDRIVE_API_URL", ""),
        "plugin_slug": payload.get("plugin_slug") or os.getenv("BRAINDRIVE_PLUGIN_SLUG", ""),
        "auth_token": payload.get("auth_token") or os.getenv("BRAINDRIVE_AUTH_TOKEN", ""),
    }

    BOT_STATE["enabled"] = True
    BOT_STATE["connected"] = False
    BOT_STATE["last_error"] = None
    BOT_TASK = asyncio.create_task(_run_bot(token))


async def stop_bot() -> None:
    global BOT_TASK, BOT_CLIENT
    BOT_STATE["enabled"] = False
    BOT_STATE["connected"] = False
    if BOT_CLIENT:
        try:
            await BOT_CLIENT.close()
        except Exception:
            pass
    if BOT_TASK and not BOT_TASK.done():
        BOT_TASK.cancel()
        try:
            await BOT_TASK
        except Exception:
            pass
    BOT_TASK = None
    BOT_CLIENT = None

async def main():
    port = int(os.getenv("PROCESS_PORT", "18150"))
    host = os.getenv("PROCESS_HOST", "0.0.0.0")

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
