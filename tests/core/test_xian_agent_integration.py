import json
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import intentkit.core.asset as asset_module
from intentkit.core.agent import process_agent_wallet
from intentkit.core.prompt import _build_wallet_section
from intentkit.models.agent import Agent, AgentVisibility
from intentkit.models.agent_data import AgentData
from intentkit.wallets.xian_networks import XianPriceConfig


@asynccontextmanager
async def _mock_session_ctx():
    session = AsyncMock()
    yield session


@pytest.mark.asyncio
async def test_process_agent_wallet_creates_xian_wallet(monkeypatch):
    now = datetime.now()
    agent = Agent(
        id="agent-xian-1",
        name="Xian Agent",
        description="Xian test agent",
        model="gpt-4o",
        deployed_at=now,
        updated_at=now,
        created_at=now,
        owner="owner-1",
        skills={},
        prompt="You are a helper.",
        temperature=0.7,
        visibility=AgentVisibility.PRIVATE,
        public_info_updated_at=now,
        wallet_provider="xian",
        network_id="xian-localnet",
    )

    existing_agent_data = AgentData(
        id=agent.id,
        created_at=now,
        updated_at=now,
    )
    updated_agent_data = AgentData(
        id=agent.id,
        xian_wallet_address="abc123",
        xian_wallet_data=json.dumps({"address": "abc123"}),
        created_at=now,
        updated_at=now,
    )

    monkeypatch.setattr(AgentData, "get", AsyncMock(return_value=existing_agent_data))
    patch_mock = AsyncMock(return_value=updated_agent_data)
    monkeypatch.setattr(AgentData, "patch", patch_mock)
    monkeypatch.setattr(
        "intentkit.wallets.xian.create_xian_wallet",
        lambda network_id: {
            "address": "abc123",
            "public_key": "abc123",
            "private_key": "def456",
            "network_id": network_id,
            "chain_id": "xian-localnet-1",
            "provider": "xian",
        },
    )

    result = await process_agent_wallet(agent, old_wallet_provider="none")

    assert result == updated_agent_data
    _, patch_payload = patch_mock.call_args.args
    assert patch_payload["xian_wallet_address"] == "abc123"
    assert (
        json.loads(patch_payload["xian_wallet_data"])["chain_id"] == "xian-localnet-1"
    )


def test_build_wallet_section_includes_xian_wallet():
    agent = SimpleNamespace(network_id="xian-localnet")
    agent_data = SimpleNamespace(
        evm_wallet_address=None,
        solana_wallet_address=None,
        xian_wallet_address="abc123",
    )

    section = _build_wallet_section(agent, agent_data)

    assert "Xian wallet address is abc123" in section
    assert "xian-localnet" in section


@pytest.mark.asyncio
async def test_get_solana_jupiter_price_usd(monkeypatch):
    class MockResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, dict[str, str]]:
            return {"Mint123": {"usdPrice": "1.23"}}

    class MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, *, params: dict[str, str], timeout: float):
            assert url == asset_module.JUPITER_PRICE_API_URL
            assert params == {"ids": "Mint123"}
            assert timeout == 30.0
            return MockResponse()

    monkeypatch.setattr(asset_module.httpx, "AsyncClient", lambda: MockClient())

    price = await asset_module._get_solana_jupiter_price_usd("Mint123")

    assert price == Decimal("1.23")


@pytest.mark.asyncio
async def test_agent_asset_xian(monkeypatch):
    agent = SimpleNamespace(
        network_id="xian-localnet",
        ticker=None,
        token_address=None,
        id="agent-xian-1",
    )
    wallet_data = {
        "address": "abc123",
        "public_key": "abc123",
        "private_key": "def456",
        "network_id": "xian-localnet",
        "chain_id": "xian-localnet-1",
        "provider": "xian",
    }

    async def mock_get_agent(agent_id):
        return agent

    class DummyAgentData:
        @classmethod
        async def get(cls, agent_id: str):
            return SimpleNamespace(
                evm_wallet_address=None,
                xian_wallet_address="abc123",
                xian_wallet_data=json.dumps(wallet_data),
            )

    provider = AsyncMock()
    provider.native_token_symbol = "XIAN"
    provider.get_balance = AsyncMock(return_value=Decimal("12.5"))

    monkeypatch.setattr(asset_module, "get_agent", mock_get_agent)
    monkeypatch.setattr(asset_module, "AgentData", DummyAgentData)
    monkeypatch.setattr(asset_module, "get_xian_wallet_provider", lambda _: provider)
    monkeypatch.setattr(
        asset_module,
        "get_xian_price_config",
        lambda _: XianPriceConfig(network_id="xian-localnet", strategy="none"),
    )
    monkeypatch.setattr(asset_module, "get_session", _mock_session_ctx)

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.set.return_value = None
    monkeypatch.setattr(asset_module, "get_redis", lambda: mock_redis)

    result = await asset_module.agent_asset("agent-xian-1")

    assert result.net_worth == "0"
    assert result.tokens == [asset_module.Asset(symbol="XIAN", balance=Decimal("12.5"))]


@pytest.mark.asyncio
async def test_agent_asset_xian_uses_fixed_usd_price(monkeypatch):
    agent = SimpleNamespace(
        network_id="xian-localnet",
        ticker=None,
        token_address=None,
        id="agent-xian-2",
    )
    wallet_data = {
        "address": "abc123",
        "public_key": "abc123",
        "private_key": "def456",
        "network_id": "xian-localnet",
        "chain_id": "xian-localnet-1",
        "provider": "xian",
    }

    async def mock_get_agent(agent_id):
        return agent

    class DummyAgentData:
        @classmethod
        async def get(cls, agent_id: str):
            return SimpleNamespace(
                evm_wallet_address=None,
                xian_wallet_address="abc123",
                xian_wallet_data=json.dumps(wallet_data),
            )

    provider = AsyncMock()
    provider.native_token_symbol = "XIAN"
    provider.get_balance = AsyncMock(return_value=Decimal("12.5"))

    monkeypatch.setattr(asset_module, "get_agent", mock_get_agent)
    monkeypatch.setattr(asset_module, "AgentData", DummyAgentData)
    monkeypatch.setattr(asset_module, "get_xian_wallet_provider", lambda _: provider)
    monkeypatch.setattr(
        asset_module,
        "get_xian_price_config",
        lambda _: XianPriceConfig(
            network_id="xian-localnet",
            strategy="fixed_usd",
            fixed_usd=Decimal("2.5"),
        ),
    )
    monkeypatch.setattr(asset_module, "get_session", _mock_session_ctx)

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.set.return_value = None
    monkeypatch.setattr(asset_module, "get_redis", lambda: mock_redis)

    result = await asset_module.agent_asset("agent-xian-2")

    assert result.net_worth == "31.25"
    assert result.tokens == [asset_module.Asset(symbol="XIAN", balance=Decimal("12.5"))]
