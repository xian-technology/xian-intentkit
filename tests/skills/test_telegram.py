from unittest.mock import patch

import pytest
from aiohttp import web

from intentkit.abstracts.graph import AgentContext
from intentkit.models.chat import AuthorType
from intentkit.skills.telegram.send_message import TelegramSendMessage


class _TestAgent:
    def __init__(self, base_url: str) -> None:
        self.skills = {
            "telegram": {
                "enabled": True,
                "states": {"send_message": "private"},
                "bot_token": "bot-token",
                "default_chat_id": "-100123",
                "api_base_url": base_url,
            }
        }

    def skill_config(self, category: str):
        return self.skills.get(category, {})


@pytest.mark.asyncio
async def test_telegram_send_message_posts_to_configured_chat():
    captured: list[dict] = []

    async def _handle(request: web.Request) -> web.Response:
        payload = await request.json()
        captured.append(payload)
        return web.json_response({"ok": True, "result": {"message_id": 7}})

    app = web.Application()
    app.router.add_post(r"/bot{token}/sendMessage", _handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = getattr(site._server, "sockets", None)  # pyright: ignore[reportPrivateUsage]
    port = sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    try:
        tool = TelegramSendMessage()
        agent = _TestAgent(base_url)
        context = AgentContext(
            agent_id="agent-1",
            get_agent=lambda: agent,
            chat_id="chat-1",
            user_id="user-1",
            entrypoint=AuthorType.TRIGGER,
            is_private=True,
        )
        with patch(
            "intentkit.skills.base.IntentKitSkill.get_context",
            return_value=context,
        ):
            result = await tool._arun(text="Hello Telegram")
        assert "Telegram message sent successfully" in result
        assert captured[0]["chat_id"] == "-100123"
        assert captured[0]["text"] == "Hello Telegram"
    finally:
        await runner.cleanup()
