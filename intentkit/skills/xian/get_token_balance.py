from __future__ import annotations

from typing import override

from langchain_core.tools import ArgsSchema
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from intentkit.skills.xian.base import XianBaseTool
from intentkit.skills.xian.utils import format_xian_amount


class XianGetTokenBalanceInput(BaseModel):
    token_contract: str = Field(
        default="currency",
        description="Token contract name. Use 'currency' for the native Xian token.",
    )
    address: str | None = Field(
        default=None,
        description="Wallet address to query. Defaults to the agent wallet address.",
    )


class XianGetTokenBalance(XianBaseTool):
    name: str = "xian_get_token_balance"
    description: str = (
        "Get the balance of a Xian token contract for a wallet address. Defaults "
        "to the agent wallet and the native 'currency' token."
    )
    args_schema: ArgsSchema | None = XianGetTokenBalanceInput

    @override
    async def _arun(
        self,
        token_contract: str = "currency",
        address: str | None = None,
    ) -> str:
        try:
            provider = await self.get_xian_provider()
            target_address = address or provider.address
            balance = await provider.get_balance(
                token=token_contract,
                address=target_address,
            )
            return (
                f"Token balance for {target_address} on {token_contract}:\n"
                f"{format_xian_amount(balance)}"
            )
        except ToolException:
            raise
        except Exception as exc:
            raise ToolException(f"Error getting Xian token balance: {exc}") from exc
