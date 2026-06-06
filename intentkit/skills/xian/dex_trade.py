from __future__ import annotations

from decimal import Decimal
from typing import Literal, override

from langchain_core.tools import ArgsSchema
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from intentkit.skills.xian.base import XianBaseTool
from intentkit.skills.xian.dex_common import (
    DEFAULT_DEX_CONTRACT,
    DEFAULT_DEX_HELPER_CONTRACT,
    DEFAULT_DEX_PAIRS_CONTRACT,
    build_deadline,
    decimal_from_value,
    decimal_to_contract_number,
    direct_swap_function,
    parse_positive_decimal,
    quote_trade,
    render_quote,
)
from intentkit.skills.xian.utils import format_xian_amount, render_submission


class XianDexTradeInput(BaseModel):
    side: Literal["buy", "sell"] = Field(
        ...,
        description=(
            "Trade direction. 'buy' means amount is desired output. 'sell' means "
            "amount is the input to sell."
        ),
    )
    buy_token: str = Field(..., description="Token contract to receive.")
    sell_token: str = Field(..., description="Token contract to spend.")
    amount: str = Field(
        ...,
        description="Human-readable numeric amount. Meaning depends on side.",
    )
    slippage: float = Field(
        default=1,
        ge=0,
        le=100,
        description="Allowed slippage percentage.",
    )
    deadline_minutes: int = Field(
        default=5,
        ge=1,
        le=1440,
        description="Minutes from now before the router trade expires.",
    )
    auto_approve: bool = Field(
        default=True,
        description=(
            "Automatically approve the DEX router to spend the sell token when "
            "allowance is insufficient."
        ),
    )
    mode: Literal["async", "checktx", "commit"] = Field(
        default="commit",
        description="Broadcast mode for the trade transaction.",
    )
    wait_for_tx: bool = Field(
        default=True,
        description="Wait for the final transaction receipt when possible.",
    )
    dex_contract: str = Field(
        default=DEFAULT_DEX_CONTRACT,
        description="DEX router contract name.",
    )
    dex_helper_contract: str = Field(
        default=DEFAULT_DEX_HELPER_CONTRACT,
        description=(
            "Deprecated. Single-pair execution now uses dex_contract directly "
            "to reduce fee overhead."
        ),
    )
    pairs_contract: str = Field(
        default=DEFAULT_DEX_PAIRS_CONTRACT,
        description="DEX pair registry contract name.",
    )


class XianDexTrade(XianBaseTool):
    name: str = "xian_dex_trade"
    description: str = (
        "Execute a single-pair trade on the Xian DEX through the con_dex router. "
        "Quotes the trade first, checks allowance, optionally approves, then "
        "submits a direct router swap transaction."
    )
    args_schema: ArgsSchema | None = XianDexTradeInput

    @override
    async def _arun(
        self,
        side: Literal["buy", "sell"],
        buy_token: str,
        sell_token: str,
        amount: str,
        slippage: float = 1,
        deadline_minutes: int = 5,
        auto_approve: bool = True,
        mode: Literal["async", "checktx", "commit"] = "commit",
        wait_for_tx: bool = True,
        dex_contract: str = DEFAULT_DEX_CONTRACT,
        dex_helper_contract: str = DEFAULT_DEX_HELPER_CONTRACT,
        pairs_contract: str = DEFAULT_DEX_PAIRS_CONTRACT,
    ) -> str:
        try:
            provider = await self.get_xian_provider()
            quote = await quote_trade(
                provider,
                side=side,
                buy_token=buy_token,
                sell_token=sell_token,
                amount=parse_positive_decimal(amount, field_name="amount"),
                slippage=Decimal(str(slippage)),
                dex_contract=dex_contract,
                pairs_contract=pairs_contract,
            )

            allowance_required = quote.max_input if side == "buy" else quote.estimated_input
            allowance_current = decimal_from_value(
                await provider.get_allowance(token=sell_token, spender=dex_contract)
            )

            sections = [render_quote(quote, router_contract=dex_contract)]

            if allowance_current < allowance_required:
                if not auto_approve:
                    raise ToolException(
                        "Allowance to the DEX router is insufficient. "
                        f"Current allowance: {format_xian_amount(allowance_current)}. "
                        f"Required: {format_xian_amount(allowance_required)}."
                    )

                approval_submission = await provider.approve(
                    token=sell_token,
                    spender=dex_contract,
                    amount=decimal_to_contract_number(allowance_required),
                    mode=mode,
                    wait_for_tx=wait_for_tx,
                )
                sections.append(
                    render_submission(
                        (f"Submitted Xian DEX router approval for {dex_contract} on {sell_token}."),
                        approval_submission,
                    )
                )

            amount_in = quote.max_input if side == "buy" else quote.estimated_input
            trade_kwargs = {
                "amountIn": decimal_to_contract_number(amount_in),
                "amountOutMin": decimal_to_contract_number(quote.min_output),
                "pair": quote.pair_id,
                "src": sell_token,
                "to": provider.address,
                "deadline": build_deadline(deadline_minutes),
            }
            swap_function = direct_swap_function(quote)
            trade_submission = await provider.send_contract_transaction(
                contract=dex_contract,
                function=swap_function,
                kwargs=trade_kwargs,
                mode=mode,
                wait_for_tx=wait_for_tx,
            )
            sections.append(
                render_submission(
                    (
                        f"Submitted Xian DEX {side} trade on {dex_contract} "
                        f"for pair {quote.pair_id}."
                    ),
                    trade_submission,
                )
            )
            return "\n\n".join(sections)
        except ToolException:
            raise
        except Exception as exc:
            raise ToolException(f"Error executing Xian DEX trade: {exc}") from exc
