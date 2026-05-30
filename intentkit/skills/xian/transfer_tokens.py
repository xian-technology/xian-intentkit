from __future__ import annotations

from typing import Literal, override

from langchain_core.tools import ArgsSchema
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from intentkit.skills.xian.base import XianBaseTool
from intentkit.skills.xian.utils import render_submission


class XianTransferTokensInput(BaseModel):
    to_address: str = Field(..., description="Destination Xian wallet address.")
    amount: str = Field(
        ...,
        description="Amount to transfer. Supports integer or decimal token values.",
    )
    token_contract: str = Field(
        default="currency",
        description="Token contract name. Use 'currency' for native XIAN.",
    )
    mode: Literal["async", "checktx", "commit"] = Field(
        default="checktx",
        description="Broadcast mode for the transaction.",
    )
    wait_for_tx: bool = Field(
        default=True,
        description="Wait for the final transaction receipt when possible.",
    )


class XianTransferTokens(XianBaseTool):
    name: str = "xian_transfer_tokens"
    description: str = (
        "Transfer Xian native currency or another Xian token contract to a destination address."
    )
    args_schema: ArgsSchema | None = XianTransferTokensInput

    @override
    async def _arun(
        self,
        to_address: str,
        amount: str,
        token_contract: str = "currency",
        mode: Literal["async", "checktx", "commit"] = "checktx",
        wait_for_tx: bool = True,
    ) -> str:
        try:
            provider = await self.get_xian_provider()
            submission = await provider.transfer(
                token=token_contract,
                to_address=to_address,
                amount=amount,
                mode=mode,
                wait_for_tx=wait_for_tx,
            )
            return render_submission(
                f"Submitted Xian transfer of {amount} on {token_contract} to {to_address}.",
                submission,
            )
        except ToolException:
            raise
        except Exception as exc:
            raise ToolException(f"Error transferring on Xian: {exc}") from exc
