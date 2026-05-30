from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from intentkit.config.config import config
from intentkit.utils.error import IntentKitAPIError


@dataclass(frozen=True)
class XianNetworkConfig:
    """Runtime configuration for a supported Xian network."""

    network_id: str
    display_name: str
    rpc_url: str
    chain_id: str
    native_token_symbol: str = "XIAN"


@dataclass(frozen=True)
class XianPriceConfig:
    """Deployment-specific USD pricing configuration for a Xian network."""

    network_id: str
    strategy: Literal["none", "fixed_usd", "solana_jupiter"] = "none"
    fixed_usd: Decimal | None = None
    solana_mint: str | None = None
    market_url: str | None = None


_NETWORK_SPECS: dict[str, dict[str, str | None]] = {
    "xian-mainnet": {
        "display_name": "Xian Mainnet",
        "env_prefix": "XIAN_MAINNET",
        "rpc_env": "XIAN_MAINNET_RPC_URL",
        "chain_env": "XIAN_MAINNET_CHAIN_ID",
        "default_chain_id": "xian-1",
        "default_rpc_url": None,
    },
    "xian-testnet": {
        "display_name": "Xian Testnet",
        "env_prefix": "XIAN_TESTNET",
        "rpc_env": "XIAN_TESTNET_RPC_URL",
        "chain_env": "XIAN_TESTNET_CHAIN_ID",
        "default_chain_id": "xian-testnet-5",
        "default_rpc_url": None,
    },
    "xian-devnet": {
        "display_name": "Xian Devnet",
        "env_prefix": "XIAN_DEVNET",
        "rpc_env": "XIAN_DEVNET_RPC_URL",
        "chain_env": "XIAN_DEVNET_CHAIN_ID",
        "default_chain_id": "xian-testnet-12",
        "default_rpc_url": None,
    },
    "xian-localnet": {
        "display_name": "Xian Localnet",
        "env_prefix": "XIAN_LOCALNET",
        "rpc_env": "XIAN_LOCALNET_RPC_URL",
        "chain_env": "XIAN_LOCALNET_CHAIN_ID",
        "default_chain_id": "xian-localnet-1",
        "default_rpc_url": "http://127.0.0.1:27657",
    },
}


def get_supported_xian_network_ids() -> tuple[str, ...]:
    return tuple(_NETWORK_SPECS)


def is_xian_network(network_id: str | None) -> bool:
    if network_id is None:
        return False
    return network_id.strip().lower() in _NETWORK_SPECS


def _get_network_spec(network_id: str) -> dict[str, str | None]:
    normalized = (network_id or "").strip().lower()
    spec = _NETWORK_SPECS.get(normalized)
    if spec is None:
        supported = ", ".join(sorted(_NETWORK_SPECS))
        raise IntentKitAPIError(
            400,
            "UnsupportedXianNetwork",
            f"Unsupported Xian network '{network_id}'. Supported networks: {supported}.",
        )
    return spec


def _load_xian_setting(
    *,
    env_prefix: str,
    suffix: str,
    default: str | None = None,
) -> str | None:
    network_key = f"{env_prefix}_{suffix}"
    global_key = f"XIAN_{suffix}"
    return config.load(network_key, config.load(global_key, default))


def get_xian_network_config(network_id: str) -> XianNetworkConfig:
    normalized = (network_id or "").strip().lower()
    spec = _get_network_spec(normalized)

    rpc_env = str(spec["rpc_env"])
    chain_env = str(spec["chain_env"])
    default_chain_id = str(spec["default_chain_id"])
    default_rpc_url = spec["default_rpc_url"]

    rpc_url = config.load(rpc_env, default_rpc_url)
    if not rpc_url:
        raise IntentKitAPIError(
            500,
            "XianRpcUrlNotConfigured",
            f"RPC URL is not configured for {normalized}. Set {rpc_env}.",
        )

    chain_id = config.load(chain_env, default_chain_id) or default_chain_id

    return XianNetworkConfig(
        network_id=normalized,
        display_name=str(spec["display_name"]),
        rpc_url=rpc_url,
        chain_id=chain_id,
    )


def get_xian_price_config(network_id: str) -> XianPriceConfig:
    normalized = (network_id or "").strip().lower()
    spec = _get_network_spec(normalized)
    env_prefix = str(spec["env_prefix"])

    raw_strategy = _load_xian_setting(
        env_prefix=env_prefix,
        suffix="PRICE_STRATEGY",
        default="none",
    )
    strategy = (raw_strategy or "none").strip().lower()
    if strategy not in {"none", "fixed_usd", "solana_jupiter"}:
        raise IntentKitAPIError(
            500,
            "InvalidXianPriceStrategy",
            "Invalid Xian price strategy "
            f"'{raw_strategy}' for {normalized}. "
            "Supported strategies: none, fixed_usd, solana_jupiter.",
        )

    fixed_usd_raw = _load_xian_setting(
        env_prefix=env_prefix,
        suffix="PRICE_FIXED_USD",
    )
    fixed_usd: Decimal | None = None
    if fixed_usd_raw is not None:
        try:
            fixed_usd = Decimal(fixed_usd_raw)
        except Exception as exc:
            raise IntentKitAPIError(
                500,
                "InvalidXianFixedUsdPrice",
                f"Invalid fixed USD price '{fixed_usd_raw}' for {normalized}.",
            ) from exc

    solana_mint = _load_xian_setting(
        env_prefix=env_prefix,
        suffix="PRICE_SOLANA_MINT",
    )
    market_url = _load_xian_setting(
        env_prefix=env_prefix,
        suffix="PRICE_MARKET_URL",
    )

    if strategy == "fixed_usd" and fixed_usd is None:
        raise IntentKitAPIError(
            500,
            "MissingXianFixedUsdPrice",
            f"Set {env_prefix}_PRICE_FIXED_USD or XIAN_PRICE_FIXED_USD for {normalized}.",
        )
    if strategy == "solana_jupiter" and not solana_mint:
        raise IntentKitAPIError(
            500,
            "MissingXianSolanaMint",
            f"Set {env_prefix}_PRICE_SOLANA_MINT or XIAN_PRICE_SOLANA_MINT for {normalized}.",
        )

    return XianPriceConfig(
        network_id=normalized,
        strategy=strategy,
        fixed_usd=fixed_usd,
        solana_mint=solana_mint,
        market_url=market_url,
    )


__all__ = [
    "XianNetworkConfig",
    "XianPriceConfig",
    "get_supported_xian_network_ids",
    "get_xian_network_config",
    "get_xian_price_config",
    "is_xian_network",
]
