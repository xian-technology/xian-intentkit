from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from langchain_core.tools.base import ToolException
from xian_py import to_contract_time

from intentkit.skills.xian.utils import format_xian_amount
from intentkit.wallets.xian import XianWalletProvider

DEFAULT_DEX_CONTRACT = "con_dex"
DEFAULT_DEX_HELPER_CONTRACT = "con_dex_helper"
DEFAULT_DEX_PAIRS_CONTRACT = "con_pairs"
DEFAULT_TRADE_FEE_BPS = 30
ZERO_TRADE_FEE_BPS = 0


@dataclass(frozen=True)
class PairContext:
    pair_id: int
    token0: str
    token1: str
    reserve_buy: Decimal
    reserve_sell: Decimal
    fee_bps: int


@dataclass(frozen=True)
class DexQuote:
    side: Literal["buy", "sell"]
    pair_id: int
    buy_token: str
    sell_token: str
    requested_amount: Decimal
    fee_bps: int
    estimated_input: Decimal
    expected_output: Decimal
    max_input: Decimal
    min_output: Decimal


def parse_positive_decimal(value: str, *, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ToolException(f"{field_name} must be a valid numeric string.") from exc
    if parsed <= 0:
        raise ToolException(f"{field_name} must be greater than 0.")
    return parsed


def decimal_from_value(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ToolException(f"Could not parse numeric value: {value!r}") from exc


def decimal_to_contract_number(value: Decimal) -> int | float:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return int(normalized)
    return float(normalized)


def canonical_tokens(token_a: str, token_b: str) -> tuple[str, str]:
    return (token_a, token_b) if token_a < token_b else (token_b, token_a)


def build_deadline(minutes: int) -> dict[str, list[int]]:
    deadline = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=minutes)
    return to_contract_time(deadline)


async def resolve_pair_context(
    provider: XianWalletProvider,
    *,
    buy_token: str,
    sell_token: str,
    dex_contract: str,
    pairs_contract: str,
) -> PairContext:
    token0, token1 = canonical_tokens(buy_token, sell_token)
    pair_id = await provider.get_state(pairs_contract, "toks_to_pair", token0, token1)
    if pair_id is None:
        raise ToolException(f"No DEX pair exists for tokens {buy_token} and {sell_token}.")

    reserve0 = decimal_from_value(
        await provider.get_state(pairs_contract, "pairs", int(pair_id), "reserve0")
    )
    reserve1 = decimal_from_value(
        await provider.get_state(pairs_contract, "pairs", int(pair_id), "reserve1")
    )
    zero_fee = await provider.get_state(
        dex_contract,
        "zero_fee_signers",
        provider.address,
    )
    fee_bps = ZERO_TRADE_FEE_BPS if bool(zero_fee) else DEFAULT_TRADE_FEE_BPS

    if token0 == buy_token:
        reserve_buy = reserve0
        reserve_sell = reserve1
    else:
        reserve_buy = reserve1
        reserve_sell = reserve0

    return PairContext(
        pair_id=int(pair_id),
        token0=token0,
        token1=token1,
        reserve_buy=reserve_buy,
        reserve_sell=reserve_sell,
        fee_bps=fee_bps,
    )


async def quote_trade(
    provider: XianWalletProvider,
    *,
    side: Literal["buy", "sell"],
    buy_token: str,
    sell_token: str,
    amount: Decimal,
    slippage: Decimal,
    dex_contract: str,
    pairs_contract: str,
) -> DexQuote:
    context = await resolve_pair_context(
        provider,
        buy_token=buy_token,
        sell_token=sell_token,
        dex_contract=dex_contract,
        pairs_contract=pairs_contract,
    )

    slippage_factor = Decimal("1") + (slippage / Decimal("100"))
    min_output_factor = Decimal("1") - (slippage / Decimal("100"))

    if side == "buy":
        if amount >= context.reserve_buy:
            raise ToolException("Requested buy amount exceeds available liquidity.")
        fee_multiplier = Decimal(10000 - context.fee_bps) / Decimal(10000)
        if fee_multiplier <= 0:
            raise ToolException("Invalid trade fee configuration for this pair.")
        estimated_input = (context.reserve_sell * amount) / (
            (context.reserve_buy - amount) * fee_multiplier
        )
        # Match con_dex_helper.buy(...) behavior: slippage expansion plus tiny buffer.
        max_input = estimated_input * slippage_factor * Decimal("1.0001")
        return DexQuote(
            side=side,
            pair_id=context.pair_id,
            buy_token=buy_token,
            sell_token=sell_token,
            requested_amount=amount,
            fee_bps=context.fee_bps,
            estimated_input=estimated_input,
            expected_output=amount,
            max_input=max_input,
            min_output=amount * min_output_factor,
        )

    fee_multiplier = Decimal(10000 - context.fee_bps) / Decimal(10000)
    amount_in_with_fee = amount * fee_multiplier
    numerator = amount_in_with_fee * context.reserve_buy
    denominator = context.reserve_sell + amount_in_with_fee
    if denominator <= 0:
        raise ToolException("Insufficient liquidity for the requested trade.")
    expected_output = numerator / denominator
    return DexQuote(
        side=side,
        pair_id=context.pair_id,
        buy_token=buy_token,
        sell_token=sell_token,
        requested_amount=amount,
        fee_bps=context.fee_bps,
        estimated_input=amount,
        expected_output=expected_output,
        max_input=amount,
        min_output=expected_output * min_output_factor,
    )


def render_quote(quote: DexQuote, *, helper_contract: str) -> str:
    lines = [
        f"Xian DEX quote ({quote.side})",
        f"Pair: {quote.pair_id}",
        f"Sell token: {quote.sell_token}",
        f"Buy token: {quote.buy_token}",
        f"Trade fee: {quote.fee_bps} bps",
    ]
    if quote.side == "buy":
        lines.extend(
            [
                f"Target output: {format_xian_amount(quote.expected_output)}",
                f"Estimated input: {format_xian_amount(quote.estimated_input)}",
                f"Max input with slippage buffer: {format_xian_amount(quote.max_input)}",
                f"Helper execution path: {helper_contract}.buy(...)",
                f"Approval target for execution: {helper_contract}",
            ]
        )
    else:
        lines.extend(
            [
                f"Input amount: {format_xian_amount(quote.estimated_input)}",
                f"Expected output: {format_xian_amount(quote.expected_output)}",
                f"Minimum output with slippage: {format_xian_amount(quote.min_output)}",
                f"Helper execution path: {helper_contract}.sell(...)",
                f"Approval target for execution: {helper_contract}",
            ]
        )
    return "\n".join(lines)
