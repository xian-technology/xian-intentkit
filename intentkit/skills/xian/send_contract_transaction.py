from __future__ import annotations

from typing import Any, Literal, override

from langchain_core.tools import ArgsSchema
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from intentkit.skills.xian.base import XianBaseTool
from intentkit.skills.xian.utils import render_submission


class XianSendContractTransactionInput(BaseModel):
    contract: str = Field(..., description="Contract name.")
    function: str = Field(..., description="Writable function name.")
    kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Function keyword arguments.",
    )
    stamps: int | None = Field(
        default=None,
        description="Optional explicit stamp limit. Defaults to SDK estimation.",
    )
    nonce: int | None = Field(
        default=None,
        description="Optional explicit nonce override.",
    )
    mode: Literal["async", "checktx", "commit"] = Field(
        default="checktx",
        description="Broadcast mode for the transaction.",
    )
    wait_for_tx: bool = Field(
        default=True,
        description="Wait for the final transaction receipt when possible.",
    )


class XianSendContractTransaction(XianBaseTool):
    name: str = "xian_send_contract_transaction"
    description: str = (
        "Submit a writable transaction to a Xian contract function with explicit "
        "broadcast mode and optional stamp/nonce overrides."
    )
    args_schema: ArgsSchema | None = XianSendContractTransactionInput

    @override
    async def _arun(
        self,
        contract: str,
        function: str,
        kwargs: dict[str, Any] | None = None,
        stamps: int | None = None,
        nonce: int | None = None,
        mode: Literal["async", "checktx", "commit"] = "checktx",
        wait_for_tx: bool = True,
    ) -> str:
        try:
            provider = await self.get_xian_provider()
            submission = await provider.send_contract_transaction(
                contract=contract,
                function=function,
                kwargs=kwargs or {},
                stamps=stamps,
                nonce=nonce,
                mode=mode,
                wait_for_tx=wait_for_tx,
            )
            return render_submission(
                f"Submitted Xian contract transaction {contract}.{function}.",
                submission,
            )
        except ToolException:
            raise
        except Exception as exc:
            raise ToolException(
                f"Error sending Xian contract transaction: {exc}"
            ) from exc
