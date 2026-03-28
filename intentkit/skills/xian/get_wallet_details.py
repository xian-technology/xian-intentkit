from __future__ import annotations

from typing import override

from langchain_core.tools import ArgsSchema
from langchain_core.tools.base import ToolException

from intentkit.skills.base import NoArgsSchema
from intentkit.skills.xian.base import XianBaseTool
from intentkit.skills.xian.utils import format_xian_amount


class XianGetWalletDetails(XianBaseTool):
    name: str = "xian_get_wallet_details"
    description: str = (
        "Get the connected Xian wallet address, configured network, chain ID, "
        "RPC endpoint, and native XIAN balance."
    )
    args_schema: ArgsSchema | None = NoArgsSchema

    @override
    async def _arun(self) -> str:
        try:
            provider = await self.get_xian_provider()
            network = self.get_xian_network_config()
            balance = await provider.get_balance(token="currency")
            return (
                f"Xian wallet address: {provider.address}\n"
                f"Network: {network.display_name} ({network.network_id})\n"
                f"Chain ID: {network.chain_id}\n"
                f"RPC URL: {network.rpc_url}\n"
                f"Balance: {format_xian_amount(balance)} {provider.native_token_symbol}"
            )
        except ToolException:
            raise
        except Exception as exc:
            raise ToolException(f"Error getting Xian wallet details: {exc}") from exc
