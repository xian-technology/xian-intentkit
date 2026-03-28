from __future__ import annotations

from typing import override

from langchain_core.tools import ArgsSchema
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from intentkit.skills.xian.base import XianBaseTool
from intentkit.skills.xian.utils import format_xian_amount


class XianGetAllowanceInput(BaseModel):
    spender: str = Field(..., description="Approved spender to inspect.")
    token_contract: str = Field(
        default="currency",
        description="Token contract name. Use 'currency' for native XIAN.",
    )
    owner: str | None = Field(
        default=None,
        description="Owner address. Defaults to the agent wallet address.",
    )


class XianGetAllowance(XianBaseTool):
    name: str = "xian_get_allowance"
    description: str = (
        "Read the current token allowance for a spender on a Xian token contract."
    )
    args_schema: ArgsSchema | None = XianGetAllowanceInput

    @override
    async def _arun(
        self,
        spender: str,
        token_contract: str = "currency",
        owner: str | None = None,
    ) -> str:
        try:
            provider = await self.get_xian_provider()
            allowance = await provider.get_allowance(
                token=token_contract,
                spender=spender,
                owner=owner,
            )
            owner_label = owner or provider.address
            return (
                f"Allowance for spender {spender} on {token_contract} "
                f"from owner {owner_label}:\n{format_xian_amount(allowance)}"
            )
        except ToolException:
            raise
        except Exception as exc:
            raise ToolException(f"Error getting Xian allowance: {exc}") from exc
