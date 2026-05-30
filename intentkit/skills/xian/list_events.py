from __future__ import annotations

from typing import override

from langchain_core.tools import ArgsSchema
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from intentkit.skills.xian.base import XianBaseTool
from intentkit.skills.xian.utils import format_structured


class XianListEventsInput(BaseModel):
    contract: str = Field(..., description="Contract name.")
    event: str = Field(..., description="Event name.")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum events to return.")
    offset: int = Field(default=0, ge=0, description="Offset when after_id is not used.")
    after_id: int | None = Field(
        default=None,
        description="Resume listing from the first event after this indexed event ID.",
    )


class XianListEvents(XianBaseTool):
    name: str = "xian_list_events"
    description: str = "List indexed events for a Xian contract and event name."
    args_schema: ArgsSchema | None = XianListEventsInput

    @override
    async def _arun(
        self,
        contract: str,
        event: str,
        limit: int = 20,
        offset: int = 0,
        after_id: int | None = None,
    ) -> str:
        try:
            provider = await self.get_xian_provider()
            events = await provider.list_events(
                contract=contract,
                event=event,
                limit=limit,
                offset=offset,
                after_id=after_id,
            )
            if not events:
                return f"No indexed events found for {contract}.{event}."
            payload = [item.raw for item in events]
            return f"Indexed events for {contract}.{event}:\n{format_structured(payload)}"
        except ToolException:
            raise
        except Exception as exc:
            raise ToolException(f"Error listing Xian events: {exc}") from exc
