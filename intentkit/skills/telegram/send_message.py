from __future__ import annotations

from typing import Literal

import httpx
from langchain_core.tools import ArgsSchema
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from intentkit.skills.telegram.base import TelegramBaseTool


class TelegramSendMessageInput(BaseModel):
    text: str = Field(..., description="Message text to send to Telegram.")
    chat_id: str | None = Field(
        default=None,
        description=(
            "Optional Telegram chat ID override. If omitted, uses the configured "
            "default chat or group."
        ),
    )
    parse_mode: Literal["HTML", "Markdown", "MarkdownV2"] | None = Field(
        default=None,
        description="Optional Telegram parse mode.",
    )
    disable_web_page_preview: bool = Field(
        default=True,
        description="Disable link previews in the Telegram message.",
    )
    disable_notification: bool = Field(
        default=False,
        description="Send the message silently.",
    )


class TelegramSendMessage(TelegramBaseTool):
    """Tool for sending a Telegram message to a configured group or chat."""

    name: str = "telegram_send_message"
    description: str = "Send a message to a Telegram chat or group."
    args_schema: ArgsSchema | None = TelegramSendMessageInput

    async def _arun(
        self,
        text: str,
        chat_id: str | None = None,
        parse_mode: Literal["HTML", "Markdown", "MarkdownV2"] | None = None,
        disable_web_page_preview: bool = True,
        disable_notification: bool = False,
        **kwargs,
    ) -> str:
        bot_token = self.get_bot_token()
        target_chat_id = chat_id or self.get_default_chat_id()
        url = f"{self.get_api_base_url()}/bot{bot_token}/sendMessage"
        payload: dict[str, str | bool] = {
            "chat_id": target_chat_id,
            "text": text[:4096],
            "disable_web_page_preview": disable_web_page_preview,
            "disable_notification": disable_notification,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise ToolException(f"Error sending Telegram message: {exc}") from exc

        if not isinstance(body, dict) or not body.get("ok", False):
            raise ToolException(f"Telegram sendMessage failed with response: {body!r}")
        result = body.get("result") or {}
        message_id = result.get("message_id")
        return f"Telegram message sent successfully to {target_chat_id}." + (
            f" Message ID: {message_id}." if message_id is not None else ""
        )
