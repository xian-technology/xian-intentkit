from __future__ import annotations

from typing import Any, override

from langchain_core.tools import ArgsSchema
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from intentkit.skills.xian.base import XianBaseTool
from intentkit.skills.xian.utils import format_structured


class XianCallContractInput(BaseModel):
    contract: str = Field(..., description="Contract name.")
    function: str = Field(..., description="Read-only function name.")
    kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Function keyword arguments.",
    )


class XianCallContract(XianBaseTool):
    name: str = "xian_call_contract"
    description: str = (
        "Call a read-only Xian contract function using the SDK simulation path."
    )
    args_schema: ArgsSchema | None = XianCallContractInput

    @override
    async def _arun(
        self,
        contract: str,
        function: str,
        kwargs: dict[str, Any] | None = None,
    ) -> str:
        try:
            provider = await self.get_xian_provider()
            result = await provider.call_contract(contract, function, kwargs or {})
            return f"Result from {contract}.{function}:\n{format_structured(result)}"
        except ToolException:
            raise
        except Exception as exc:
            raise ToolException(f"Error calling Xian contract: {exc}") from exc
