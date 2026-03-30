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
    parse_positive_decimal,
    quote_trade,
    render_quote,
)


class XianDexQuoteInput(BaseModel):
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
        description="Slippage tolerance percentage used for execution planning.",
    )
    dex_contract: str = Field(
        default=DEFAULT_DEX_CONTRACT,
        description="DEX router contract name.",
    )
    dex_helper_contract: str = Field(
        default=DEFAULT_DEX_HELPER_CONTRACT,
        description="DEX helper contract name for single-pair execution.",
    )
    pairs_contract: str = Field(
        default=DEFAULT_DEX_PAIRS_CONTRACT,
        description="DEX pair registry contract name.",
    )


class XianDexQuote(XianBaseTool):
    name: str = "xian_dex_quote"
    description: str = (
        "Quote a single-pair trade on the Xian DEX using the current con_dex and "
        "con_dex_helper contracts. Returns pair ID, fee, and execution bounds."
    )
    args_schema: ArgsSchema | None = XianDexQuoteInput

    @override
    async def _arun(
        self,
        side: Literal["buy", "sell"],
        buy_token: str,
        sell_token: str,
        amount: str,
        slippage: float = 1,
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
            return render_quote(quote, helper_contract=dex_helper_contract)
        except ToolException:
            raise
        except Exception as exc:
            raise ToolException(f"Error quoting Xian DEX trade: {exc}") from exc
