# Xian Skills

This skill category integrates the current `xian-tech-py` SDK into IntentKit
for Xian-native agents.

## Requirements

- Agent `wallet_provider` must be `"xian"`.
- Agent `network_id` must be one of:
  - `xian-mainnet`
  - `xian-testnet`
  - `xian-devnet`
  - `xian-localnet`

## Environment

Set RPC URLs for the networks you plan to use:

- `XIAN_MAINNET_RPC_URL`
- `XIAN_TESTNET_RPC_URL`
- `XIAN_DEVNET_RPC_URL`
- `XIAN_LOCALNET_RPC_URL`

Optional chain ID overrides:

- `XIAN_MAINNET_CHAIN_ID`
- `XIAN_TESTNET_CHAIN_ID`
- `XIAN_DEVNET_CHAIN_ID`
- `XIAN_LOCALNET_CHAIN_ID`

`xian-localnet` defaults to `http://127.0.0.1:27657` and `xian-localnet-1`.

## USD Pricing Configuration

Xian USD pricing is deployment-configurable. `xian-intentkit` does not hardcode
live-network token metadata into core asset logic.

Global defaults:

- `XIAN_PRICE_STRATEGY=none|fixed_usd|solana_jupiter`
- `XIAN_PRICE_FIXED_USD`
- `XIAN_PRICE_SOLANA_MINT`
- `XIAN_PRICE_MARKET_URL`

Per-network overrides:

- `XIAN_MAINNET_PRICE_STRATEGY`
- `XIAN_MAINNET_PRICE_FIXED_USD`
- `XIAN_MAINNET_PRICE_SOLANA_MINT`
- `XIAN_MAINNET_PRICE_MARKET_URL`

Equivalent overrides also exist for `XIAN_TESTNET_`, `XIAN_DEVNET_`, and
`XIAN_LOCALNET_`.

Example for a live Xian-based deployment that prices the native asset using a
bridged Solana token via Jupiter:

```bash
XIAN_MAINNET_PRICE_STRATEGY=solana_jupiter
XIAN_MAINNET_PRICE_SOLANA_MINT=<solana-mint-address>
XIAN_MAINNET_PRICE_MARKET_URL=<optional-market-url>
```

If no pricing strategy is configured, Xian balances are still returned but USD
net worth remains `0`.

## What It Covers

- wallet details and token balances
- transfers and approvals
- contract state reads and read-only function calls
- writable contract transactions
- DEX quote and trade helpers for the current Xian DEX
- transaction inspection, transaction-scoped indexed events, and indexed event
  listing
- node and BDS status checks

## Current DEX Coverage

The Xian skill category now includes dedicated tools for the current Xian DEX:

- `xian_dex_quote`
- `xian_dex_trade`

These tools are intentionally narrow:

- they target the current `con_dex`, `con_pairs`, and `con_dex_helper`
  contracts
- they focus on single-pair quote and helper-based buy/sell execution
- they do not replace the generic contract tools for advanced routing or custom
  DEX integrations

For autonomous Xian trading agents, the recommended posture is:

1. use a service node so indexed events are available
2. configure an autonomous task with `trigger_type="xian_event"` and an exact
   `xian_event={contract,event,...}` source
3. let the Xian event trigger service wake immediately from node websocket
   activity and confirm against indexed events before execution
4. quote with `xian_dex_quote`
5. execute with `xian_dex_trade`
6. verify the confirmed transaction and its emitted indexed events with
   `xian_get_transaction` and `xian_get_events_for_tx` before any side effect
   such as posting to social media

The trigger model is intentionally hybrid:

- node websocket traffic is used for low-latency wake-ups
- indexed BDS events and Redis cursors are used as the source of truth
- a periodic indexed sync loop remains enabled so BDS lag or websocket
  reconnects do not cause missed triggers

## Workflow Test Harness

There is now a deterministic workflow test for the exact Xian agent pattern:

1. a Xian indexed event wakes the autonomous trigger path
2. the agent checks a `price_change_pct` threshold
3. the agent executes `xian_dex_trade` to sell `currency`
4. the agent posts to Telegram
5. the agent posts to X

The harness uses:

- the real `XianEventTriggerService`
- the real `xian_dex_trade` skill
- the real `telegram_send_message` skill
- the real `twitter_post_tweet` skill

It intentionally mocks only:

- the indexed Xian event feed
- the DEX wallet/provider transport
- the Telegram/X delivery endpoints

That keeps the workflow test deterministic and credential-free while still
exercising the full IntentKit trigger and skill path.

Run it with:

```bash
cd /Users/endogen/Projekte/xian/xian-intentkit
uv run python scripts/test_xian_trade_social_workflow.py --threshold-pct 3.0
```

The script returns a JSON summary showing:

- which indexed event IDs caused action
- the DEX helper trade call that was submitted
- the captured Telegram payload
- the captured X payload
- the final Redis cursor

The default test feed contains two events:

- event `1` with `price_change_pct=1.5` should be ignored
- event `2` with `price_change_pct=6.4` should trigger the workflow

The matching pytest coverage is:

```bash
cd /Users/endogen/Projekte/xian/xian-intentkit
REDIS_HOST=localhost uv run pytest -q \
  tests/skills/test_telegram.py \
  tests/skills/test_twitter.py \
  tests/core/test_xian_event_triggers.py \
  tests/core/test_xian_trade_social_workflow.py
```

If you want to move from the mock social sinks to real delivery:

- replace the Telegram skill config with a real `bot_token` and `default_chat_id`
- replace the Twitter skill config with real X credentials instead of
  `mock_webhook_url`
- keep the same `xian_event` trigger shape and DEX skill surface
