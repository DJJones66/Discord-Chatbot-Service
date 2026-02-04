import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discord_conversation (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                discord_user_id TEXT,
                discord_username TEXT,
                guild_id TEXT,
                channel_id TEXT,
                settings_instance_id TEXT,
                scope TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discord_message (
                id TEXT PRIMARY KEY,
                conversation_id TEXT,
                discord_user_id TEXT,
                discord_username TEXT,
                guild_id TEXT,
                channel_id TEXT,
                settings_instance_id TEXT,
                role TEXT,
                content TEXT,
                message_id TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_discord_message_scope_created
            ON discord_message (discord_user_id, guild_id, channel_id, settings_instance_id, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_discord_message_conversation_created
            ON discord_message (conversation_id, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_discord_conversation_scope
            ON discord_conversation (discord_user_id, guild_id, channel_id, settings_instance_id)
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


def _connect() -> sqlite3.Connection:
    db_path = _db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _normalize_id(value: Optional[str]) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _normalize_scope(scope: Optional[str]) -> str:
    normalized = (scope or "channel").strip().lower()
    if normalized not in {"channel", "guild", "dm"}:
        return "channel"
    return normalized


def _conversation_scope_values(
    *,
    scope: Optional[str],
    guild_id: Optional[str],
    channel_id: Optional[str],
    settings_instance_id: Optional[str],
) -> tuple[str, str, str, str]:
    normalized_scope = _normalize_scope(scope)
    guild_value = _normalize_id(guild_id)
    channel_value = _normalize_id(channel_id)
    settings_value = _normalize_id(settings_instance_id)

    if normalized_scope == "guild" and guild_value:
        channel_value = ""
    elif normalized_scope == "dm" and guild_value:
        # For guild messages, fall back to channel scoping.
        normalized_scope = "channel"
    return normalized_scope, guild_value, channel_value, settings_value


def get_or_create_conversation(
    *,
    user_id: str,
    discord_user_id: str,
    discord_username: Optional[str],
    guild_id: Optional[str],
    channel_id: Optional[str],
    settings_instance_id: Optional[str],
    scope: Optional[str] = None,
) -> str:
    discord_user_value = _normalize_id(discord_user_id)
    discord_username_value = _normalize_id(discord_username)
    normalized_scope, guild_value, channel_value, settings_value = _conversation_scope_values(
        scope=scope,
        guild_id=guild_id,
        channel_id=channel_id,
        settings_instance_id=settings_instance_id,
    )
    now = datetime.utcnow().isoformat()
    conn = _connect()
    try:
        cursor = conn.execute(
            """
            SELECT id FROM discord_conversation
            WHERE discord_user_id = ?
              AND guild_id = ?
              AND channel_id = ?
              AND settings_instance_id = ?
            LIMIT 1
            """,
            (discord_user_value, guild_value, channel_value, settings_value),
        )
        row = cursor.fetchone()
        if row:
            convo_id = row["id"]
            conn.execute(
                """
                UPDATE discord_conversation
                SET updated_at = ?, discord_username = ?, scope = ?
                WHERE id = ?
                """,
                (now, discord_username_value, normalized_scope, convo_id),
            )
            conn.commit()
            return convo_id

        convo_id = f"conv_{uuid4().hex}"
        conn.execute(
            """
            INSERT INTO discord_conversation
            (id, user_id, discord_user_id, discord_username, guild_id, channel_id,
             settings_instance_id, scope, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                convo_id,
                user_id,
                discord_user_value,
                discord_username_value,
                guild_value,
                channel_value,
                settings_value,
                normalized_scope,
                now,
                now,
            ),
        )
        conn.commit()
        return convo_id
    finally:
        conn.close()


def insert_message(
    *,
    conversation_id: str,
    role: str,
    content: str,
    message_id: Optional[str],
    discord_user_id: Optional[str],
    discord_username: Optional[str],
    guild_id: Optional[str],
    channel_id: Optional[str],
    settings_instance_id: Optional[str],
) -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO discord_message
            (id, conversation_id, discord_user_id, discord_username, guild_id, channel_id,
             settings_instance_id, role, content, message_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"msg_{uuid4().hex}",
                conversation_id,
                _normalize_id(discord_user_id),
                _normalize_id(discord_username),
                _normalize_id(guild_id),
                _normalize_id(channel_id),
                _normalize_id(settings_instance_id),
                role,
                content,
                _normalize_id(message_id),
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_history(
    *,
    conversation_id: str,
    max_turns: Optional[int] = 6,
    max_age_minutes: Optional[int] = 120,
) -> List[Dict[str, str]]:
    if not conversation_id:
        return []
    try:
        limit = int(max_turns) if max_turns is not None else 0
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        return []
    limit = min(limit, 50)

    params: List[Any] = [conversation_id]
    query = """
        SELECT role, content
        FROM discord_message
        WHERE conversation_id = ?
    """
    if max_age_minutes:
        try:
            age_minutes = int(max_age_minutes)
        except (TypeError, ValueError):
            age_minutes = 0
        if age_minutes > 0:
            cutoff = datetime.utcnow() - timedelta(minutes=age_minutes)
            query += " AND created_at >= ?"
            params.append(cutoff.isoformat())
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    conn = _connect()
    try:
        cursor = conn.execute(query, tuple(params))
        rows = cursor.fetchall()
        history = [
            {"role": row["role"], "content": row["content"]}
            for row in rows
            if row["role"] and row["content"]
        ]
        history.reverse()
        return history
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
