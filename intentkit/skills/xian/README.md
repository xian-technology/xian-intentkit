# Xian Skills

This skill category integrates `xian-py` into IntentKit for Xian-native agents.

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
- transaction inspection and indexed event listing
- node and BDS status checks
