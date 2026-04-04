from __future__ import annotations

from typing import override

from langchain_core.tools import ArgsSchema
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from intentkit.skills.xian.base import XianBaseTool
from intentkit.skills.xian.utils import format_structured


class XianGetEventsForTxInput(BaseModel):
    tx_hash: str = Field(
        ..., description="Transaction hash to inspect for indexed events."
    )


class XianGetEventsForTx(XianBaseTool):
    name: str = "xian_get_events_for_tx"
    description: str = (
        "Fetch the indexed Xian events emitted by a specific transaction hash."
    )
    args_schema: ArgsSchema | None = XianGetEventsForTxInput

    @override
    async def _arun(self, tx_hash: str) -> str:
        try:
            provider = await self.get_xian_provider()
            events = await provider.get_events_for_transaction(tx_hash)
            if not events:
                return f"No indexed events found for transaction {tx_hash}."
            payload = [item.raw for item in events]
            return (
                f"Indexed events for transaction {tx_hash}:\n"
                f"{format_structured(payload)}"
            )
        except ToolException:
            raise
        except Exception as exc:
            raise ToolException(
                f"Error getting Xian events for transaction: {exc}"
            ) from exc
