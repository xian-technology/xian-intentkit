from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from aiohttp import web
from xian_py.models import IndexedEvent

from intentkit.abstracts.graph import AgentContext
from intentkit.core.xian_event_triggers import XianEventTask, XianEventTriggerService
from intentkit.models.agent.autonomous import XianEventTrigger
from intentkit.models.chat import AuthorType
from intentkit.skills.telegram.send_message import TelegramSendMessage
from intentkit.skills.twitter.post_tweet import TwitterPostTweet
from intentkit.skills.xian.dex_trade import XianDexTrade


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def exists(self, key: str) -> bool:
        return key in self.values

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value):
        self.values[key] = str(value)

    async def delete(self, key: str):
        self.values.pop(key, None)


class FakeClient:
    def __init__(self, batches: list[list[IndexedEvent]]) -> None:
        self._batches = list(batches)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def list_events(self, contract, event, limit=100, after_id=None):
        if self._batches:
            return self._batches.pop(0)
        return []


def _indexed_event(
    *,
    event_id: int,
    payload: dict[str, Any],
    contract: str = "currency",
    event: str = "Transfer",
) -> IndexedEvent:
    return IndexedEvent.from_dict(
        {
            "id": event_id,
            "contract": contract,
            "event": event,
            "data_indexed": payload,
            "tx_hash": f"tx-{event_id}",
            "block_height": 100 + event_id,
        }
    )


@dataclass
class TestAgent:
    id: str
    network_id: str
    wallet_provider: str
    skills: dict[str, dict[str, Any]]

    def skill_config(self, category: str) -> dict[str, Any]:
        return self.skills.get(category, {})


@dataclass
class FakeDexProvider:
    address: str = "xian-test-wallet"
    trade_calls: list[dict[str, Any]] = field(default_factory=list)

    async def get_state(self, contract: str, variable: str, *keys: str) -> Any:
        if contract == "con_pairs" and variable == "toks_to_pair":
            return 9
        if contract == "con_pairs" and variable == "pairs" and keys == (9, "reserve0"):
            return 1000
        if contract == "con_pairs" and variable == "pairs" and keys == (9, "reserve1"):
            return 500
        if contract == "con_dex" and variable == "zero_fee_signers":
            return False
        raise AssertionError(f"unexpected state lookup: {contract}.{variable} {keys}")

    async def call_contract(
        self,
        contract: str,
        function: str,
        kwargs: dict[str, Any],
    ) -> Any:
        if contract == "con_pairs" and function == "getReserves":
            return [1000, 500, 0]
        if contract == "con_dex" and function == "getTradeFeeBps":
            return 30
        if contract == "con_dex" and function == "getAmountOut":
            return 45
        raise AssertionError(f"unexpected call: {contract}.{function} {kwargs}")

    async def get_allowance(
        self,
        *,
        token: str,
        spender: str,
        owner: str | None = None,
    ):
        return 10_000

    async def send_contract_transaction(
        self,
        *,
        contract: str,
        function: str,
        kwargs: dict[str, Any],
        stamps: int | None = None,
        nonce: int | None = None,
        mode: str | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> Any:
        self.trade_calls.append(
            {
                "contract": contract,
                "function": function,
                "kwargs": kwargs,
                "mode": mode,
                "wait_for_tx": wait_for_tx,
            }
        )
        return SimpleNamespace(
            tx_hash="trade-123",
            mode=mode or "commit",
            accepted=True,
            finalized=True,
            message=None,
            receipt=None,
        )


class MockSocialSink:
    def __init__(self) -> None:
        self.telegram_payloads: list[dict[str, Any]] = []
        self.twitter_payloads: list[dict[str, Any]] = []
        self._runner: web.AppRunner | None = None
        self.base_url: str | None = None

    async def __aenter__(self) -> "MockSocialSink":
        app = web.Application()
        app.router.add_post(r"/bot{token}/sendMessage", self._handle_telegram)
        app.router.add_post("/twitter", self._handle_twitter)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        sockets = getattr(site._server, "sockets", None)  # pyright: ignore[reportPrivateUsage]
        port = sockets[0].getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._runner is not None:
            await self._runner.cleanup()

    async def _handle_telegram(self, request: web.Request) -> web.Response:
        payload = await request.json()
        self.telegram_payloads.append(payload)
        return web.json_response(
            {
                "ok": True,
                "result": {
                    "message_id": len(self.telegram_payloads),
                    "chat": {"id": payload.get("chat_id")},
                    "text": payload.get("text"),
                },
            }
        )

    async def _handle_twitter(self, request: web.Request) -> web.Response:
        payload = await request.json()
        self.twitter_payloads.append(payload)
        return web.json_response(
            {"ok": True, "id": f"tweet-{len(self.twitter_payloads)}"}
        )


def _extract_event_context(prompt: str) -> dict[str, Any]:
    marker = "payload before deciding what to do.\n"
    suffix = "\n\nOriginal autonomous task instructions:\n"
    context_json = prompt.split(marker, 1)[1].split(suffix, 1)[0]
    return json.loads(context_json)


def _extract_tx_hash(result: str) -> str | None:
    match = re.search(r"Transaction hash: ([A-Za-z0-9-]+)", result)
    return match.group(1) if match else None


async def _workflow_runner(
    *,
    agent: TestAgent,
    provider: FakeDexProvider,
    threshold_pct: float,
    prompt: str,
    acted_on_event_ids: list[int],
) -> None:
    context_payload = _extract_event_context(prompt)
    price_change = float(context_payload["payload"].get("price_change_pct", 0))
    if price_change < threshold_pct:
        return

    acted_on_event_ids.append(int(context_payload["event_id"]))

    context = AgentContext(
        agent_id=agent.id,
        get_agent=lambda: agent,
        chat_id="autonomous-workflow-test",
        user_id="system",
        entrypoint=AuthorType.TRIGGER,
        is_private=True,
    )

    trade_tool = XianDexTrade()
    telegram_tool = TelegramSendMessage()
    twitter_tool = TwitterPostTweet()

    with (
        patch("intentkit.skills.base.IntentKitSkill.get_context", return_value=context),
        patch.object(
            XianDexTrade,
            "get_xian_provider",
            new=AsyncMock(return_value=provider),
        ),
    ):
        trade_result = await trade_tool._arun(
            side="sell",
            buy_token="con_token",
            sell_token="currency",
            amount=str(context_payload["payload"].get("sell_amount", "25")),
            auto_approve=False,
            mode="commit",
            wait_for_tx=True,
        )
        trade_tx_hash = _extract_tx_hash(trade_result) or "unknown"
        message = (
            "IntentKit workflow test: auto-sell executed on Xian after "
            f"{price_change}% price change. Trade tx: {trade_tx_hash}."
        )
        await telegram_tool._arun(text=message)
        await twitter_tool._arun(text=message)


async def run_trade_social_workflow_test(
    *, threshold_pct: float = 3.0
) -> dict[str, Any]:
    redis = FakeRedis()
    service = XianEventTriggerService(redis, batch_limit=10, poll_interval_seconds=1.0)
    provider = FakeDexProvider()
    acted_on_event_ids: list[int] = []

    async with MockSocialSink() as sink:
        agent = TestAgent(
            id="agent-xian-trade-social",
            network_id="xian-localnet",
            wallet_provider="xian",
            skills={
                "telegram": {
                    "enabled": True,
                    "states": {"send_message": "private"},
                    "bot_token": "test-bot-token",
                    "default_chat_id": "-1001234567890",
                    "api_base_url": sink.base_url,
                },
                "twitter": {
                    "enabled": True,
                    "states": {"post_tweet": "private"},
                    "mock_webhook_url": f"{sink.base_url}/twitter",
                },
                "xian": {
                    "enabled": True,
                    "states": {"xian_dex_trade": "private"},
                },
            },
        )

        task = XianEventTask(
            runtime_id=f"{agent.id}-task-1",
            agent_id=agent.id,
            agent_owner="system",
            agent_name="Workflow Test Agent",
            network_id="xian-localnet",
            task_id="task-1",
            prompt=(
                "If the indexed event shows price_change_pct above the threshold, "
                "sell currency on the Xian DEX and announce the result."
            ),
            has_memory=False,
            trigger=XianEventTrigger(
                contract="currency",
                event="Transfer",
                cooldown_seconds=0,
            ),
        )

        fake_client = FakeClient(
            [
                [
                    _indexed_event(
                        event_id=1,
                        payload={
                            "price_change_pct": "1.5",
                            "sell_amount": "25",
                            "pair": "currency/con_token",
                        },
                    ),
                    _indexed_event(
                        event_id=2,
                        payload={
                            "price_change_pct": "6.4",
                            "sell_amount": "25",
                            "pair": "currency/con_token",
                        },
                    ),
                ]
            ]
        )

        async def _patched_run_autonomous_task(
            agent_id: str,
            agent_owner: str,
            task_id: str,
            prompt: str,
            has_memory: bool = True,
        ) -> None:
            await _workflow_runner(
                agent=agent,
                provider=provider,
                threshold_pct=threshold_pct,
                prompt=prompt,
                acted_on_event_ids=acted_on_event_ids,
            )

        with patch.object(service, "_xian_client", lambda network_id: fake_client):
            with patch(
                "intentkit.core.xian_event_triggers.run_autonomous_task",
                _patched_run_autonomous_task,
            ):
                with patch(
                    "intentkit.core.xian_event_triggers.update_autonomous_task_status",
                    new=AsyncMock(),
                ):
                    await redis.set(task.cursor_key, 0)
                    await service._sync_task(task)

        return {
            "threshold_pct": threshold_pct,
            "acted_on_event_ids": acted_on_event_ids,
            "trade_calls": provider.trade_calls,
            "telegram_payloads": sink.telegram_payloads,
            "twitter_payloads": sink.twitter_payloads,
            "final_cursor": await redis.get(task.cursor_key),
        }


def main() -> None:
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("intentkit.core.xian_event_triggers").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(
        description=(
            "Run a deterministic IntentKit workflow test: Xian event trigger -> "
            "DEX sell -> Telegram post -> X post."
        )
    )
    parser.add_argument(
        "--threshold-pct",
        type=float,
        default=3.0,
        help="Minimum price_change_pct required before the workflow acts.",
    )
    args = parser.parse_args()
    summary = asyncio.run(
        run_trade_social_workflow_test(threshold_pct=args.threshold_pct)
    )
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
