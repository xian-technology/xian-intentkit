import base64
from unittest.mock import AsyncMock

import pytest
from xian_py.models import IndexedEvent

from intentkit.core.xian_event_triggers import (
    XianEventTask,
    XianEventTriggerService,
    build_xian_event_prompt,
    event_matches_trigger,
    iter_contract_events_from_tx_event,
)
from intentkit.models.agent.autonomous import (
    XianDexPriceChangeTrigger,
    XianEventTrigger,
)


class FakeRedis:
    def __init__(self):
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
    def __init__(self, batches):
        self._batches = list(batches)
        self.calls: list[int] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def list_events(self, contract, event, limit=100, after_id=None):
        self.calls.append(after_id or 0)
        if self._batches:
            return self._batches.pop(0)
        return []


def _indexed_event(
    *,
    event_id: int,
    contract: str = "currency",
    event: str = "Transfer",
    payload: dict | None = None,
) -> IndexedEvent:
    return IndexedEvent.from_dict(
        {
            "id": event_id,
            "contract": contract,
            "event": event,
            "data_indexed": payload or {},
            "tx_hash": f"tx-{event_id}",
            "block_height": 100 + event_id,
        }
    )


def _task(*, cooldown_seconds: int = 0, filters: dict[str, str] | None = None):
    return XianEventTask(
        runtime_id="agent-1-task-1",
        agent_id="agent-1",
        agent_owner="owner-1",
        agent_name="Agent One",
        network_id="xian-localnet",
        task_id="task-1",
        prompt="Act on the event",
        has_memory=False,
        trigger=XianEventTrigger(
            contract="currency",
            event="Transfer",
            filters=filters,
            cooldown_seconds=cooldown_seconds,
        ),
    )


def test_iter_contract_events_from_tx_event_decodes_payload():
    event_name = base64.b64encode(b"Transfer").decode()
    contract_key = base64.b64encode(b"contract").decode()
    contract_value = base64.b64encode(b"currency").decode()
    tx_event = {
        "value": {
            "TxResult": {
                "result": {
                    "events": [
                        {
                            "type": event_name,
                            "attributes": [{"key": contract_key, "value": contract_value}],
                        }
                    ]
                }
            }
        }
    }

    assert list(iter_contract_events_from_tx_event(tx_event)) == [("currency", "Transfer")]


@pytest.mark.asyncio
async def test_handle_ws_message_requests_sync_for_custom_event(monkeypatch):
    redis = FakeRedis()
    service = XianEventTriggerService(redis, batch_limit=10, poll_interval_seconds=1.0)
    task = XianEventTask(
        runtime_id="agent-1-task-custom",
        agent_id="agent-1",
        agent_owner="owner-1",
        agent_name="Agent One",
        network_id="xian-localnet",
        task_id="task-custom",
        prompt="Act on custom payments",
        has_memory=False,
        trigger=XianEventTrigger(
            contract="con_custom_payments",
            event="Paid",
            filters={"account": "alice"},
        ),
    )
    service._tasks[task.runtime_id] = task
    service._tasks_by_source[task.source_key].add(task.runtime_id)
    requested: list[str] = []

    async def fake_request_sync(runtime_id):
        requested.append(runtime_id)

    def b64(value: str) -> str:
        return base64.b64encode(value.encode()).decode()

    monkeypatch.setattr(service, "request_sync", fake_request_sync)
    message = {
        "result": {
            "data": {
                "type": "tendermint/event/Tx",
                "value": {
                    "TxResult": {
                        "result": {
                            "events": [
                                {
                                    "type": b64("Paid"),
                                    "attributes": [
                                        {
                                            "key": b64("contract"),
                                            "value": b64("con_custom_payments"),
                                        }
                                    ],
                                },
                                {
                                    "type": b64("Ignored"),
                                    "attributes": [
                                        {
                                            "key": b64("contract"),
                                            "value": b64("con_custom_payments"),
                                        }
                                    ],
                                },
                                {
                                    "type": b64("Paid"),
                                    "attributes": [
                                        {
                                            "key": b64("contract"),
                                            "value": b64("con_other"),
                                        }
                                    ],
                                },
                            ]
                        }
                    }
                },
            }
        }
    }

    await service._handle_ws_message("xian-localnet", message)

    assert requested == [task.runtime_id]


def test_event_matches_trigger_with_filters():
    task = _task(filters={"to": "alice"})
    matching = _indexed_event(event_id=1, payload={"to": "alice", "amount": 5})
    non_matching = _indexed_event(event_id=2, payload={"to": "bob"})

    assert event_matches_trigger(task, matching) is True
    assert event_matches_trigger(task, non_matching) is False


def test_build_xian_event_prompt_includes_event_context():
    task = _task()
    event = _indexed_event(event_id=7, payload={"to": "alice", "amount": 5})

    prompt = build_xian_event_prompt(task, event)

    assert "Xian event trigger fired" in prompt
    assert '"event_id": 7' in prompt
    assert '"contract": "currency"' in prompt
    assert '"to": "alice"' in prompt
    assert "Original autonomous task instructions" in prompt


def test_build_xian_event_prompt_includes_trigger_metrics():
    task = _task()
    event = _indexed_event(event_id=8, payload={"to": "alice", "amount": 7})

    prompt = build_xian_event_prompt(
        task,
        event,
        trigger_metrics={"price_change_pct": 6.2, "pair": "1"},
    )

    assert '"trigger_metrics"' in prompt
    assert '"price_change_pct": 6.2' in prompt
    assert '"pair": "1"' in prompt


@pytest.mark.asyncio
async def test_sync_task_advances_cursor_and_dispatches_matching_events(monkeypatch):
    redis = FakeRedis()
    service = XianEventTriggerService(redis, batch_limit=10, poll_interval_seconds=1.0)
    task = _task(filters={"to": "alice"})
    fake_client = FakeClient(
        [
            [
                _indexed_event(event_id=1, payload={"to": "bob"}),
                _indexed_event(event_id=2, payload={"to": "alice"}),
            ]
        ]
    )
    dispatched: list[int] = []

    async def fake_dispatch(runtime_task, event):
        dispatched.append(event.id)

    monkeypatch.setattr(service, "_xian_client", lambda network_id: fake_client)
    monkeypatch.setattr(service, "_dispatch_event", fake_dispatch)
    await redis.set(task.cursor_key, 0)

    await service._sync_task(task)

    assert dispatched == [2]
    assert await redis.get(task.cursor_key) == "2"


@pytest.mark.asyncio
async def test_process_custom_event_dispatches_without_dex_metrics(monkeypatch):
    redis = FakeRedis()
    service = XianEventTriggerService(redis, batch_limit=10, poll_interval_seconds=1.0)
    task = XianEventTask(
        runtime_id="agent-1-task-custom",
        agent_id="agent-1",
        agent_owner="owner-1",
        agent_name="Agent One",
        network_id="xian-localnet",
        task_id="task-custom",
        prompt="Act on custom payments",
        has_memory=False,
        trigger=XianEventTrigger(
            contract="con_custom_payments",
            event="Paid",
            filters={"account": "alice"},
        ),
    )
    dispatched: list[tuple[str, int, dict | None]] = []

    async def fake_dispatch(runtime_task, event, *, trigger_metrics=None):
        dispatched.append((runtime_task.runtime_id, event.id, trigger_metrics))

    monkeypatch.setattr(service, "_dispatch_event", fake_dispatch)

    await service._process_event(
        task,
        _indexed_event(
            event_id=11,
            contract="con_custom_payments",
            event="Paid",
            payload={"account": "alice", "amount": "12.5"},
        ),
    )
    await service._process_event(
        task,
        _indexed_event(
            event_id=12,
            contract="con_custom_payments",
            event="Paid",
            payload={"account": "bob", "amount": "8"},
        ),
    )

    assert dispatched == [(task.runtime_id, 11, None)]


@pytest.mark.asyncio
async def test_dispatch_event_respects_cooldown(monkeypatch):
    redis = FakeRedis()
    service = XianEventTriggerService(redis, batch_limit=10, poll_interval_seconds=1.0)
    task = _task(cooldown_seconds=60)
    event = _indexed_event(event_id=3, payload={"to": "alice"})

    run_mock = AsyncMock()
    status_mock = AsyncMock()
    monkeypatch.setattr(
        "intentkit.core.xian_event_triggers.run_autonomous_task",
        run_mock,
    )
    monkeypatch.setattr(
        "intentkit.core.xian_event_triggers.update_autonomous_task_status",
        status_mock,
    )

    await service._dispatch_event(task, event)
    await service._dispatch_event(task, event)

    assert run_mock.await_count == 1
    assert status_mock.await_count == 2
    assert await redis.get(task.last_run_key) is not None


@pytest.mark.asyncio
async def test_dex_price_trigger_seeds_baseline_then_dispatches_matching_move(
    monkeypatch,
):
    redis = FakeRedis()
    service = XianEventTriggerService(redis, batch_limit=10, poll_interval_seconds=1.0)
    task = XianEventTask(
        runtime_id="agent-1-task-dex",
        agent_id="agent-1",
        agent_owner="owner-1",
        agent_name="Agent One",
        network_id="xian-localnet",
        task_id="task-dex",
        prompt="Trade on big moves",
        has_memory=False,
        trigger=XianEventTrigger(
            contract="con_pairs",
            event="Sync",
            filters={"pair": "1"},
            dex_price_change=XianDexPriceChangeTrigger(
                threshold_pct=5.0,
                direction="either",
            ),
        ),
    )
    fake_client = FakeClient(
        [
            [
                _indexed_event(
                    event_id=1,
                    contract="con_pairs",
                    event="Sync",
                    payload={"pair": 1, "reserve0": "100", "reserve1": "100"},
                ),
                _indexed_event(
                    event_id=2,
                    contract="con_pairs",
                    event="Sync",
                    payload={"pair": 1, "reserve0": "100", "reserve1": "112"},
                ),
            ]
        ]
    )
    dispatched: list[tuple[int, dict[str, object] | None]] = []

    async def fake_dispatch(runtime_task, event, *, trigger_metrics=None):
        dispatched.append((event.id, trigger_metrics))

    monkeypatch.setattr(service, "_xian_client", lambda network_id: fake_client)
    monkeypatch.setattr(service, "_dispatch_event", fake_dispatch)
    await redis.set(task.cursor_key, 0)

    await service._sync_task(task)

    assert len(dispatched) == 1
    event_id, metrics = dispatched[0]
    assert event_id == 2
    assert metrics is not None
    assert metrics["pair"] == "1"
    assert metrics["price_change_pct_abs"] >= 12


@pytest.mark.asyncio
async def test_seed_cursor_primes_dex_baseline(monkeypatch):
    redis = FakeRedis()
    service = XianEventTriggerService(redis, batch_limit=10, poll_interval_seconds=1.0)
    task = XianEventTask(
        runtime_id="agent-1-task-seed",
        agent_id="agent-1",
        agent_owner="owner-1",
        agent_name="Agent One",
        network_id="xian-localnet",
        task_id="task-seed",
        prompt="Trade on big moves",
        has_memory=False,
        trigger=XianEventTrigger(
            contract="con_pairs",
            event="Sync",
            filters={"pair": "1"},
            dex_price_change=XianDexPriceChangeTrigger(threshold_pct=3.0),
        ),
    )
    fake_client = FakeClient(
        [
            [
                _indexed_event(
                    event_id=9,
                    contract="con_pairs",
                    event="Sync",
                    payload={"pair": 1, "reserve0": "50", "reserve1": "75"},
                )
            ]
        ]
    )

    monkeypatch.setattr(service, "_xian_client", lambda network_id: fake_client)

    await service._seed_cursor(task)

    baseline_raw = await redis.get(task.dex_baseline_key("1"))
    assert baseline_raw is not None
    assert '"price": "1.5"' in baseline_raw


@pytest.mark.asyncio
async def test_seed_cursor_primes_dex_baseline_from_fixed_payload(monkeypatch):
    redis = FakeRedis()
    service = XianEventTriggerService(redis, batch_limit=10, poll_interval_seconds=1.0)
    task = XianEventTask(
        runtime_id="agent-1-task-fixed",
        agent_id="agent-1",
        agent_owner="owner-1",
        agent_name="Agent One",
        network_id="xian-localnet",
        task_id="task-fixed",
        prompt="Trade on big moves",
        has_memory=False,
        trigger=XianEventTrigger(
            contract="con_pairs",
            event="Sync",
            filters={"pair": "1"},
            dex_price_change=XianDexPriceChangeTrigger(threshold_pct=3.0),
        ),
    )
    fake_client = FakeClient(
        [
            [
                _indexed_event(
                    event_id=10,
                    contract="con_pairs",
                    event="Sync",
                    payload={
                        "pair": 1,
                        "reserve0": {"__fixed__": "50"},
                        "reserve1": {"__fixed__": "75"},
                    },
                )
            ]
        ]
    )

    monkeypatch.setattr(service, "_xian_client", lambda network_id: fake_client)

    await service._seed_cursor(task)

    baseline_raw = await redis.get(task.dex_baseline_key("1"))
    assert baseline_raw is not None
    assert '"price": "1.5"' in baseline_raw
