from __future__ import annotations

from typing import override

from langchain_core.tools import ArgsSchema
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from intentkit.skills.xian.base import XianBaseTool
from intentkit.skills.xian.utils import format_structured, render_receipt


class XianGetTransactionInput(BaseModel):
    tx_hash: str = Field(..., description="Transaction hash to inspect.")


class XianGetTransaction(XianBaseTool):
    name: str = "xian_get_transaction"
    description: str = (
        "Fetch a Xian transaction receipt and, when indexed data is available, "
        "return the indexed transaction summary."
    )
    args_schema: ArgsSchema | None = XianGetTransactionInput

    @override
    async def _arun(self, tx_hash: str) -> str:
        try:
            provider = await self.get_xian_provider()
            receipt = await provider.get_transaction(tx_hash)
            indexed = await provider.get_indexed_transaction(tx_hash)
            result = [render_receipt(receipt)]
            if indexed is not None:
                result.append("Indexed transaction:")
                result.append(format_structured(indexed.raw))
            return "\n".join(result)
        except ToolException:
            raise
        except Exception as exc:
            raise ToolException(f"Error getting Xian transaction: {exc}") from exc
