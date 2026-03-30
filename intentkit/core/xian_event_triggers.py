from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import aiohttp
from redis.asyncio import Redis
from xian_py import XianAsync
from xian_py.models import IndexedEvent
from xian_py.projectors import merged_event_payload

from intentkit.config.config import config
from intentkit.core.autonomous import update_autonomous_task_status
from intentkit.models.agent import Agent, AgentAutonomousStatus
from intentkit.models.agent.autonomous import (
    AgentAutonomousTriggerType,
    XianDexPriceChangeTrigger,
    XianEventTrigger,
)
from intentkit.wallets.xian_networks import get_xian_network_config, is_xian_network

from app.entrypoints.autonomous import run_autonomous_task

logger = logging.getLogger(__name__)

_SUBSCRIBE_TX = json.dumps(
    {
        "jsonrpc": "2.0",
        "method": "subscribe",
        "id": 1,
        "params": {"query": "tm.event='Tx'"},
    }
)

_RECONNECT_DELAYS = [1, 2, 4, 8, 16, 30]
_CURSOR_PREFIX = "intentkit:xian_event_trigger:cursor:"
_LAST_RUN_PREFIX = "intentkit:xian_event_trigger:last_run:"
_DEX_BASELINE_PREFIX = "intentkit:xian_event_trigger:dex_baseline:"


@dataclass(frozen=True)
class XianEventTask:
    runtime_id: str
    agent_id: str
    agent_owner: str
    agent_name: str | None
    network_id: str
    task_id: str
    prompt: str
    has_memory: bool
    trigger: XianEventTrigger

    @property
    def source_key(self) -> tuple[str, str, str]:
        return (
            self.network_id,
            self.trigger.contract,
            self.trigger.event,
        )

    @property
    def cursor_key(self) -> str:
        return f"{_CURSOR_PREFIX}{self.runtime_id}"

    @property
    def last_run_key(self) -> str:
        return f"{_LAST_RUN_PREFIX}{self.runtime_id}"

    def dex_baseline_key(self, pair_key: str) -> str:
        return f"{_DEX_BASELINE_PREFIX}{self.runtime_id}:{pair_key}"


def build_cometbft_ws_url(rpc_url: str) -> str:
    if rpc_url.startswith("https://"):
        return f"wss://{rpc_url.removeprefix('https://')}/websocket"
    return f"ws://{rpc_url.removeprefix('http://')}/websocket"


def _decode_base64_string(value: str) -> str:
    try:
        return base64.b64decode(value).decode()
    except Exception:
        return value


def iter_contract_events_from_tx_event(event_data: dict[str, Any]):
    value = event_data.get("value", {})
    tx_result = value.get("TxResult", {})
    result = tx_result.get("result", {})
    for event in result.get("events", []):
        event_type = event.get("type", "")
        if event_type == "StateChange":
            continue

        attrs: dict[str, str] = {}
        for attr in event.get("attributes", []):
            raw_key = _decode_base64_string(attr.get("key", ""))
            raw_value = _decode_base64_string(attr.get("value", ""))
            attrs[raw_key] = raw_value

        contract = attrs.get("contract", "")
        if not contract:
            continue

        yield contract, _decode_base64_string(event_type)


def build_xian_event_prompt(
    task: XianEventTask,
    event: IndexedEvent,
    *,
    trigger_metrics: dict[str, Any] | None = None,
) -> str:
    payload = merged_event_payload(event)
    context = {
        "network_id": task.network_id,
        "contract": event.contract,
        "event": event.event,
        "event_id": event.id,
        "tx_hash": event.tx_hash,
        "block_height": event.block_height,
        "signer": event.signer,
        "caller": event.caller,
        "payload": payload,
    }
    if trigger_metrics:
        context["trigger_metrics"] = trigger_metrics
    context_json = json.dumps(context, sort_keys=True, ensure_ascii=True)
    return (
        "A Xian event trigger fired for this autonomous task.\n"
        "Use the following indexed event context as the authoritative trigger "
        "payload before deciding what to do.\n"
        f"{context_json}\n\n"
        "Original autonomous task instructions:\n"
        f"{task.prompt}"
    )


def event_matches_trigger(
    task: XianEventTask,
    event: IndexedEvent,
) -> bool:
    if event.contract != task.trigger.contract or event.event != task.trigger.event:
        return False
    filters = task.trigger.filters or {}
    if not filters:
        return True
    payload = merged_event_payload(event)
    for key, expected in filters.items():
        actual = payload.get(key)
        if actual is None or str(actual) != expected:
            return False
    return True


def _payload_decimal(payload: dict[str, Any], field_name: str) -> Decimal:
    raw = payload.get(field_name)
    if raw is None:
        raise ValueError(f"missing payload field '{field_name}'")
    if isinstance(raw, dict) and "__fixed__" in raw:
        raw = raw["__fixed__"]
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(
            f"payload field '{field_name}' is not numeric: {raw!r}"
        ) from exc


def _compute_dex_price_metrics(
    *,
    payload: dict[str, Any],
    trigger: XianDexPriceChangeTrigger,
    baseline_price: Decimal,
) -> tuple[str, Decimal, dict[str, Any]]:
    pair_value = payload.get(trigger.pair_field)
    if pair_value is None:
        raise ValueError(
            f"missing payload field '{trigger.pair_field}' for dex price trigger"
        )
    reserve0 = _payload_decimal(payload, trigger.reserve0_field)
    reserve1 = _payload_decimal(payload, trigger.reserve1_field)
    if reserve0 <= 0 or reserve1 <= 0:
        raise ValueError("dex price trigger reserves must be greater than 0")

    if trigger.price_base == "token0_per_token1":
        current_price = reserve0 / reserve1
    else:
        current_price = reserve1 / reserve0

    if baseline_price <= 0:
        raise ValueError("baseline dex price must be greater than 0")

    signed_change_pct = ((current_price - baseline_price) / baseline_price) * 100
    absolute_change_pct = abs(signed_change_pct)
    metrics = {
        "pair": str(pair_value),
        "price_before": str(baseline_price),
        "price_after": str(current_price),
        "price_change_pct": float(signed_change_pct),
        "price_change_pct_abs": float(absolute_change_pct),
        "price_base": trigger.price_base,
        "reserve0": str(reserve0),
        "reserve1": str(reserve1),
    }
    return str(pair_value), current_price, metrics


class XianEventTriggerService:
    def __init__(
        self,
        redis_client: Redis,
        *,
        session: aiohttp.ClientSession | None = None,
        batch_limit: int | None = None,
        poll_interval_seconds: float | None = None,
    ) -> None:
        self.redis = redis_client
        self.batch_limit = (
            batch_limit
            if batch_limit is not None
            else config.xian_event_trigger_batch_limit
        )
        self.poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else config.xian_event_trigger_poll_interval_seconds
        )
        self._external_session = session
        self._session = session
        self._tasks: dict[str, XianEventTask] = {}
        self._tasks_by_source: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        self._task_drains: dict[str, asyncio.Task[None]] = {}
        self._task_pending: set[str] = set()
        self._network_listeners: dict[str, asyncio.Task[None]] = {}
        self._periodic_task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def start(self) -> None:
        if not config.xian_event_trigger_enabled:
            logger.info("Xian event trigger service disabled by config")
            return
        if self._periodic_task is None:
            self._periodic_task = asyncio.create_task(self._periodic_sync_loop())

    async def close(self) -> None:
        self._closed = True
        for task in self._network_listeners.values():
            task.cancel()
        if self._periodic_task is not None:
            self._periodic_task.cancel()
        for task in self._task_drains.values():
            task.cancel()
        await asyncio.gather(
            *self._network_listeners.values(),
            *( [self._periodic_task] if self._periodic_task else [] ),
            *self._task_drains.values(),
            return_exceptions=True,
        )
        self._network_listeners.clear()
        self._task_drains.clear()
        if self._session is not None and not self._external_session:
            await self._session.close()
        self._session = None

    async def refresh(self, agents: list[Agent]) -> None:
        if not config.xian_event_trigger_enabled:
            return

        refreshed_tasks: dict[str, XianEventTask] = {}
        refreshed_sources: dict[tuple[str, str, str], set[str]] = defaultdict(set)

        for agent in agents:
            if not agent.autonomous:
                continue
            if not is_xian_network(agent.network_id):
                continue

            for autonomous in agent.autonomous:
                if (
                    not autonomous.enabled
                    or autonomous.trigger_type
                    != AgentAutonomousTriggerType.XIAN_EVENT
                    or autonomous.xian_event is None
                ):
                    continue

                task = XianEventTask(
                    runtime_id=f"{agent.id}-{autonomous.id}",
                    agent_id=agent.id,
                    agent_owner=agent.owner or "system",
                    agent_name=agent.name,
                    network_id=str(agent.network_id),
                    task_id=autonomous.id,
                    prompt=autonomous.prompt,
                    has_memory=bool(autonomous.has_memory),
                    trigger=autonomous.xian_event,
                )
                refreshed_tasks[task.runtime_id] = task
                refreshed_sources[task.source_key].add(task.runtime_id)

        new_task_ids = set(refreshed_tasks) - set(self._tasks)
        self._tasks = refreshed_tasks
        self._tasks_by_source = refreshed_sources

        for task_id in list(self._task_pending):
            if task_id not in self._tasks:
                self._task_pending.discard(task_id)

        for runtime_id in new_task_ids:
            await self._seed_cursor(self._tasks[runtime_id])

        await self._sync_network_listeners()

    async def _sync_network_listeners(self) -> None:
        required_networks = {task.network_id for task in self._tasks.values()}
        for network_id in list(self._network_listeners):
            if network_id not in required_networks:
                self._network_listeners[network_id].cancel()
                await asyncio.gather(
                    self._network_listeners[network_id],
                    return_exceptions=True,
                )
                del self._network_listeners[network_id]
        for network_id in required_networks:
            if network_id not in self._network_listeners:
                self._network_listeners[network_id] = asyncio.create_task(
                    self._network_listener_loop(network_id)
                )

    async def request_sync(
        self,
        runtime_id: str,
    ) -> None:
        if runtime_id not in self._tasks:
            return
        active = self._task_drains.get(runtime_id)
        if active is None or active.done():
            self._task_drains[runtime_id] = asyncio.create_task(
                self._drain_task(runtime_id)
            )
            return
        self._task_pending.add(runtime_id)

    async def request_sync_by_source(
        self,
        network_id: str,
        contract: str,
        event: str,
    ) -> None:
        for runtime_id in self._tasks_by_source.get((network_id, contract, event), set()):
            await self.request_sync(runtime_id)

    async def request_sync_all(self) -> None:
        for runtime_id in list(self._tasks):
            await self.request_sync(runtime_id)

    async def _periodic_sync_loop(self) -> None:
        while not self._closed:
            try:
                await self.request_sync_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Periodic Xian event trigger sync failed")
            await asyncio.sleep(self.poll_interval_seconds)

    async def _network_listener_loop(self, network_id: str) -> None:
        ws_url = build_cometbft_ws_url(get_xian_network_config(network_id).rpc_url)
        delay_idx = 0
        while not self._closed:
            try:
                async with self.session.ws_connect(ws_url, heartbeat=20.0) as ws:
                    delay_idx = 0
                    logger.info(
                        "Connected Xian event trigger websocket for %s",
                        network_id,
                    )
                    await ws.send_str(_SUBSCRIBE_TX)
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            if msg.type in (
                                aiohttp.WSMsgType.CLOSE,
                                aiohttp.WSMsgType.CLOSING,
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            ):
                                break
                            continue
                        data = json.loads(msg.data)
                        await self._handle_ws_message(network_id, data)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception(
                    "Xian event trigger websocket failed for %s",
                    network_id,
                )

            delay = _RECONNECT_DELAYS[min(delay_idx, len(_RECONNECT_DELAYS) - 1)]
            delay_idx += 1
            await asyncio.sleep(delay)

    async def _handle_ws_message(
        self,
        network_id: str,
        data: dict[str, Any],
    ) -> None:
        result = data.get("result", {})
        event_data = result.get("data", {})
        if event_data.get("type") != "tendermint/event/Tx":
            return
        for contract, event in iter_contract_events_from_tx_event(event_data):
            await self.request_sync_by_source(network_id, contract, event)

    async def _seed_cursor(self, task: XianEventTask) -> None:
        cursor_exists = await self.redis.exists(task.cursor_key)
        async with self._xian_client(task.network_id) as client:
            latest = await client.list_events(
                task.trigger.contract,
                task.trigger.event,
                limit=self.batch_limit,
            )
        if not cursor_exists:
            latest_id = max((item.id or 0 for item in latest), default=0)
            await self.redis.set(task.cursor_key, latest_id)

        if task.trigger.dex_price_change is None:
            return

        latest_matching: IndexedEvent | None = None
        for item in latest:
            if event_matches_trigger(task, item):
                if latest_matching is None or (item.id or 0) > (latest_matching.id or 0):
                    latest_matching = item
        if latest_matching is not None:
            await self._update_dex_baseline_from_event(task, latest_matching)

    async def _drain_task(self, runtime_id: str) -> None:
        try:
            while runtime_id in self._tasks:
                self._task_pending.discard(runtime_id)
                task = self._tasks.get(runtime_id)
                if task is None:
                    return
                await self._sync_task(task)
                if runtime_id not in self._task_pending:
                    return
        finally:
            self._task_drains.pop(runtime_id, None)
            self._task_pending.discard(runtime_id)

    async def _sync_task(self, task: XianEventTask) -> None:
        cursor = await self._get_cursor(task)
        async with self._xian_client(task.network_id) as client:
            while True:
                events = await client.list_events(
                    task.trigger.contract,
                    task.trigger.event,
                    limit=self.batch_limit,
                    after_id=cursor,
                )
                if not events:
                    return

                for event in events:
                    if event.id is None:
                        continue
                    await self._process_event(task, event)
                    cursor = event.id
                    await self.redis.set(task.cursor_key, cursor)

                if len(events) < self.batch_limit:
                    return

    async def _dispatch_event(
        self,
        task: XianEventTask,
        event: IndexedEvent,
        *,
        trigger_metrics: dict[str, Any] | None = None,
    ) -> None:
        if not await self._passes_cooldown(task):
            return

        await update_autonomous_task_status(
            task.agent_id,
            task.task_id,
            AgentAutonomousStatus.RUNNING,
            None,
        )
        try:
            await run_autonomous_task(
                task.agent_id,
                task.agent_owner,
                task.task_id,
                build_xian_event_prompt(
                    task,
                    event,
                    trigger_metrics=trigger_metrics,
                ),
                task.has_memory,
            )
            await self.redis.set(task.last_run_key, str(time.time()))
            await update_autonomous_task_status(
                task.agent_id,
                task.task_id,
                AgentAutonomousStatus.WAITING,
                None,
            )
        except Exception:
            logger.exception(
                "Failed to execute Xian event trigger task %s",
                task.runtime_id,
            )
            await update_autonomous_task_status(
                task.agent_id,
                task.task_id,
                AgentAutonomousStatus.ERROR,
                None,
            )

    async def _passes_cooldown(self, task: XianEventTask) -> bool:
        cooldown = task.trigger.cooldown_seconds
        if cooldown <= 0:
            return True
        raw = await self.redis.get(task.last_run_key)
        if raw is None:
            return True
        try:
            last_run = float(raw)
        except (TypeError, ValueError):
            return True
        return (time.time() - last_run) >= cooldown

    async def _get_cursor(self, task: XianEventTask) -> int:
        raw = await self.redis.get(task.cursor_key)
        if raw is None:
            await self._seed_cursor(task)
            raw = await self.redis.get(task.cursor_key)
        try:
            return int(raw or 0)
        except (TypeError, ValueError):
            return 0

    async def _process_event(
        self,
        task: XianEventTask,
        event: IndexedEvent,
    ) -> None:
        if not event_matches_trigger(task, event):
            return

        if task.trigger.dex_price_change is None:
            await self._dispatch_event(task, event)
            return

        evaluation = await self._evaluate_dex_price_change(task, event)
        if evaluation is None:
            return
        await self._dispatch_event(
            task,
            event,
            trigger_metrics=evaluation,
        )

    async def _evaluate_dex_price_change(
        self,
        task: XianEventTask,
        event: IndexedEvent,
    ) -> dict[str, Any] | None:
        trigger = task.trigger.dex_price_change
        if trigger is None:
            return None

        payload = merged_event_payload(event)
        pair_value = payload.get(trigger.pair_field)
        if pair_value is None:
            logger.warning(
                "Skipping dex price trigger for %s: missing pair field %s",
                task.runtime_id,
                trigger.pair_field,
            )
            return None

        baseline_key = task.dex_baseline_key(str(pair_value))
        baseline_raw = await self.redis.get(baseline_key)
        if baseline_raw is None:
            await self._update_dex_baseline_from_event(task, event)
            return None

        try:
            baseline_data = json.loads(str(baseline_raw))
            baseline_price = Decimal(str(baseline_data["price"]))
        except (KeyError, TypeError, ValueError, InvalidOperation, json.JSONDecodeError):
            await self._update_dex_baseline_from_event(task, event)
            return None

        try:
            _, current_price, metrics = _compute_dex_price_metrics(
                payload=payload,
                trigger=trigger,
                baseline_price=baseline_price,
            )
        except ValueError as exc:
            logger.warning(
                "Skipping dex price trigger for %s on event %s: %s",
                task.runtime_id,
                event.id,
                exc,
            )
            return None

        await self.redis.set(
            baseline_key,
            json.dumps(
                {
                    "event_id": event.id,
                    "price": str(current_price),
                    "block_height": event.block_height,
                },
                sort_keys=True,
            ),
        )

        absolute_change = Decimal(str(metrics["price_change_pct_abs"]))
        if absolute_change < Decimal(str(trigger.threshold_pct)):
            return None

        signed_change = Decimal(str(metrics["price_change_pct"]))
        if trigger.direction == "up" and signed_change <= 0:
            return None
        if trigger.direction == "down" and signed_change >= 0:
            return None
        return metrics

    async def _update_dex_baseline_from_event(
        self,
        task: XianEventTask,
        event: IndexedEvent,
    ) -> None:
        trigger = task.trigger.dex_price_change
        if trigger is None:
            return
        payload = merged_event_payload(event)
        try:
            pair_key, current_price, _ = _compute_dex_price_metrics(
                payload=payload,
                trigger=trigger,
                baseline_price=Decimal("1"),
            )
        except ValueError:
            return
        await self.redis.set(
            task.dex_baseline_key(pair_key),
            json.dumps(
                {
                    "event_id": event.id,
                    "price": str(current_price),
                    "block_height": event.block_height,
                },
                sort_keys=True,
            ),
        )

    def _xian_client(self, network_id: str) -> XianAsync:
        network = get_xian_network_config(network_id)
        return XianAsync(network.rpc_url, chain_id=network.chain_id)
