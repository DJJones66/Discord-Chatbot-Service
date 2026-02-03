import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "discord_service.db"


def _db_path() -> Path:
    override = os.getenv("DISCORD_SERVICE_DB")
    if override:
        return Path(override).expanduser().resolve()
    return DEFAULT_DB_PATH


def init_db() -> Path:
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discord_guild_config (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                guild_id TEXT,
                guild_name TEXT,
                allowed_channels TEXT,
                allowed_roles TEXT,
                rag_collection TEXT,
                model TEXT,
                persona_id TEXT,
                mention_only INTEGER,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discord_channel_config (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                guild_id TEXT,
                channel_id TEXT,
                enabled INTEGER,
                reply_mode TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discord_message_log (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                guild_id TEXT,
                channel_id TEXT,
                message_id TEXT,
                prompt TEXT,
                response TEXT,
                rag_collection TEXT,
                model TEXT,
                persona_id TEXT,
                created_at TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _execute(query: str, params: tuple) -> None:
    db_path = _db_path()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def upsert_guild_config(
    *,
    user_id: str,
    guild_id: str,
    guild_name: Optional[str] = None,
    allowed_channels: Optional[list] = None,
    allowed_roles: Optional[list] = None,
    rag_collection: Optional[str] = None,
    model: Optional[str] = None,
    persona_id: Optional[str] = None,
    mention_only: Optional[bool] = True,
) -> None:
    record_id = f"{user_id}_{guild_id}"
    _execute(
        """
        INSERT INTO discord_guild_config
        (id, user_id, guild_id, guild_name, allowed_channels, allowed_roles,
         rag_collection, model, persona_id, mention_only, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            guild_name = excluded.guild_name,
            allowed_channels = excluded.allowed_channels,
            allowed_roles = excluded.allowed_roles,
            rag_collection = excluded.rag_collection,
            model = excluded.model,
            persona_id = excluded.persona_id,
            mention_only = excluded.mention_only,
            updated_at = excluded.updated_at
        """,
        (
            record_id,
            user_id,
            guild_id,
            guild_name,
            json.dumps(allowed_channels or []),
            json.dumps(allowed_roles or []),
            rag_collection,
            model,
            persona_id,
            1 if mention_only else 0,
            datetime.utcnow().isoformat(),
        ),
    )


def upsert_channel_config(
    *,
    user_id: str,
    channel_id: str,
    guild_id: Optional[str] = None,
    enabled: bool = True,
    reply_mode: Optional[str] = None,
) -> None:
    record_id = f"{user_id}_{channel_id}"
    _execute(
        """
        INSERT INTO discord_channel_config
        (id, user_id, guild_id, channel_id, enabled, reply_mode, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            guild_id = excluded.guild_id,
            enabled = excluded.enabled,
            reply_mode = excluded.reply_mode,
            updated_at = excluded.updated_at
        """,
        (
            record_id,
            user_id,
            guild_id,
            channel_id,
            1 if enabled else 0,
            reply_mode or "mention_only",
            datetime.utcnow().isoformat(),
        ),
    )


def log_message(
    *,
    message_id: str,
    user_id: str,
    guild_id: Optional[str],
    channel_id: Optional[str],
    prompt: str,
    response: str,
    rag_collection: Optional[str],
    model: Optional[str],
    persona_id: Optional[str],
) -> None:
    _execute(
        """
        INSERT INTO discord_message_log
        (id, user_id, guild_id, channel_id, message_id, prompt, response, rag_collection, model, persona_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"log_{message_id}_{datetime.utcnow().timestamp()}",
            user_id,
            guild_id,
            channel_id,
            message_id,
            prompt,
            response,
            rag_collection,
            model,
            persona_id,
            datetime.utcnow().isoformat(),
        ),
    )
