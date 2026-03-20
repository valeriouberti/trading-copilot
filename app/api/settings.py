"""Settings API endpoints — Telegram configuration (persisted to database)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.models.database import get_telegram_config, upsert_telegram_config
from app.services.notifier import TelegramNotifier

router = APIRouter()


class TelegramConfigBody(BaseModel):
    bot_token: str = ""
    chat_id: str = ""
    enabled: bool = False


@router.get("/settings/telegram")
async def get_telegram_settings(request: Request):
    """Return current Telegram configuration (token masked)."""
    tg = await get_telegram_config(request.app.state.session_factory)
    token = tg.get("bot_token", "")
    masked = f"...{token[-8:]}" if len(token) > 8 else ("set" if token else "")
    return {
        "bot_token_masked": masked,
        "chat_id": str(tg.get("chat_id", "")),
        "enabled": tg.get("enabled", False),
    }


@router.put("/settings/telegram")
async def update_telegram_settings(request: Request, body: TelegramConfigBody):
    """Update Telegram configuration in database."""
    await upsert_telegram_config(
        request.app.state.session_factory,
        body.bot_token,
        body.chat_id,
        body.enabled,
    )

    # Update in-memory config dict for notifier
    request.app.state.config["telegram"] = {
        "bot_token": body.bot_token,
        "chat_id": body.chat_id,
        "enabled": body.enabled,
    }

    return {"message": "Telegram settings updated", "enabled": body.enabled}


@router.post("/telegram/test")
async def test_telegram(request: Request):
    """Send a test message to the configured Telegram chat."""
    tg = await get_telegram_config(request.app.state.session_factory)

    if not tg.get("bot_token") or not tg.get("chat_id"):
        raise HTTPException(
            status_code=400,
            detail="Telegram not configured — set bot_token and chat_id first",
        )

    notifier = TelegramNotifier(
        bot_token=tg["bot_token"],
        chat_id=str(tg["chat_id"]),
        enabled=True,
    )

    sent = await notifier.send_test()
    if not sent:
        raise HTTPException(status_code=502, detail="Failed to send test message")

    return {"message": "Test message sent successfully"}
