from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intentkit.skills.xian.get_wallet_details import XianGetWalletDetails
from intentkit.skills.xian.read_contract_state import XianReadContractState
from intentkit.skills.xian.send_contract_transaction import (
    XianSendContractTransaction,
)
from intentkit.wallets.xian import get_wallet_provider


def _mock_xian_env(monkeypatch) -> None:
    def _load(key: str, default: str | None = None) -> str | None:
        mapping = {
            "XIAN_LOCALNET_RPC_URL": "http://127.0.0.1:27657",
            "XIAN_LOCALNET_CHAIN_ID": "xian-localnet-1",
        }
        return mapping.get(key, default)

    monkeypatch.setattr("intentkit.wallets.xian_networks.config.load", _load)


def _mock_context() -> MagicMock:
    mock_agent = MagicMock()
    mock_agent.network_id = "xian-localnet"
    mock_agent.id = "agent-xian"
    mock_agent.wallet_provider = "xian"
    ctx = MagicMock()
    ctx.agent = mock_agent
    return ctx


def _provider(monkeypatch):
    _mock_xian_env(monkeypatch)
    provider = get_wallet_provider(
        {
            "private_key": "7cef134072db25484d4f5384bd6cec5b4a1fce84a371680e0d218c51ff2adafc",
            "network_id": "xian-localnet",
        }
    )
    return provider


@pytest.mark.asyncio
async def test_xian_get_wallet_details(monkeypatch):
    skill = XianGetWalletDetails()
    ctx = _mock_context()
    provider = _provider(monkeypatch)
    provider.get_balance = AsyncMock(return_value="42")

    with (
        patch("intentkit.skills.base.IntentKitSkill.get_context", return_value=ctx),
        patch(
            "intentkit.skills.xian.base.get_wallet_provider",
            new=AsyncMock(return_value=provider),
        ),
    ):
        result = await skill._arun()

    assert "Xian wallet address" in result
    assert "xian-localnet" in result
    assert "42 XIAN" in result


@pytest.mark.asyncio
async def test_xian_read_contract_state(monkeypatch):
    skill = XianReadContractState()
    ctx = _mock_context()
    provider = _provider(monkeypatch)
    provider.get_state = AsyncMock(return_value={"balance": "5"})

    with (
        patch("intentkit.skills.base.IntentKitSkill.get_context", return_value=ctx),
        patch(
            "intentkit.skills.xian.base.get_wallet_provider",
            new=AsyncMock(return_value=provider),
        ),
    ):
        result = await skill._arun("currency", "balances", ["alice"])

    assert "currency.balances:alice" in result
    assert '"balance": "5"' in result


@pytest.mark.asyncio
async def test_xian_send_contract_transaction(monkeypatch):
    skill = XianSendContractTransaction()
    ctx = _mock_context()
    provider = _provider(monkeypatch)
    provider.send_contract_transaction = AsyncMock(
        return_value=SimpleNamespace(
            tx_hash="tx-123",
            mode="checktx",
            accepted=True,
            finalized=True,
            message=None,
            receipt=None,
        )
    )

    with (
        patch("intentkit.skills.base.IntentKitSkill.get_context", return_value=ctx),
        patch(
            "intentkit.skills.xian.base.get_wallet_provider",
            new=AsyncMock(return_value=provider),
        ),
    ):
        result = await skill._arun(
            contract="submission",
            function="submit_contract",
            kwargs={"name": "hello"},
        )

    assert "submission.submit_contract" in result
    assert "tx-123" in result
    assert "Finalized: True" in result
