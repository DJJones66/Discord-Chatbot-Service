# Discord Chatbot Service (Skeleton)

This is a minimal service runtime for the BrainDrive Discord Chatbot plugin.
It is intended to be managed by BrainDrive's service runtime system (venv_process).

## Files
- `service.py` - FastAPI app with `/health` plus placeholders for Discord bot logic
- `requirements.txt` - Python deps (discord.py + FastAPI + uvicorn)
- `service_scripts/` - venv helpers used by BrainDrive
- `client.py` - tiny helper for calling the BrainDrive plugin `/discord/message` endpoint

## Local dev
```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python service.py
```

## Bot call contract (payload)
Send POST to:
`/api/v1/plugin-api/BrainDriveDiscordChatbotCommunity/discord/message`

Example payload:
```json
{
  "user_id": "USER_ID",
  "guild_id": "123",
  "channel_id": "456",
  "message_id": "789",
  "text": "What is our refund policy?",
  "rag_collection_id": "T1",
  "model": "llama3.1:8b",
  "persona_id": "",
  "config": {
    "default_model": "llama3.1:8b",
    "default_rag_collection": "T1",
    "persona_id": ""
  }
}
```

Authentication:
- Provide `BRAINDRIVE_AUTH_TOKEN` and `BRAINDRIVE_API_URL` in `.env`.
