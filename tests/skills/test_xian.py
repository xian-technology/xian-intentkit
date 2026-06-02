from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intentkit.skills.xian.dex_quote import XianDexQuote
from intentkit.skills.xian.dex_trade import XianDexTrade
from intentkit.skills.xian.get_events_for_tx import XianGetEventsForTx
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


@pytest.mark.asyncio
async def test_xian_get_events_for_tx(monkeypatch):
    skill = XianGetEventsForTx()
    ctx = _mock_context()
    provider = _provider(monkeypatch)
    provider.get_events_for_transaction = AsyncMock(
        return_value=[
            SimpleNamespace(
                raw={
                    "id": 12,
                    "tx_hash": "tx-123",
                    "contract": "currency",
                    "event": "Transfer",
                    "data": {"to": "bob", "amount": 25},
                }
            )
        ]
    )

    with (
        patch("intentkit.skills.base.IntentKitSkill.get_context", return_value=ctx),
        patch(
            "intentkit.skills.xian.base.get_wallet_provider",
            new=AsyncMock(return_value=provider),
        ),
    ):
        result = await skill._arun("tx-123")

    assert "Indexed events for transaction tx-123" in result
    assert '"event": "Transfer"' in result
    assert '"amount": 25' in result


@pytest.mark.asyncio
async def test_xian_dex_quote_sell(monkeypatch):
    skill = XianDexQuote()
    ctx = _mock_context()
    provider = _provider(monkeypatch)

    async def get_state(contract: str, variable: str, *keys):
        if (contract, variable, keys) == (
            "con_pairs",
            "toks_to_pair",
            ("con_token", "currency"),
        ):
            return 7
        if (contract, variable, keys) == (
            "con_pairs",
            "pairs",
            (7, "reserve0"),
        ):
            return 500
        if (contract, variable, keys) == (
            "con_pairs",
            "pairs",
            (7, "reserve1"),
        ):
            return 1000
        if (contract, variable, keys) == (
            "con_dex",
            "zero_fee_signers",
            (provider.address,),
        ):
            return None
        raise AssertionError(f"unexpected get_state: {contract}.{variable} {keys}")

    provider.get_state = AsyncMock(side_effect=get_state)
    provider.call_contract = AsyncMock()

    with (
        patch("intentkit.skills.base.IntentKitSkill.get_context", return_value=ctx),
        patch(
            "intentkit.skills.xian.base.get_wallet_provider",
            new=AsyncMock(return_value=provider),
        ),
    ):
        result = await skill._arun(
            side="sell",
            buy_token="con_token",
            sell_token="currency",
            amount="100",
        )

    assert "Xian DEX quote (sell)" in result
    assert "Pair: 7" in result
    assert "Expected output:" in result
    assert "Minimum output with slippage:" in result
    assert "Approval target for execution: con_dex_helper" in result
    provider.call_contract.assert_not_awaited()


@pytest.mark.asyncio
async def test_xian_dex_trade_buy_with_auto_approve(monkeypatch):
    skill = XianDexTrade()
    ctx = _mock_context()
    provider = _provider(monkeypatch)

    async def get_state(contract: str, variable: str, *keys):
        if (contract, variable, keys) == (
            "con_pairs",
            "toks_to_pair",
            ("con_token", "currency"),
        ):
            return 11
        if (contract, variable, keys) == (
            "con_pairs",
            "pairs",
            (11, "reserve0"),
        ):
            return 500
        if (contract, variable, keys) == (
            "con_pairs",
            "pairs",
            (11, "reserve1"),
        ):
            return 1000
        if (contract, variable, keys) == (
            "con_dex",
            "zero_fee_signers",
            (provider.address,),
        ):
            return None
        raise AssertionError(f"unexpected get_state: {contract}.{variable} {keys}")

    provider.get_state = AsyncMock(side_effect=get_state)
    provider.call_contract = AsyncMock()
    provider.get_allowance = AsyncMock(return_value=0)
    provider.approve = AsyncMock(
        return_value=SimpleNamespace(
            tx_hash="approve-123",
            mode="commit",
            accepted=True,
            finalized=True,
            message=None,
            receipt=None,
        )
    )
    provider.send_contract_transaction = AsyncMock(
        return_value=SimpleNamespace(
            tx_hash="trade-123",
            mode="commit",
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
            side="buy",
            buy_token="con_token",
            sell_token="currency",
            amount="50.5",
            slippage=0.5,
        )

    provider.approve.assert_awaited_once()
    provider.send_contract_transaction.assert_awaited_once()
    approve_amount = provider.approve.await_args.kwargs["amount"]
    assert approve_amount > Decimal("110")
    assert not isinstance(approve_amount, float)
    trade_kwargs = provider.send_contract_transaction.await_args.kwargs["kwargs"]
    assert provider.send_contract_transaction.await_args.kwargs["contract"] == "con_dex_helper"
    assert provider.send_contract_transaction.await_args.kwargs["function"] == "buy"
    assert trade_kwargs["buy_token"] == "con_token"
    assert trade_kwargs["sell_token"] == "currency"
    assert trade_kwargs["amount"] == Decimal("50.5")
    assert trade_kwargs["slippage"] == Decimal("0.5")
    assert isinstance(trade_kwargs["deadline"], dict)
    assert "__time__" in trade_kwargs["deadline"]
    assert "approve-123" in result
    assert "trade-123" in result
    provider.call_contract.assert_not_awaited()


@pytest.mark.asyncio
async def test_xian_dex_trade_requires_allowance_when_auto_approve_disabled(
    monkeypatch,
):
    skill = XianDexTrade()
    ctx = _mock_context()
    provider = _provider(monkeypatch)

    async def call_contract(contract: str, function: str, kwargs: dict):
        if contract == "con_pairs" and function == "getReserves":
            return [1000, 500, 0]
        if contract == "con_dex" and function == "getTradeFeeBps":
            return 30
        if contract == "con_dex" and function == "getAmountOut":
            return 40
        raise AssertionError(f"unexpected call: {contract}.{function} {kwargs}")

    provider.get_state = AsyncMock(return_value=5)
    provider.call_contract = AsyncMock(side_effect=call_contract)
    provider.get_allowance = AsyncMock(return_value=0)

    with (
        patch("intentkit.skills.base.IntentKitSkill.get_context", return_value=ctx),
        patch(
            "intentkit.skills.xian.base.get_wallet_provider",
            new=AsyncMock(return_value=provider),
        ),
    ):
        with pytest.raises(Exception, match="Allowance to the DEX helper is insufficient"):
            await skill._arun(
                side="sell",
                buy_token="con_token",
                sell_token="currency",
                amount="25",
                auto_approve=False,
            )
