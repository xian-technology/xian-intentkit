from __future__ import annotations

from typing import override

from langchain_core.tools import ArgsSchema
from langchain_core.tools.base import ToolException

from intentkit.skills.base import NoArgsSchema
from intentkit.skills.xian.base import XianBaseTool
from intentkit.skills.xian.utils import format_structured


class XianGetChainStatus(XianBaseTool):
    name: str = "xian_get_chain_status"
    description: str = (
        "Get the live Xian node status and, when available, the BDS indexer status."
    )
    args_schema: ArgsSchema | None = NoArgsSchema

    @override
    async def _arun(self) -> str:
        try:
            provider = await self.get_xian_provider()
            node_status = await provider.get_node_status()
            result = [
                f"Network: {node_status.network}",
                f"Node ID: {node_status.node_id}",
                f"Moniker: {node_status.moniker}",
                f"Latest block height: {node_status.latest_block_height}",
                f"Catching up: {node_status.catching_up}",
            ]
            try:
                bds_status = await provider.get_bds_status()
            except Exception as exc:
                result.append(f"BDS status unavailable: {exc}")
            else:
                result.append("BDS status:")
                result.append(format_structured(bds_status.raw))
            return "\n".join(result)
        except ToolException:
            raise
        except Exception as exc:
            raise ToolException(f"Error getting Xian chain status: {exc}") from exc
