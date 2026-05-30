"""Shared asset retrieval utilities for agents."""

from __future__ import annotations

import json
import logging
from decimal import Decimal

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import update
from web3 import AsyncWeb3

from intentkit.config.config import config
from intentkit.config.db import get_session
from intentkit.config.redis import get_redis
from intentkit.core.agent import get_agent
from intentkit.models.agent import Agent, AgentTable
from intentkit.models.agent_data import AgentData
from intentkit.utils.error import IntentKitAPIError
from intentkit.wallets.web3 import get_async_web3_client
from intentkit.wallets.xian import get_wallet_provider as get_xian_wallet_provider
from intentkit.wallets.xian_networks import get_xian_price_config, is_xian_network

logger = logging.getLogger(__name__)

JUPITER_PRICE_API_URL = "https://api.jup.ag/price/v3"

# USDC contract addresses for different networks
USDC_ADDRESSES = {
    "base-mainnet": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "ethereum-mainnet": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "arbitrum-mainnet": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "optimism-mainnet": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
    "polygon-mainnet": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
    "bnb-mainnet": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
    "base-sepolia": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
}

# NATION token address for base-mainnet
NATION_ADDRESS = "0x2f74f818e81685c8086dd783837a4605a90474b8"

MORALIS_CHAIN_BY_NETWORK = {
    "ethereum-mainnet": "eth",
    "base-mainnet": "base",
    "polygon-mainnet": "polygon",
    "arbitrum-mainnet": "arbitrum",
    "optimism-mainnet": "optimism",
    "bnb-mainnet": "bsc",
}


class Asset(BaseModel):
    """Model for individual asset with symbol and balance."""

    symbol: str = Field(description="Asset symbol (e.g., ETH, USDC, NATION)")
    balance: Decimal = Field(description="Asset balance as decimal")


class AgentAssets(BaseModel):
    """Simplified agent asset response with wallet net worth and tokens."""

    net_worth: str = Field(description="Total wallet net worth in USD")
    tokens: list[Asset] = Field(description="List of assets with symbol and balance")


async def _get_token_balance(
    web3_client: AsyncWeb3, wallet_address: str, token_address: str
) -> Decimal:
    """Get ERC-20 token balance for a wallet address."""
    try:
        # ERC-20 standard ABI for balanceOf and decimals
        erc20_abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            },
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function",
            },
        ]

        contract = web3_client.eth.contract(
            address=web3_client.to_checksum_address(token_address), abi=erc20_abi
        )

        balance_wei = await contract.functions.balanceOf(
            web3_client.to_checksum_address(wallet_address)
        ).call()
        decimals = await contract.functions.decimals().call()

        # Convert from wei to token units using actual decimals
        balance = Decimal(balance_wei) / Decimal(10**decimals)
        return balance
    except Exception as exc:  # pragma: no cover - log path only
        logger.error("Error getting token balance: %s", exc)
        return Decimal("0")


async def _get_eth_balance(web3_client: AsyncWeb3, wallet_address: str) -> Decimal:
    """Get ETH balance for a wallet address."""
    try:
        balance_wei = await web3_client.eth.get_balance(
            web3_client.to_checksum_address(wallet_address)
        )
        balance = Decimal(balance_wei) / Decimal(10**18)
        return balance
    except Exception as exc:  # pragma: no cover - log path only
        logger.error("Error getting ETH balance: %s", exc)
        return Decimal("0")


async def _get_wallet_net_worth(wallet_address: str, network_id: str | None) -> str:
    """Get wallet net worth using Moralis API."""
    moralis_chain = MORALIS_CHAIN_BY_NETWORK.get(network_id or "")
    if not moralis_chain:
        return "0"

    try:
        async with httpx.AsyncClient() as client:
            url = f"https://deep-index.moralis.io/api/v2.2/wallets/{wallet_address}/net-worth"
            headers = {
                "accept": "application/json",
            }
            if config.moralis_api_key:
                headers["X-API-Key"] = config.moralis_api_key
            params = {
                "exclude_spam": "true",
                "exclude_unverified_contracts": "true",
                "chains": [moralis_chain],
            }

            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("total_networth_usd", "0")
    except Exception as exc:  # pragma: no cover - log path only
        logger.error("Error getting wallet net worth for %s: %s", wallet_address, exc)
        return "0"


def _decimal_to_string(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


async def _get_solana_jupiter_price_usd(solana_mint: str) -> Decimal | None:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                JUPITER_PRICE_API_URL,
                params={"ids": solana_mint},
                timeout=30.0,
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # pragma: no cover - log path only
        logger.error(
            "Error getting Jupiter USD price for Solana mint %s: %s",
            solana_mint,
            exc,
        )
        return None

    result_data = payload
    if "data" in payload and isinstance(payload["data"], dict):
        result_data = payload["data"]

    token_data = result_data.get(solana_mint)
    if not isinstance(token_data, dict) or token_data.get("usdPrice") is None:
        return None

    try:
        return Decimal(str(token_data["usdPrice"]))
    except Exception as exc:  # pragma: no cover - log path only
        logger.error(
            "Invalid Jupiter USD price for Solana mint %s: %s",
            solana_mint,
            exc,
        )
        return None


async def _get_xian_net_worth(
    network_id: str | None,
    native_balance: Decimal | None,
) -> str:
    if not network_id or native_balance is None or native_balance <= 0:
        return "0"

    try:
        price_config = get_xian_price_config(network_id)
    except Exception as exc:  # pragma: no cover - log path only
        logger.error("Error loading Xian price config for %s: %s", network_id, exc)
        return "0"

    if price_config.strategy == "none":
        return "0"

    usd_price: Decimal | None = None
    if price_config.strategy == "fixed_usd":
        usd_price = price_config.fixed_usd
    elif price_config.strategy == "solana_jupiter" and price_config.solana_mint is not None:
        usd_price = await _get_solana_jupiter_price_usd(price_config.solana_mint)

    if usd_price is None:
        return "0"

    return _decimal_to_string(native_balance * usd_price)


async def build_assets_list(
    agent: Agent, agent_data: AgentData, web3_client: AsyncWeb3 | None
) -> list[Asset]:
    """Build the assets list based on network conditions and agent configuration."""
    assets: list[Asset] = []
    network_id: str | None = agent.network_id

    if (
        network_id
        and is_xian_network(network_id)
        and agent_data.xian_wallet_address
        and agent_data.xian_wallet_data
    ):
        provider = get_xian_wallet_provider(json.loads(agent_data.xian_wallet_data))
        balance = await provider.get_balance(
            token="currency",
            address=agent_data.xian_wallet_address,
        )
        assets.append(
            Asset(
                symbol=provider.native_token_symbol,
                balance=Decimal(str(balance)),
            )
        )
        return assets

    if not agent_data or not agent_data.evm_wallet_address or web3_client is None:
        return assets

    wallet_address = agent_data.evm_wallet_address

    # ETH is always included
    eth_balance = await _get_eth_balance(web3_client, wallet_address)
    assets.append(Asset(symbol="ETH", balance=eth_balance))

    if network_id and network_id.endswith("-mainnet"):
        usdc_address = USDC_ADDRESSES.get(str(network_id))
        if usdc_address:
            usdc_balance = await _get_token_balance(web3_client, wallet_address, usdc_address)
            assets.append(Asset(symbol="USDC", balance=usdc_balance))

    if network_id == "base-mainnet":
        nation_balance = await _get_token_balance(web3_client, wallet_address, NATION_ADDRESS)
        assets.append(Asset(symbol="NATION", balance=nation_balance))

    if agent.ticker and agent.token_address:
        lower_addresses = [addr.lower() for addr in USDC_ADDRESSES.values()]
        is_usdc = agent.token_address.lower() in lower_addresses
        is_nation = agent.token_address.lower() == NATION_ADDRESS.lower()

        if not is_usdc and not is_nation:
            custom_balance = await _get_token_balance(
                web3_client, wallet_address, agent.token_address
            )
            assets.append(Asset(symbol=agent.ticker, balance=custom_balance))

    return assets


async def agent_asset(agent_id: str) -> AgentAssets:
    """Fetch wallet net worth and token balances for an agent."""

    cache_key = f"intentkit:agent_assets:{agent_id}"
    redis_client = get_redis()

    agent = await get_agent(agent_id)
    if not agent:
        raise IntentKitAPIError(404, "AgentNotFound", "Agent not found")

    cached_raw = await redis_client.get(cache_key)
    if cached_raw:
        cached_data = json.loads(cached_raw)
        cached_assets = AgentAssets.model_validate(cached_data)
        return cached_assets

    agent_data = await AgentData.get(agent_id)
    evm_wallet_address = getattr(agent_data, "evm_wallet_address", None)
    xian_wallet_address = getattr(agent_data, "xian_wallet_address", None)
    is_xian_agent = bool(
        agent_data
        and xian_wallet_address
        and agent.network_id
        and is_xian_network(agent.network_id)
    )

    if not agent_data or (not evm_wallet_address and not is_xian_agent):
        assets_result = AgentAssets(net_worth="0", tokens=[])
    elif is_xian_agent:
        try:
            tokens = await build_assets_list(agent, agent_data, None)
            native_balance = tokens[0].balance if tokens else None
            net_worth = await _get_xian_net_worth(agent.network_id, native_balance)
            assets_result = AgentAssets(net_worth=net_worth, tokens=tokens)
        except IntentKitAPIError:
            raise
        except Exception as exc:
            raise IntentKitAPIError(
                500, "AgentAssetError", "Failed to retrieve agent assets"
            ) from exc
    elif not agent.network_id:
        assets_result = AgentAssets(net_worth="0", tokens=[])
    else:
        try:
            web3_client = get_async_web3_client(str(agent.network_id))
            tokens = await build_assets_list(agent, agent_data, web3_client)
            net_worth = await _get_wallet_net_worth(str(evm_wallet_address), str(agent.network_id))
            assets_result = AgentAssets(net_worth=net_worth, tokens=tokens)
        except IntentKitAPIError:
            raise
        except Exception as exc:
            raise IntentKitAPIError(
                500, "AgentAssetError", "Failed to retrieve agent assets"
            ) from exc

    assets_payload = assets_result.model_dump(mode="json")

    await redis_client.set(
        cache_key,
        json.dumps(assets_payload),
        ex=3600,
    )

    try:
        async with get_session() as session:
            await session.execute(
                update(AgentTable).where(AgentTable.id == agent_id).values(assets=assets_payload)
            )
            await session.commit()
    except Exception as exc:  # pragma: no cover - db persistence path only
        logger.error("Error updating agent assets cache for %s: %s", agent_id, exc)

    return assets_result


__all__ = [
    "Asset",
    "AgentAssets",
    "USDC_ADDRESSES",
    "NATION_ADDRESS",
    "agent_asset",
    "build_assets_list",
    "_get_wallet_net_worth",
]
