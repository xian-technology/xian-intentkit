from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import aiohttp
from xian_py import XianAsync, to_contract_time
from xian_py.wallet import Wallet

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent.parent
WORKSPACE_DIR = REPO_DIR.parent
DEFAULT_NETWORK_JSON = WORKSPACE_DIR / "xian-stack" / ".localnet" / "network.json"
DEFAULT_DEX_BUNDLE_PATH = (
    WORKSPACE_DIR
    / "xian-configs"
    / "solution-packs"
    / "dex"
    / "contract-bundle.json"
)
TOKEN_FIXTURE = (
    WORKSPACE_DIR / "xian-stack" / "workloads" / "dex_mixed" / "token_fixture.py"
)

TOKEN_DEPLOY_STAMPS = 200_000
PAIR_DEPLOY_STAMPS = 350_000
DEX_DEPLOY_STAMPS = 250_000
HELPER_DEPLOY_STAMPS = 120_000
TOKEN_TX_STAMPS = 12_000
DEX_TX_STAMPS = 80_000
WAIT_TIMEOUT_SECONDS = 120.0
AUTONOMOUS_READY_TIMEOUT_SECONDS = 30.0
AUTONOMOUS_SYNC_GRACE_SECONDS = 3.0


class LiveWorkflowError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dex_source_path(role: str, fallback_name: str) -> Path:
    src_override = os.environ.get("XIAN_DEX_SRC_DIR")
    if src_override:
        return Path(src_override).expanduser() / fallback_name

    bundle_path = Path(
        os.environ.get(
            "XIAN_DEX_BUNDLE",
            os.environ.get("XIAN_DEX_BUNDLE_PATH", DEFAULT_DEX_BUNDLE_PATH),
        )
    ).expanduser()
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    for contract in payload.get("contracts", []):
        if contract.get("role") != role:
            continue
        source_path = (bundle_path.parent / contract["path"]).resolve()
        expected_sha256 = contract.get("sha256")
        if expected_sha256:
            actual_sha256 = _sha256_file(source_path)
            if actual_sha256 != expected_sha256:
                raise LiveWorkflowError(
                    f"DEX bundle sha256 mismatch for {source_path}: "
                    f"expected {expected_sha256}, got {actual_sha256}"
                )
        return source_path
    raise LiveWorkflowError(f"DEX bundle missing role {role!r}: {bundle_path}")


@dataclass(frozen=True)
class LocalnetConfig:
    chain_id: str
    rpc_url: str
    founder_private_key: str


@dataclass(frozen=True)
class DexContracts:
    token_contract: str
    pairs_contract: str
    dex_contract: str
    helper_contract: str
    pair_id: int


@dataclass(frozen=True)
class SocialConfig:
    telegram_bot_token: str
    telegram_chat_id: str
    twitter_auth_mode: Literal["linked_account", "self_key"]
    twitter_consumer_key: str | None = None
    twitter_consumer_secret: str | None = None
    twitter_access_token: str | None = None
    twitter_access_token_secret: str | None = None


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a real end-to-end IntentKit workflow against a live Xian localnet: "
            "watch con_pairs Sync events, trigger on a real price change threshold, "
            "execute a real DEX sell, then post to Telegram and X."
        )
    )
    parser.add_argument(
        "--intentkit-api-url",
        default=_env("INTENTKIT_E2E_API_URL", "http://127.0.0.1:38080"),
        help="Base URL of the running IntentKit local API.",
    )
    parser.add_argument(
        "--network-json",
        default=str(DEFAULT_NETWORK_JSON),
        help="Path to xian-stack .localnet/network.json for founder key and RPC discovery.",
    )
    parser.add_argument(
        "--rpc-url",
        default=_env("INTENTKIT_E2E_RPC_URL"),
        help="Optional Xian RPC URL override.",
    )
    parser.add_argument(
        "--chain-id",
        default=_env("INTENTKIT_E2E_CHAIN_ID"),
        help="Optional Xian chain id override.",
    )
    parser.add_argument(
        "--founder-private-key",
        default=_env("INTENTKIT_E2E_FOUNDER_PRIVATE_KEY"),
        help="Optional founder private key override.",
    )
    parser.add_argument(
        "--model",
        default=_env("INTENTKIT_E2E_MODEL", "gpt-4o-mini"),
        help="IntentKit agent model to use for the live workflow.",
    )
    parser.add_argument(
        "--agent-id",
        default=_env("INTENTKIT_E2E_AGENT_ID"),
        help=(
            "Reuse an existing IntentKit agent instead of creating a new one. "
            "Useful for keeping a pre-linked X account across test runs."
        ),
    )
    parser.add_argument(
        "--threshold-pct",
        type=float,
        default=float(_env("INTENTKIT_E2E_THRESHOLD_PCT", "3.0")),
        help="Minimum absolute price change percentage required to trigger the workflow.",
    )
    parser.add_argument(
        "--trigger-sell-amount",
        type=float,
        default=float(_env("INTENTKIT_E2E_TRIGGER_SELL_AMOUNT", "250")),
        help="Founder-side trade size used to trigger the price movement.",
    )
    parser.add_argument(
        "--agent-sell-amount",
        type=float,
        default=float(_env("INTENTKIT_E2E_AGENT_SELL_AMOUNT", "40")),
        help="Amount of currency the agent should sell once triggered.",
    )
    parser.add_argument(
        "--agent-funding-amount",
        type=float,
        default=float(_env("INTENTKIT_E2E_AGENT_FUNDING_AMOUNT", "250")),
        help="Amount of currency to fund into the agent wallet before triggering.",
    )
    parser.add_argument(
        "--liquidity-currency",
        type=float,
        default=float(_env("INTENTKIT_E2E_LIQUIDITY_CURRENCY", "1000")),
        help="Initial currency liquidity seeded into the live DEX pair.",
    )
    parser.add_argument(
        "--liquidity-token",
        type=float,
        default=float(_env("INTENTKIT_E2E_LIQUIDITY_TOKEN", "1000")),
        help="Initial custom token liquidity seeded into the live DEX pair.",
    )
    parser.add_argument(
        "--allow-live-posts",
        action="store_true",
        help="Required acknowledgement that the workflow will post real Telegram and X messages.",
    )
    parser.add_argument(
        "--twitter-auth-mode",
        choices=["auto", "linked_account", "self_key"],
        default=_env("INTENTKIT_E2E_TWITTER_AUTH_MODE", "auto"),
        help=(
            "How the live runner authenticates the agent to X. "
            "'auto' selects self_key when all self-key env vars are present, "
            "otherwise linked_account."
        ),
    )
    parser.add_argument(
        "--twitter-redirect-uri",
        default=_env("INTENTKIT_E2E_TWITTER_REDIRECT_URI")
        or _env("INTENTKIT_E2E_APP_URL"),
        help=(
            "Redirect URI used when generating the IntentKit /auth/twitter URL for "
            "linked-account mode. It must be under IntentKit APP_BASE_URL."
        ),
    )
    parser.add_argument(
        "--open-auth-url",
        action="store_true",
        help="Open the linked-account X auth URL in the default browser.",
    )
    return parser.parse_args()


def load_localnet_config(
    *,
    network_json: str,
    rpc_url: str | None,
    chain_id: str | None,
    founder_private_key: str | None,
) -> LocalnetConfig:
    if rpc_url and chain_id and founder_private_key:
        return LocalnetConfig(
            chain_id=chain_id,
            rpc_url=rpc_url,
            founder_private_key=founder_private_key,
        )

    path = Path(network_json)
    if not path.exists():
        raise LiveWorkflowError(
            "Missing localnet network.json. Pass --rpc-url/--chain-id/--founder-private-key "
            "or start xian-stack localnet first."
        )
    payload = json.loads(path.read_text())
    return LocalnetConfig(
        chain_id=chain_id or payload["chain_id"],
        rpc_url=rpc_url
        or payload.get("bds", {}).get("service_rpc_url")
        or f"http://127.0.0.1:{payload['nodes'][0]['host_rpc_port']}",
        founder_private_key=founder_private_key or payload["founder_key"],
    )


def load_social_config(
    *,
    twitter_auth_mode: str,
    allow_missing: bool = False,
) -> SocialConfig | None:
    telegram_bot_token = _env("INTENTKIT_E2E_TELEGRAM_BOT_TOKEN")
    telegram_chat_id = _env("INTENTKIT_E2E_TELEGRAM_CHAT_ID")
    if not telegram_bot_token or not telegram_chat_id:
        if allow_missing:
            return None
        raise LiveWorkflowError(
            "Missing required live Telegram env vars: "
            "INTENTKIT_E2E_TELEGRAM_BOT_TOKEN, INTENTKIT_E2E_TELEGRAM_CHAT_ID"
        )

    consumer_key = _env("INTENTKIT_E2E_TWITTER_CONSUMER_KEY")
    consumer_secret = _env("INTENTKIT_E2E_TWITTER_CONSUMER_SECRET")
    access_token = _env("INTENTKIT_E2E_TWITTER_ACCESS_TOKEN")
    access_token_secret = _env("INTENTKIT_E2E_TWITTER_ACCESS_TOKEN_SECRET")

    if twitter_auth_mode == "auto":
        if consumer_key and consumer_secret and access_token and access_token_secret:
            twitter_auth_mode = "self_key"
        else:
            twitter_auth_mode = "linked_account"

    if twitter_auth_mode == "self_key":
        missing = [
            name
            for name, value in {
                "INTENTKIT_E2E_TWITTER_CONSUMER_KEY": consumer_key,
                "INTENTKIT_E2E_TWITTER_CONSUMER_SECRET": consumer_secret,
                "INTENTKIT_E2E_TWITTER_ACCESS_TOKEN": access_token,
                "INTENTKIT_E2E_TWITTER_ACCESS_TOKEN_SECRET": access_token_secret,
            }.items()
            if not value
        ]
        if missing:
            if allow_missing:
                return None
            raise LiveWorkflowError(
                "Missing required live X env vars for self_key mode: "
                + ", ".join(missing)
            )

    return SocialConfig(
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        twitter_auth_mode=twitter_auth_mode,
        twitter_consumer_key=consumer_key,
        twitter_consumer_secret=consumer_secret,
        twitter_access_token=access_token,
        twitter_access_token_secret=access_token_secret,
    )


def deadline_value(*, seconds_from_now: int):
    return to_contract_time(datetime.now(UTC) + timedelta(seconds=seconds_from_now))


def _read_file(path: Path) -> str:
    if not path.exists():
        raise LiveWorkflowError(f"Missing source file: {path}")
    return path.read_text()


def render_pairs_contract(*, dex_contract: str) -> str:
    source = _read_file(_dex_source_path("pairs", "con_pairs.py"))
    needle = 'DEX_ROUTER = "con_dex"'
    if needle not in source:
        raise LiveWorkflowError("Unexpected con_pairs.py format")
    return source.replace(needle, f'DEX_ROUTER = "{dex_contract}"', 1)


def render_dex_contract(*, pairs_contract: str) -> str:
    source = _read_file(_dex_source_path("router", "con_dex.py"))
    needle = 'DEX_PAIRS = "con_pairs"'
    if needle not in source:
        raise LiveWorkflowError("Unexpected con_dex.py format")
    return source.replace(needle, f'DEX_PAIRS = "{pairs_contract}"', 1)


def render_helper_contract(*, dex_contract: str, pairs_contract: str) -> str:
    source = _read_file(_dex_source_path("helper", "con_dex_helper.py"))
    source = source.replace(
        'DEX_CONTRACT = "con_dex"', f'DEX_CONTRACT = "{dex_contract}"', 1
    )
    source = source.replace(
        'DEX_PAIRS = "con_pairs"', f'DEX_PAIRS = "{pairs_contract}"', 1
    )
    return source


def read_token_fixture() -> str:
    return _read_file(TOKEN_FIXTURE)


def _render_submission_error(result: Any) -> str:
    message = getattr(result, "message", None)
    tx_hash = getattr(result, "tx_hash", None)
    return f"submitted={getattr(result, 'submitted', None)} accepted={getattr(result, 'accepted', None)} finalized={getattr(result, 'finalized', None)} tx_hash={tx_hash} message={message}"


def _submission_succeeded(result: Any) -> bool:
    receipt = getattr(result, "receipt", None)
    if not getattr(result, "finalized", False):
        return False
    if receipt is not None:
        return bool(getattr(receipt, "success", False))
    response = getattr(result, "response", None)
    if isinstance(response, dict):
        tx_result = response.get("result", {}).get("tx_result", {})
        if isinstance(tx_result, dict):
            return int(tx_result.get("code", 1)) == 0
    accepted = getattr(result, "accepted", None)
    return bool(accepted) if accepted is not None else False


async def submit_contract(
    client: XianAsync,
    *,
    name: str,
    code: str,
    constructor_args: dict[str, Any] | None = None,
    stamps: int,
) -> None:
    result = await client.submit_contract(
        name=name,
        code=code,
        args=constructor_args,
        stamps=stamps,
        mode="commit",
        wait_for_tx=True,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
    )
    if not _submission_succeeded(result):
        raise LiveWorkflowError(
            f"Contract deployment failed for {name}: {_render_submission_error(result)}"
        )


async def send_tx_or_raise(
    client: XianAsync,
    *,
    contract: str,
    function: str,
    kwargs: dict[str, Any],
    stamps: int,
) -> Any:
    result = await client.send_tx(
        contract=contract,
        function=function,
        kwargs=kwargs,
        stamps=stamps,
        mode="commit",
        wait_for_tx=True,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
    )
    if not _submission_succeeded(result):
        raise LiveWorkflowError(
            f"Transaction failed for {contract}.{function}: {_render_submission_error(result)}"
        )
    return result


async def approve_or_raise(
    client: XianAsync,
    *,
    spender: str,
    token: str,
    amount: float,
) -> None:
    result = await client.approve(
        contract=spender,
        token=token,
        amount=amount,
        stamps=TOKEN_TX_STAMPS,
        mode="commit",
        wait_for_tx=True,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
    )
    if not _submission_succeeded(result):
        raise LiveWorkflowError(
            f"Approval failed for {token} -> {spender}: {_render_submission_error(result)}"
        )


async def wait_for_chain_ready(client: XianAsync) -> None:
    status = await client.get_node_status()
    if not status.network:
        raise LiveWorkflowError("Xian node status did not return a chain/network id")
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        bds = await client.get_bds_status()
        if not bds.catching_up:
            return
        await asyncio.sleep(1)
    raise LiveWorkflowError("BDS did not catch up before the timeout")


async def deploy_live_dex(
    client: XianAsync,
    *,
    founder_address: str,
    suffix: str,
    liquidity_currency: float,
    liquidity_token: float,
) -> DexContracts:
    token_contract = f"con_ixtrade_{suffix}"
    pairs_contract = f"con_ixpairs_{suffix}"
    dex_contract = f"con_ixdex_{suffix}"
    helper_contract = f"con_ixhelper_{suffix}"

    await submit_contract(
        client,
        name=token_contract,
        code=read_token_fixture(),
        constructor_args={
            "owner": founder_address,
            "supply": max(liquidity_token * 100, 100000.0),
            "name": "IntentKit Trade Token",
            "symbol": "IKT",
        },
        stamps=TOKEN_DEPLOY_STAMPS,
    )
    await submit_contract(
        client,
        name=pairs_contract,
        code=render_pairs_contract(dex_contract=dex_contract),
        stamps=PAIR_DEPLOY_STAMPS,
    )
    await submit_contract(
        client,
        name=dex_contract,
        code=render_dex_contract(pairs_contract=pairs_contract),
        stamps=DEX_DEPLOY_STAMPS,
    )
    await submit_contract(
        client,
        name=helper_contract,
        code=render_helper_contract(
            dex_contract=dex_contract,
            pairs_contract=pairs_contract,
        ),
        stamps=HELPER_DEPLOY_STAMPS,
    )

    await approve_or_raise(
        client,
        spender=dex_contract,
        token="currency",
        amount=max(liquidity_currency * 10, 100000.0),
    )
    await approve_or_raise(
        client,
        spender=dex_contract,
        token=token_contract,
        amount=max(liquidity_token * 10, 100000.0),
    )

    await send_tx_or_raise(
        client,
        contract=dex_contract,
        function="addLiquidity",
        kwargs={
            "tokenA": "currency",
            "tokenB": token_contract,
            "amountADesired": liquidity_currency,
            "amountBDesired": liquidity_token,
            "amountAMin": liquidity_currency * 0.95,
            "amountBMin": liquidity_token * 0.95,
            "to": founder_address,
            "deadline": deadline_value(seconds_from_now=300),
        },
        stamps=DEX_TX_STAMPS,
    )

    token0, token1 = sorted(("currency", token_contract))
    pair_id = await client.get_state(pairs_contract, "toks_to_pair", token0, token1)
    if not isinstance(pair_id, int):
        raise LiveWorkflowError(f"Expected a pair id, got {pair_id!r}")

    return DexContracts(
        token_contract=token_contract,
        pairs_contract=pairs_contract,
        dex_contract=dex_contract,
        helper_contract=helper_contract,
        pair_id=pair_id,
    )


async def api_request(
    session: aiohttp.ClientSession,
    *,
    method: str,
    base_url: str,
    path: str,
    json_body: dict[str, Any] | None = None,
) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    async with session.request(method, url, json=json_body) as response:
        text = await response.text()
        if response.status >= 400:
            raise LiveWorkflowError(
                f"IntentKit API request failed ({response.status}) {method} {path}: {text}"
            )
        if not text:
            return None
        return json.loads(text)


def build_agent_payload(
    *,
    suffix: str,
    model: str,
    dex: DexContracts,
    social: SocialConfig,
) -> dict[str, Any]:
    return {
        "id": f"xian-trade-bot-{suffix}",
        "name": f"Xian Trade Bot {suffix}",
        "description": "Live Xian DEX event-triggered trading and social posting agent.",
        "purpose": (
            "Monitor a live Xian DEX pair and react immediately to material price changes."
        ),
        "prompt": (
            "You are an autonomous Xian trading bot. Always use tools, never invent "
            "transaction results. Keep final responses concise and factual."
        ),
        "model": model,
        "temperature": 0,
        "wallet_provider": "xian",
        "network_id": "xian-localnet",
        "skills": {
            "xian": {
                "enabled": True,
                "states": {
                    "xian_dex_trade": "private",
                    "xian_get_events_for_tx": "private",
                    "xian_dex_quote": "private",
                    "xian_list_events": "private",
                },
            },
            "telegram": {
                "enabled": True,
                "states": {"send_message": "private"},
                "bot_token": social.telegram_bot_token,
                "default_chat_id": social.telegram_chat_id,
            },
            "twitter": {
                "enabled": True,
                "states": {"post_tweet": "private"},
                "auth_mode": social.twitter_auth_mode,
                **(
                    {
                        "consumer_key": social.twitter_consumer_key,
                        "consumer_secret": social.twitter_consumer_secret,
                        "access_token": social.twitter_access_token,
                        "access_token_secret": social.twitter_access_token_secret,
                    }
                    if social.twitter_auth_mode == "self_key"
                    else {}
                ),
            },
        },
    }


def build_agent_update_payload(
    *,
    suffix: str,
    model: str,
    dex: DexContracts,
    social: SocialConfig,
) -> dict[str, Any]:
    payload = build_agent_payload(
        suffix=suffix,
        model=model,
        dex=dex,
        social=social,
    )
    payload.pop("id", None)
    return payload


def build_autonomous_payload(
    *,
    dex: DexContracts,
    threshold_pct: float,
    agent_sell_amount: float,
) -> dict[str, Any]:
    prompt = (
        "The JSON event context above is authoritative. "
        f"If trigger_metrics.price_change_pct_abs is below {threshold_pct}, do nothing. "
        "Otherwise execute this exact workflow in order and do not ask follow-up questions:\n"
        f"1. Call xian_dex_trade once with side='sell', sell_token='currency', "
        f"buy_token='{dex.token_contract}', amount='{agent_sell_amount}', slippage=1, "
        f"dex_contract='{dex.dex_contract}', dex_helper_contract='{dex.helper_contract}', "
        f"pairs_contract='{dex.pairs_contract}', mode='commit', wait_for_tx=true.\n"
        "2. Extract the transaction hash from the trade tool result and call "
        "xian_get_events_for_tx for that hash.\n"
        "3. Call telegram_send_message with a concise message that includes the pair id, "
        "the price change percentage, and the trade tx hash.\n"
        "4. Call twitter_post_tweet with the same concise summary.\n"
        "Use only the contract names provided here."
    )
    return {
        "name": "Live DEX social trigger",
        "description": "Sell currency and post to Telegram/X when the pair moves materially.",
        "trigger_type": "xian_event",
        "enabled": True,
        "has_memory": False,
        "prompt": prompt,
        "xian_event": {
            "contract": dex.pairs_contract,
            "event": "Sync",
            "filters": {"pair": str(dex.pair_id)},
            "cooldown_seconds": 120,
            "dex_price_change": {
                "threshold_pct": threshold_pct,
                "direction": "either",
            },
        },
    }


async def upsert_live_agent(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    requested_agent_id: str | None,
    suffix: str,
    model: str,
    dex: DexContracts,
    social: SocialConfig | None,
) -> dict[str, Any]:
    if requested_agent_id:
        if social is None:
            return await api_request(
                session,
                method="GET",
                base_url=base_url,
                path=f"/agents/{requested_agent_id}",
            )
        await api_request(
            session,
            method="PATCH",
            base_url=base_url,
            path=f"/agents/{requested_agent_id}",
            json_body=build_agent_update_payload(
                suffix=suffix,
                model=model,
                dex=dex,
                social=social,
            ),
        )
        return await api_request(
            session,
            method="GET",
            base_url=base_url,
            path=f"/agents/{requested_agent_id}",
        )

    if social is None:
        raise LiveWorkflowError(
            "Cannot create a new live workflow agent without Telegram/X social config."
        )
    return await api_request(
        session,
        method="POST",
        base_url=base_url,
        path="/agents",
        json_body=build_agent_payload(
            suffix=suffix,
            model=model,
            dex=dex,
            social=social,
        ),
    )


async def delete_matching_autonomous_tasks(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    agent_id: str,
    task_name: str,
) -> None:
    tasks = await api_request(
        session,
        method="GET",
        base_url=base_url,
        path=f"/agents/{agent_id}/autonomous",
    )
    for task in tasks:
        if task.get("name") != task_name:
            continue
        await api_request(
            session,
            method="DELETE",
            base_url=base_url,
            path=f"/agents/{agent_id}/autonomous/{task['id']}",
        )


async def wait_for_agent_wallet(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    agent_id: str,
) -> str:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        payload = await api_request(
            session,
            method="GET",
            base_url=base_url,
            path=f"/agents/{agent_id}",
        )
        address = payload.get("xian_wallet_address")
        if isinstance(address, str) and address:
            return address
        await asyncio.sleep(1)
    raise LiveWorkflowError("Agent Xian wallet was not created before the timeout")


async def wait_for_twitter_link(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    agent_id: str,
    timeout_seconds: float = WAIT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        payload = await api_request(
            session,
            method="GET",
            base_url=base_url,
            path=f"/agents/{agent_id}",
        )
        if payload.get("has_twitter_linked"):
            return payload
        await asyncio.sleep(1)
    raise LiveWorkflowError(
        f"Timed out waiting for a linked X account on agent {agent_id}"
    )


async def ensure_twitter_linked(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    agent_id: str,
    redirect_uri: str | None,
    open_auth_url: bool,
) -> dict[str, Any]:
    payload = await api_request(
        session,
        method="GET",
        base_url=base_url,
        path=f"/agents/{agent_id}",
    )
    if payload.get("has_twitter_linked"):
        return payload
    if not redirect_uri:
        raise LiveWorkflowError(
            "Linked-account X mode requires --twitter-redirect-uri or "
            "INTENTKIT_E2E_TWITTER_REDIRECT_URI / INTENTKIT_E2E_APP_URL."
        )

    auth_url_payload = await api_request(
        session,
        method="GET",
        base_url=base_url,
        path=(
            f"/auth/twitter?agent_id={quote(agent_id, safe='')}"
            f"&redirect_uri={quote(redirect_uri, safe='')}"
        ),
    )
    auth_url = auth_url_payload["url"]
    print("\nLink the agent's X account through this URL, then return here:\n")
    print(auth_url)
    print()
    if open_auth_url:
        webbrowser.open(auth_url)

    return await wait_for_twitter_link(
        session,
        base_url=base_url,
        agent_id=agent_id,
    )


async def fund_agent_wallet(
    client: XianAsync,
    *,
    wallet_address: str,
    amount: float,
) -> None:
    result = await client.send(
        amount=amount,
        to_address=wallet_address,
        token="currency",
        stamps=TOKEN_TX_STAMPS,
        mode="commit",
        wait_for_tx=True,
        timeout_seconds=WAIT_TIMEOUT_SECONDS,
    )
    if not _submission_succeeded(result):
        raise LiveWorkflowError(
            f"Funding the agent wallet failed: {_render_submission_error(result)}"
        )


async def wait_for_autonomous_trigger_readiness(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    agent_id: str,
    task_id: str,
) -> None:
    deadline = time.monotonic() + AUTONOMOUS_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        tasks = await api_request(
            session,
            method="GET",
            base_url=base_url,
            path=f"/agents/{agent_id}/autonomous",
        )
        for task in tasks:
            if task["id"] == task_id:
                return
        await asyncio.sleep(1)
    raise LiveWorkflowError("Autonomous task was not visible through the API")


async def trigger_price_move(
    client: XianAsync,
    *,
    dex: DexContracts,
    amount: float,
    founder_address: str,
) -> str:
    result = await send_tx_or_raise(
        client,
        contract=dex.dex_contract,
        function="swapExactTokenForToken",
        kwargs={
            "amountIn": amount,
            "amountOutMin": 0.0001,
            "pair": dex.pair_id,
            "src": "currency",
            "to": founder_address,
            "deadline": deadline_value(seconds_from_now=300),
        },
        stamps=DEX_TX_STAMPS,
    )
    tx_hash = getattr(result, "tx_hash", None)
    if not isinstance(tx_hash, str) or not tx_hash:
        raise LiveWorkflowError("Trigger trade succeeded but returned no tx hash")
    return tx_hash


def _extract_trade_hash_from_text(text: str | None) -> str | None:
    if not text:
        return None
    matches = re.findall(r"Transaction hash: ([A-Fa-f0-9-]+)", text)
    if matches:
        # The DEX tool can emit an approval tx first and the actual trade tx last.
        return matches[-1]
    return None


async def wait_for_workflow_messages(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    agent_id: str,
    chat_id: str,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            payload = await api_request(
                session,
                method="GET",
                base_url=base_url,
                path=f"/agents/{agent_id}/chats/{chat_id}/messages",
            )
        except LiveWorkflowError as exc:
            if "ChatNotFound" in str(exc):
                await asyncio.sleep(2)
                continue
            raise
        messages = payload.get("data", [])
        skill_names = {
            call.get("name")
            for message in messages
            for call in (message.get("skill_calls") or [])
        }
        if {
            "xian_dex_trade",
            "telegram_send_message",
            "twitter_post_tweet",
        }.issubset(skill_names):
            return messages
        await asyncio.sleep(2)
    raise LiveWorkflowError("Timed out waiting for the autonomous workflow messages")


async def verify_agent_trade_on_chain(
    client: XianAsync,
    *,
    messages: list[dict[str, Any]],
    expected_events_contract: str,
) -> dict[str, Any]:
    trade_hash: str | None = None
    for message in messages:
        for call in message.get("skill_calls") or []:
            if call.get("name") != "xian_dex_trade":
                continue
            trade_hash = _extract_trade_hash_from_text(call.get("response"))
            if trade_hash:
                break
        if trade_hash:
            break
    if not trade_hash:
        raise LiveWorkflowError(
            "Could not extract the agent trade tx hash from the skill calls"
        )

    indexed_tx = await client.get_indexed_tx(trade_hash)
    if indexed_tx is None:
        raise LiveWorkflowError(f"Agent trade tx {trade_hash} was not indexed")
    events = await client.get_events_for_tx(trade_hash)
    event_names = {f"{event.contract}:{event.event}" for event in events}
    if f"{expected_events_contract}:Swap" not in event_names:
        raise LiveWorkflowError(
            f"Agent trade tx {trade_hash} did not emit the expected swap event"
        )
    return {
        "trade_tx_hash": trade_hash,
        "indexed_tx_hash": indexed_tx.tx_hash,
        "events": sorted(event_names),
    }


async def run_live_trade_social_workflow(args: argparse.Namespace) -> dict[str, Any]:
    if not args.allow_live_posts:
        raise LiveWorkflowError(
            "Refusing to run without --allow-live-posts because this workflow will send "
            "real Telegram and X messages."
        )

    social = load_social_config(
        twitter_auth_mode=args.twitter_auth_mode,
        allow_missing=bool(args.agent_id),
    )
    network = load_localnet_config(
        network_json=args.network_json,
        rpc_url=args.rpc_url,
        chain_id=args.chain_id,
        founder_private_key=args.founder_private_key,
    )
    founder_wallet = Wallet(private_key=network.founder_private_key)

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30)
    ) as session:
        founder_client = XianAsync(
            network.rpc_url,
            chain_id=network.chain_id,
            wallet=founder_wallet,
            session=session,
        )
        await wait_for_chain_ready(founder_client)

        suffix = hashlib.sha256(str(time.time()).encode("utf-8")).hexdigest()[:8]
        dex = await deploy_live_dex(
            founder_client,
            founder_address=founder_wallet.public_key,
            suffix=suffix,
            liquidity_currency=args.liquidity_currency,
            liquidity_token=args.liquidity_token,
        )

        agent = await upsert_live_agent(
            session,
            base_url=args.intentkit_api_url,
            requested_agent_id=args.agent_id,
            suffix=suffix,
            model=args.model,
            dex=dex,
            social=social,
        )
        agent_id = agent["id"]
        agent_wallet = agent.get("xian_wallet_address") or await wait_for_agent_wallet(
            session,
            base_url=args.intentkit_api_url,
            agent_id=agent_id,
        )
        twitter_link = None
        effective_twitter_auth_mode = (
            social.twitter_auth_mode
            if social is not None
            else (
                "linked_account"
                if agent.get("has_twitter_linked")
                else "existing_agent"
            )
        )
        if effective_twitter_auth_mode == "linked_account" and social is not None:
            twitter_link = await ensure_twitter_linked(
                session,
                base_url=args.intentkit_api_url,
                agent_id=agent_id,
                redirect_uri=args.twitter_redirect_uri,
                open_auth_url=args.open_auth_url,
            )

        await fund_agent_wallet(
            founder_client,
            wallet_address=agent_wallet,
            amount=args.agent_funding_amount,
        )

        autonomous_payload = build_autonomous_payload(
            dex=dex,
            threshold_pct=args.threshold_pct,
            agent_sell_amount=args.agent_sell_amount,
        )
        await delete_matching_autonomous_tasks(
            session,
            base_url=args.intentkit_api_url,
            agent_id=agent_id,
            task_name=autonomous_payload["name"],
        )

        autonomous = await api_request(
            session,
            method="POST",
            base_url=args.intentkit_api_url,
            path=f"/agents/{agent_id}/autonomous",
            json_body=autonomous_payload,
        )
        task_id = autonomous["id"]
        chat_id = autonomous["chat_id"]
        await wait_for_autonomous_trigger_readiness(
            session,
            base_url=args.intentkit_api_url,
            agent_id=agent_id,
            task_id=task_id,
        )
        await asyncio.sleep(AUTONOMOUS_SYNC_GRACE_SECONDS)

        trigger_tx_hash = await trigger_price_move(
            founder_client,
            dex=dex,
            amount=args.trigger_sell_amount,
            founder_address=founder_wallet.public_key,
        )
        messages = await wait_for_workflow_messages(
            session,
            base_url=args.intentkit_api_url,
            agent_id=agent_id,
            chat_id=chat_id,
        )
        on_chain = await verify_agent_trade_on_chain(
            founder_client,
            messages=messages,
            expected_events_contract=dex.pairs_contract,
        )

        skill_sequence = [
            call["name"]
            for message in reversed(messages)
            for call in (message.get("skill_calls") or [])
        ]
        return {
            "agent_id": agent_id,
            "agent_wallet": agent_wallet,
            "twitter_auth_mode": effective_twitter_auth_mode,
            "linked_twitter_username": (
                twitter_link.get("linked_twitter_username") if twitter_link else None
            ),
            "autonomous_task_id": task_id,
            "chat_id": chat_id,
            "trigger_tx_hash": trigger_tx_hash,
            "dex": dex.__dict__,
            "skill_sequence": skill_sequence,
            "on_chain": on_chain,
        }


def main() -> None:
    args = parse_args()
    summary = asyncio.run(run_live_trade_social_workflow(args))
    print(json.dumps(summary, indent=2, sort_keys=True))


__all__ = [
    "main",
    "parse_args",
    "run_live_trade_social_workflow",
]
