import os
import asyncio
import traceback
import time
from typing import Any, Dict, Optional, List

import discord
import httpx
from fastapi import FastAPI, Body
import uvicorn

from db import (
    init_db,
    log_message,
    get_or_create_conversation,
    get_recent_history,
    insert_message,
)
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


def _log(msg: str) -> None:
    print(f"[discord_service] {msg}", flush=True)


async def _refresh_auth_token() -> bool:
    refresh_token = BOT_CONFIG.get("refresh_token")
    api_url = (BOT_CONFIG.get("api_url") or "").rstrip("/")
    if not refresh_token or not api_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{api_url}/api/v1/auth/refresh",
                json={"refresh_token": refresh_token},
            )
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
        new_access = data.get("access_token")
        new_refresh = data.get("refresh_token")
        if new_access:
            BOT_CONFIG["auth_token"] = new_access
        if new_refresh:
            BOT_CONFIG["refresh_token"] = new_refresh
        _log("Refreshed BrainDrive auth token")
        return bool(new_access)
    except Exception as exc:
        _log(f"Auth refresh failed: {exc!r}")
        return False

@app.get("/health")
async def health():
    return {"ok": True, "service": SERVICE_NAME}

@app.get("/bot/status")
async def bot_status():
    _log("Status check requested")
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
        _log("Connect requested without token")
        return {"ok": False, "error": "Missing Discord bot token"}
    _log(
        "Connect requested "
        f"(mention_only={bool(payload.get('mention_only', True))}, "
        f"guild_allowlist={payload.get('guild_allowlist') or []}, "
        f"channel_allowlist={payload.get('channel_allowlist') or []}, "
        f"settings_instance_id={payload.get('settings_instance_id')}, "
        f"user_id={payload.get('user_id')}, "
        f"target_user_id={payload.get('target_user_id')}, "
        f"api_url={payload.get('api_url')}, "
        f"plugin_slug={payload.get('plugin_slug')})"
    )
    await start_bot(token, payload)
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "enabled": BOT_STATE.get("enabled", False),
        "connected": BOT_STATE.get("connected", False),
    }

@app.post("/bot/disconnect")
async def bot_disconnect(payload: dict = Body(default=None)):
    _log("Disconnect requested")
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


def _normalize_history_config(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return raw


def _history_settings() -> Dict[str, Any]:
    history_cfg = _normalize_history_config(BOT_CONFIG.get("history"))
    if not history_cfg:
        history_cfg = _normalize_history_config(
            (BOT_CONFIG.get("config") or {}).get("history")
        )
    return history_cfg


async def _handle_message(message: discord.Message) -> None:
    _log(
        "Incoming message "
        f"id={message.id} author={message.author} "
        f"guild={getattr(message.guild, 'id', None)} "
        f"channel={getattr(message.channel, 'id', None)}"
    )
    if message.author.bot:
        _log("Ignoring bot message")
        return

    if BOT_CLIENT is None or BOT_CLIENT.user is None:
        _log("No bot client available for message handling")
        return

    mention_only = bool(BOT_CONFIG.get("mention_only", True))
    if mention_only and BOT_CLIENT.user not in message.mentions:
        _log("Ignoring message: mention-only enabled and bot not mentioned")
        return

    guild_allowlist = set(_string_list(BOT_CONFIG.get("guild_allowlist")))
    channel_allowlist = set(_string_list(BOT_CONFIG.get("channel_allowlist")))
    if guild_allowlist and message.guild and str(message.guild.id) not in guild_allowlist:
        _log(f"Ignoring message: guild {message.guild.id} not in allowlist")
        return
    if channel_allowlist and str(message.channel.id) not in channel_allowlist:
        _log(f"Ignoring message: channel {message.channel.id} not in allowlist")
        return

    content = message.content or ""
    if mention_only:
        content = content.replace(f"<@{BOT_CLIENT.user.id}>", "").replace(
            f"<@!{BOT_CLIENT.user.id}>", ""
        ).strip()
    if not content:
        _log("Ignoring message: empty content after mention cleanup")
        return

    _log(f"Processing message {message.id} from {message.author} in channel {message.channel.id}")

    user_id = BOT_CONFIG.get("user_id") or os.getenv("BRAINDRIVE_USER_ID", "")
    target_user_id = BOT_CONFIG.get("target_user_id") or None
    settings_instance_id = BOT_CONFIG.get("settings_instance_id") or None
    service_secret = BOT_CONFIG.get("service_secret") or None

    history_cfg = _history_settings()
    history_enabled = bool(history_cfg.get("enabled", True))
    history_scope = history_cfg.get("scope") or history_cfg.get("history_scope") or "channel"
    history_max_turns = history_cfg.get("max_turns")
    if history_max_turns is None:
        history_max_turns = history_cfg.get("max_history_turns")
    if history_max_turns is None:
        history_max_turns = 6
    history_max_age = history_cfg.get("max_age_minutes")
    if history_max_age is None:
        history_max_age = history_cfg.get("max_history_age_minutes")
    if history_max_age is None:
        history_max_age = 120

    discord_user_id = str(message.author.id)
    discord_username = str(message.author)
    guild_id = str(message.guild.id) if message.guild else None
    channel_id = str(message.channel.id)

    conversation_id = get_or_create_conversation(
        user_id=target_user_id or user_id,
        discord_user_id=discord_user_id,
        discord_username=discord_username,
        guild_id=guild_id,
        channel_id=channel_id,
        settings_instance_id=settings_instance_id,
        scope=history_scope,
    )
    chat_history = (
        get_recent_history(
            conversation_id=conversation_id,
            max_turns=history_max_turns,
            max_age_minutes=history_max_age,
        )
        if history_enabled
        else []
    )

    payload = build_message_payload(
        user_id=user_id,
        target_user_id=target_user_id,
        settings_instance_id=settings_instance_id,
        service_secret=service_secret,
        guild_id=guild_id,
        channel_id=channel_id,
        message_id=str(message.id),
        text=content,
        rag_collection_id=BOT_CONFIG.get("rag_collection_id"),
        model=BOT_CONFIG.get("model"),
        persona_id=BOT_CONFIG.get("persona_id"),
        config=BOT_CONFIG.get("config"),
        chat_history=chat_history,
    )

    try:
        try:
            insert_message(
                conversation_id=conversation_id,
                role="user",
                content=payload.get("text") or "",
                message_id=payload.get("message_id"),
                discord_user_id=discord_user_id,
                discord_username=discord_username,
                guild_id=guild_id,
                channel_id=channel_id,
                settings_instance_id=settings_instance_id,
            )
        except Exception as exc:
            _log(f"Failed to store user message history: {exc!r}")

        start_time = time.monotonic()
        _log("Posting message to BrainDrive plugin endpoint")
        try:
            response = await post_discord_message(
                payload,
                api_url=BOT_CONFIG.get("api_url"),
                plugin_slug=BOT_CONFIG.get("plugin_slug"),
                auth_token=BOT_CONFIG.get("auth_token"),
            )
        except RuntimeError as exc:
            if "401" in str(exc) and await _refresh_auth_token():
                response = await post_discord_message(
                    payload,
                    api_url=BOT_CONFIG.get("api_url"),
                    plugin_slug=BOT_CONFIG.get("plugin_slug"),
                    auth_token=BOT_CONFIG.get("auth_token"),
                )
            else:
                raise
        elapsed = time.monotonic() - start_time
        _log(f"BrainDrive response received in {elapsed:.2f}s")
        reply_text = (
            response.get("response")
            if isinstance(response, dict)
            else str(response)
        )
        _log(f"Received BrainDrive response length={len(reply_text or '')}")
        if reply_text:
            # Discord limits messages to 2000 chars
            chunks = [reply_text[i:i + 1900] for i in range(0, len(reply_text), 1900)]
            for index, chunk in enumerate(chunks, start=1):
                await message.channel.send(chunk)
                _log(f"Sent reply chunk {index}/{len(chunks)} to channel {message.channel.id}")
        else:
            _log("No reply text returned from BrainDrive")
        try:
            insert_message(
                conversation_id=conversation_id,
                role="assistant",
                content=reply_text or "",
                message_id=payload.get("message_id"),
                discord_user_id=discord_user_id,
                discord_username=discord_username,
                guild_id=guild_id,
                channel_id=channel_id,
                settings_instance_id=settings_instance_id,
            )
        except Exception as exc:
            _log(f"Failed to store assistant message history: {exc!r}")
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
        _log("Logged message to SQLite store")
    except Exception as exc:
        BOT_STATE["last_error"] = repr(exc)
        _log(f"Error handling message: {exc!r}")
        _log(traceback.format_exc())


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
        _log(f"Bot connected as {client.user} in {len(client.guilds)} guild(s)")

    @client.event
    async def on_disconnect():
        BOT_STATE["connected"] = False
        _log("Bot disconnected")

    @client.event
    async def on_message(message: discord.Message):
        await _handle_message(message)

    @client.event
    async def on_error(event, *args, **kwargs):
        _log(f"Discord client error event={event} args={args} kwargs={kwargs}")

    try:
        await client.start(token)
    except Exception as exc:
        BOT_STATE["connected"] = False
        BOT_STATE["last_error"] = str(exc)
        _log(f"Bot failed to start: {exc}")
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
        "history": payload.get("history") or {},
        "config": payload.get("config") or {},
        "api_url": payload.get("api_url") or os.getenv("BRAINDRIVE_API_URL", ""),
        "plugin_slug": payload.get("plugin_slug") or os.getenv("BRAINDRIVE_PLUGIN_SLUG", ""),
        "auth_token": payload.get("auth_token") or os.getenv("BRAINDRIVE_AUTH_TOKEN", ""),
        "refresh_token": payload.get("refresh_token") or os.getenv("BRAINDRIVE_REFRESH_TOKEN", ""),
    }

    BOT_STATE["enabled"] = True
    BOT_STATE["connected"] = False
    BOT_STATE["last_error"] = None
    _log(
        "Starting bot "
        f"(mention_only={BOT_CONFIG.get('mention_only')}, "
        f"guild_allowlist={BOT_CONFIG.get('guild_allowlist')}, "
        f"channel_allowlist={BOT_CONFIG.get('channel_allowlist')})"
    )
    BOT_TASK = asyncio.create_task(_run_bot(token))


async def stop_bot() -> None:
    global BOT_TASK, BOT_CLIENT
    BOT_STATE["enabled"] = False
    BOT_STATE["connected"] = False
    _log("Stopping bot")
    if BOT_CLIENT:
        try:
            await BOT_CLIENT.close()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    if BOT_TASK and not BOT_TASK.done():
        BOT_TASK.cancel()
        try:
            await BOT_TASK
        except asyncio.CancelledError:
            pass
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
