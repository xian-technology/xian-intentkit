from __future__ import annotations

from typing import override

from langchain_core.tools import ArgsSchema
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from intentkit.skills.xian.base import XianBaseTool
from intentkit.skills.xian.utils import format_structured


class XianReadContractStateInput(BaseModel):
    contract: str = Field(..., description="Contract name.")
    variable: str = Field(..., description="State variable name.")
    keys: list[str] = Field(
        default_factory=list,
        description="Optional state key suffix values.",
    )


class XianReadContractState(XianBaseTool):
    name: str = "xian_read_contract_state"
    description: str = (
        "Read a raw state value from a Xian contract variable and optional key path."
    )
    args_schema: ArgsSchema | None = XianReadContractStateInput

    @override
    async def _arun(
        self,
        contract: str,
        variable: str,
        keys: list[str] | None = None,
    ) -> str:
        try:
            provider = await self.get_xian_provider()
            state_value = await provider.get_state(contract, variable, *(keys or []))
            key_suffix = f":{':'.join(keys or [])}" if keys else ""
            return (
                f"State value for {contract}.{variable}{key_suffix}:\n"
                f"{format_structured(state_value)}"
            )
        except ToolException:
            raise
        except Exception as exc:
            raise ToolException(f"Error reading Xian contract state: {exc}") from exc
