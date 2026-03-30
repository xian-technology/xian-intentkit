from __future__ import annotations

from langchain_core.tools.base import ToolException
from pydantic import BaseModel

from intentkit.skills.base import IntentKitSkill


class TelegramBaseTool(IntentKitSkill):
    """Base class for Telegram tools."""

    category: str = "telegram"

    def get_bot_token(self) -> str:
        context = self.get_context()
        skill_config = context.agent.skill_config(self.category)
        bot_token = skill_config.get("bot_token")
        if not bot_token:
            raise ToolException("Missing required bot_token in configuration")
        return str(bot_token)

    def get_default_chat_id(self) -> str:
        context = self.get_context()
        skill_config = context.agent.skill_config(self.category)
        chat_id = skill_config.get("default_chat_id")
        if not chat_id:
            raise ToolException("Missing required default_chat_id in configuration")
        return str(chat_id)

    def get_api_base_url(self) -> str:
        context = self.get_context()
        skill_config = context.agent.skill_config(self.category)
        raw = skill_config.get("api_base_url")
        return str(raw or "https://api.telegram.org").rstrip("/")


class TelegramMessage(BaseModel):
    chat_id: str
    text: str
    message_id: int | None = None
