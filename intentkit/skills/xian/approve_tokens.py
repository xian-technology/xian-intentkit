from __future__ import annotations

from typing import Literal, override

from langchain_core.tools import ArgsSchema
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from intentkit.skills.xian.base import XianBaseTool
from intentkit.skills.xian.utils import render_submission


class XianApproveTokensInput(BaseModel):
    spender: str = Field(..., description="Contract or address to approve.")
    amount: str = Field(..., description="Allowance amount to approve.")
    token_contract: str = Field(
        default="currency",
        description="Token contract name. Use 'currency' for native XIAN.",
    )
    mode: Literal["async", "checktx", "commit"] = Field(
        default="checktx",
        description="Broadcast mode for the approval transaction.",
    )
    wait_for_tx: bool = Field(
        default=True,
        description="Wait for the final transaction receipt when possible.",
    )


class XianApproveTokens(XianBaseTool):
    name: str = "xian_approve_tokens"
    description: str = "Approve a spender to use tokens from the agent's Xian wallet."
    args_schema: ArgsSchema | None = XianApproveTokensInput

    @override
    async def _arun(
        self,
        spender: str,
        amount: str,
        token_contract: str = "currency",
        mode: Literal["async", "checktx", "commit"] = "checktx",
        wait_for_tx: bool = True,
    ) -> str:
        try:
            provider = await self.get_xian_provider()
            submission = await provider.approve(
                token=token_contract,
                spender=spender,
                amount=amount,
                mode=mode,
                wait_for_tx=wait_for_tx,
            )
            return render_submission(
                f"Submitted Xian approval for spender {spender} on {token_contract}.",
                submission,
            )
        except ToolException:
            raise
        except Exception as exc:
            raise ToolException(f"Error approving Xian tokens: {exc}") from exc
