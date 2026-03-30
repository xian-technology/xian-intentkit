"""Telegram skills."""

import logging
from typing import TypedDict

from intentkit.skills.base import SkillConfig, SkillState
from intentkit.skills.telegram.base import TelegramBaseTool
from intentkit.skills.telegram.send_message import TelegramSendMessage

_cache: dict[str, TelegramBaseTool] = {}

logger = logging.getLogger(__name__)


class SkillStates(TypedDict):
    send_message: SkillState


class Config(SkillConfig):
    """Configuration for Telegram skills."""

    states: SkillStates
    bot_token: str
    default_chat_id: str
    api_base_url: str


async def get_skills(
    config: "Config",
    is_private: bool,
    **_,
) -> list[TelegramBaseTool]:
    available_skills: list[str] = []
    for skill_name, state in config["states"].items():
        if state == "disabled":
            continue
        if state == "public" or (state == "private" and is_private):
            available_skills.append(skill_name)

    result: list[TelegramBaseTool] = []
    for name in available_skills:
        skill = get_telegram_skill(name)
        if skill is not None:
            result.append(skill)
    return result


def get_telegram_skill(name: str) -> TelegramBaseTool | None:
    if name == "send_message":
        if name not in _cache:
            _cache[name] = TelegramSendMessage()
        return _cache[name]
    logger.warning("Unknown Telegram skill: %s", name)
    return None


def available() -> bool:
    return True
