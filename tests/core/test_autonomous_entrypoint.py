from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_run_autonomous_task_creates_chat_when_missing(monkeypatch):
    from intentkit.models.chat import AuthorType

    from app.entrypoints import autonomous as module

    monkeypatch.setattr(
        module,
        "get_agent",
        AsyncMock(return_value=SimpleNamespace(name="Agent", picture=None)),
    )
    monkeypatch.setattr(module.Chat, "get", AsyncMock(return_value=None))
    saved_chat = AsyncMock()
    monkeypatch.setattr(module.ChatCreate, "save", saved_chat)
    monkeypatch.setattr(module, "clear_thread_memory", AsyncMock())
    monkeypatch.setattr(module, "create_agent_activity", AsyncMock())

    captured_messages = []

    async def fake_execute_agent(message):
        captured_messages.append(message)
        return [
            SimpleNamespace(
                author_type=AuthorType.AGENT,
                message="done",
            )
        ]

    monkeypatch.setattr(module, "execute_agent", fake_execute_agent)

    await module.run_autonomous_task(
        agent_id="agent-1",
        agent_owner="system",
        task_id="task-1",
        prompt="Run now",
        has_memory=True,
    )

    saved_chat.assert_awaited_once()
    assert captured_messages
    assert captured_messages[0].chat_id == "autonomous-task-1"


@pytest.mark.asyncio
async def test_run_autonomous_task_reuses_existing_chat(monkeypatch):
    from intentkit.models.chat import AuthorType

    from app.entrypoints import autonomous as module

    monkeypatch.setattr(
        module,
        "get_agent",
        AsyncMock(return_value=SimpleNamespace(name="Agent", picture=None)),
    )
    monkeypatch.setattr(
        module.Chat,
        "get",
        AsyncMock(
            return_value=SimpleNamespace(
                id="autonomous-task-1",
                agent_id="agent-1",
                user_id="system",
            )
        ),
    )
    saved_chat = AsyncMock()
    monkeypatch.setattr(module.ChatCreate, "save", saved_chat)
    monkeypatch.setattr(module, "clear_thread_memory", AsyncMock())
    monkeypatch.setattr(module, "create_agent_activity", AsyncMock())

    async def fake_execute_agent(message):
        return [
            SimpleNamespace(
                author_type=AuthorType.AGENT,
                message=message.message,
            )
        ]

    monkeypatch.setattr(module, "execute_agent", fake_execute_agent)

    await module.run_autonomous_task(
        agent_id="agent-1",
        agent_owner="system",
        task_id="task-1",
        prompt="Run now",
        has_memory=False,
    )

    saved_chat.assert_not_awaited()
    module.clear_thread_memory.assert_awaited_once_with(
        "agent-1",
        "autonomous-task-1",
    )
