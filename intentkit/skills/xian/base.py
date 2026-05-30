from __future__ import annotations

from langchain_core.tools.base import ToolException

from intentkit.skills.base import IntentKitSkill
from intentkit.wallets import get_wallet_provider
from intentkit.wallets.xian import XianWalletProvider
from intentkit.wallets.xian_networks import (
    XianNetworkConfig,
    get_xian_network_config,
    is_xian_network,
)


class XianBaseTool(IntentKitSkill):
    """Base class for Xian wallet and contract skills."""

    category: str = "xian"

    def get_agent_network_id(self) -> str | None:
        return self.get_context().agent.network_id

    def ensure_xian_provider(self) -> None:
        agent = self.get_context().agent
        if agent.wallet_provider != "xian":
            raise ToolException("This skill is only available when wallet_provider is 'xian'.")
        if not is_xian_network(agent.network_id):
            raise ToolException(
                "This skill requires a supported Xian network_id such as "
                "'xian-mainnet' or 'xian-localnet'."
            )

    def get_xian_network_config(self) -> XianNetworkConfig:
        network_id = self.get_agent_network_id()
        if not network_id:
            raise ToolException("Agent network_id is not configured.")
        try:
            return get_xian_network_config(network_id)
        except Exception as exc:
            raise ToolException(str(exc)) from exc

    async def get_xian_provider(self) -> XianWalletProvider:
        self.ensure_xian_provider()
        provider = await get_wallet_provider(self.get_context().agent)
        if not isinstance(provider, XianWalletProvider):
            raise ToolException("Resolved wallet provider is not a Xian wallet.")
        return provider
