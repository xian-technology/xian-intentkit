from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web

from intentkit.abstracts.graph import AgentContext
from intentkit.models.chat import AuthorType
from intentkit.skills.twitter.post_tweet import TwitterPostTweet


class _TestAgent:
    def __init__(self, webhook_url: str) -> None:
        self.skills = {
            "twitter": {
                "enabled": True,
                "states": {"post_tweet": "private"},
                "mock_webhook_url": webhook_url,
            }
        }

    def skill_config(self, category: str):
        return self.skills.get(category, {})


@pytest.mark.asyncio
async def test_twitter_post_tweet_uses_mock_webhook_when_configured():
    captured: list[dict] = []

    async def _handle(request: web.Request) -> web.Response:
        payload = await request.json()
        captured.append(payload)
        return web.json_response({"ok": True, "id": "tweet-1"})

    app = web.Application()
    app.router.add_post("/twitter", _handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = getattr(site._server, "sockets", None)  # pyright: ignore[reportPrivateUsage]
    port = sockets[0].getsockname()[1]
    webhook_url = f"http://127.0.0.1:{port}/twitter"

    try:
        tool = TwitterPostTweet()
        agent = _TestAgent(webhook_url)
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
            result = await tool._arun(text="Hello X")
        assert "Tweet captured by mock webhook" in result
        assert captured[0]["agent_id"] == "agent-1"
        assert captured[0]["text"] == "Hello X"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_twitter_post_tweet_supports_linked_account_mode_without_self_keys():
    tool = TwitterPostTweet()

    class _LinkedAgent:
        skills = {
            "twitter": {
                "enabled": True,
                "auth_mode": "linked_account",
                "states": {"post_tweet": "private"},
            }
        }

        def skill_config(self, category: str):
            return self.skills.get(category, {})

    fake_client = AsyncMock()
    fake_client.create_tweet = AsyncMock(return_value={"data": {"id": "tweet-2"}})

    class _FakeTwitter:
        use_key = False

        async def get_client(self):
            return fake_client

    context = AgentContext(
        agent_id="agent-linked",
        get_agent=lambda: _LinkedAgent(),
        chat_id="chat-1",
        user_id="user-1",
        entrypoint=AuthorType.TRIGGER,
        is_private=True,
    )

    with (
        patch(
            "intentkit.skills.base.IntentKitSkill.get_context",
            return_value=context,
        ),
        patch(
            "intentkit.skills.twitter.post_tweet.get_twitter_client",
            return_value=_FakeTwitter(),
        ),
        patch.object(
            TwitterPostTweet,
            "check_rate_limit",
            AsyncMock(return_value=None),
        ) as check_rate_limit,
    ):
        result = await tool._arun(text="Hello from linked account mode")

    assert "Tweet posted successfully" in result
    fake_client.create_tweet.assert_awaited_once()
    check_rate_limit.assert_awaited_once()
