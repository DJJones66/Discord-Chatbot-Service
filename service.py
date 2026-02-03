import os
import asyncio
from fastapi import FastAPI
import uvicorn

from db import init_db, log_message

from client import build_message_payload, post_discord_message

app = FastAPI()

SERVICE_NAME = "discord_chatbot_service"

init_db()

@app.get("/health")
async def health():
    return {"ok": True, "service": SERVICE_NAME}

async def run_discord_bot():
    """
    Minimal bot loop stub with a sample call to BrainDrive.
    Replace this with real discord.py event handlers.
    """
    example_sent = False
    stub_enabled = os.getenv("BOT_STUB_CALL_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    while True:
        if stub_enabled and not example_sent:
            example_sent = True
            user_id = os.getenv("BRAINDRIVE_USER_ID", "")
            target_user_id = os.getenv("BRAINDRIVE_TARGET_USER_ID", "") or None
            settings_instance_id = os.getenv("DISCORD_SETTINGS_INSTANCE_ID", "") or None
            service_secret = os.getenv("DISCORD_SERVICE_SECRET", "") or None
            if user_id:
                payload = build_message_payload(
                    user_id=user_id,
                    target_user_id=target_user_id,
                    settings_instance_id=settings_instance_id,
                    service_secret=service_secret,
                    guild_id="example-guild",
                    channel_id="example-channel",
                    message_id="example-message",
                    text="Test message from Discord bot stub",
                    rag_collection_id="T1",
                    model="llama3.1:8b",
                    persona_id="",
                    config={
                        "default_model": "llama3.1:8b",
                        "default_rag_collection": "T1",
                        "persona_id": ""
                    }
                )
                try:
                    response = await post_discord_message(payload)
                    print("Discord bot stub response:", response)
                    log_message(
                        message_id=payload.get("message_id") or "stub-message",
                        user_id=target_user_id or user_id,
                        guild_id=payload.get("guild_id"),
                        channel_id=payload.get("channel_id"),
                        prompt=payload.get("text") or "",
                        response=response.get("response") if isinstance(response, dict) else str(response),
                        rag_collection=payload.get("rag_collection_id"),
                        model=payload.get("model"),
                        persona_id=payload.get("persona_id"),
                    )
                except Exception as exc:
                    print("Discord bot stub call failed:", exc)

        await asyncio.sleep(5)

async def main():
    # Start Discord bot stub in background
    asyncio.create_task(run_discord_bot())

    port = int(os.getenv("PROCESS_PORT", "18150"))
    host = os.getenv("PROCESS_HOST", "0.0.0.0")

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
