import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from xian_py import IndexedTransaction

from intentkit.wallets import (
    get_wallet_provider as get_unified_wallet_provider,
)
from intentkit.wallets import (
    get_wallet_signer as get_unified_wallet_signer,
)
from intentkit.wallets.xian import (
    create_xian_wallet,
    get_wallet_provider,
)
from intentkit.wallets.xian_networks import get_xian_price_config


def _mock_xian_env(monkeypatch) -> None:
    def _load(key: str, default: str | None = None) -> str | None:
        mapping = {
            "XIAN_LOCALNET_RPC_URL": "http://127.0.0.1:27657",
            "XIAN_LOCALNET_CHAIN_ID": "xian-localnet-1",
        }
        return mapping.get(key, default)

    monkeypatch.setattr("intentkit.wallets.xian_networks.config.load", _load)


def test_create_xian_wallet(monkeypatch):
    _mock_xian_env(monkeypatch)

    wallet = create_xian_wallet("xian-localnet")

    assert wallet["network_id"] == "xian-localnet"
    assert wallet["chain_id"] == "xian-localnet-1"
    assert wallet["provider"] == "xian"
    assert len(wallet["address"]) == 64
    assert len(wallet["private_key"]) == 64


def test_get_xian_price_config_prefers_network_override(monkeypatch):
    def _load(key: str, default: str | None = None) -> str | None:
        mapping = {
            "XIAN_PRICE_STRATEGY": "none",
            "XIAN_MAINNET_PRICE_STRATEGY": "solana_jupiter",
            "XIAN_MAINNET_PRICE_SOLANA_MINT": "Mint123",
            "XIAN_MAINNET_PRICE_MARKET_URL": "https://raydium.io/swap",
        }
        return mapping.get(key, default)

    monkeypatch.setattr("intentkit.wallets.xian_networks.config.load", _load)

    price_config = get_xian_price_config("xian-mainnet")

    assert price_config.strategy == "solana_jupiter"
    assert price_config.solana_mint == "Mint123"
    assert price_config.market_url == "https://raydium.io/swap"


@pytest.mark.asyncio
async def test_xian_wallet_provider_get_balance(monkeypatch):
    _mock_xian_env(monkeypatch)
    wallet_data = create_xian_wallet("xian-localnet")
    provider = get_wallet_provider(wallet_data)

    with patch("intentkit.wallets.xian.XianAsync") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get_balance = AsyncMock(return_value=123)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        balance = await provider.get_balance(token="currency")

    assert balance == 123
    mock_client.get_balance.assert_awaited_once_with(
        address=provider.address,
        contract="currency",
    )


@pytest.mark.asyncio
async def test_xian_wallet_provider_normalizes_indexed_tx_hash(monkeypatch):
    _mock_xian_env(monkeypatch)
    wallet_data = create_xian_wallet("xian-localnet")
    provider = get_wallet_provider(wallet_data)
    raw_indexed_tx = {
        "hash": "ABC123",
        "block_height": 10,
        "sender": provider.address,
        "nonce": 1,
        "contract": "currency",
        "function": "transfer",
        "success": True,
        "chi_used": 42,
    }

    with patch("intentkit.wallets.xian.XianAsync") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get_indexed_tx = AsyncMock(
            return_value=IndexedTransaction.from_dict(raw_indexed_tx)
        )
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        indexed_tx = await provider.get_indexed_transaction("ABC123")

    assert indexed_tx is not None
    assert indexed_tx.tx_hash == "ABC123"
    assert indexed_tx.raw["hash"] == "ABC123"


@pytest.mark.asyncio
async def test_unified_xian_wallet_provider(monkeypatch):
    _mock_xian_env(monkeypatch)
    wallet_data = create_xian_wallet("xian-localnet")
    agent = SimpleNamespace(
        id="agent-xian",
        wallet_provider="xian",
        network_id="xian-localnet",
    )
    agent_data = SimpleNamespace(xian_wallet_data=json.dumps(wallet_data))
    expected_provider = get_wallet_provider(wallet_data)

    with (
        patch(
            "intentkit.models.agent_data.AgentData.get",
            new=AsyncMock(return_value=agent_data),
        ),
        patch(
            "intentkit.wallets.get_xian_wallet_provider",
            return_value=expected_provider,
        ) as mock_get_provider,
    ):
        provider = await get_unified_wallet_provider(agent)

    assert provider is expected_provider
    mock_get_provider.assert_called_once()


@pytest.mark.asyncio
async def test_unified_xian_wallet_signer(monkeypatch):
    _mock_xian_env(monkeypatch)
    wallet_data = create_xian_wallet("xian-localnet")
    agent = SimpleNamespace(
        id="agent-xian",
        wallet_provider="xian",
        network_id="xian-localnet",
    )
    agent_data = SimpleNamespace(xian_wallet_data=json.dumps(wallet_data))

    with patch(
        "intentkit.models.agent_data.AgentData.get",
        new=AsyncMock(return_value=agent_data),
    ):
        signer = await get_unified_wallet_signer(agent)

    assert signer.public_key == wallet_data["address"]
    assert signer.private_key == wallet_data["private_key"]
