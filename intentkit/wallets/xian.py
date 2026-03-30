from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from xian_py import IndexedTransaction, XianAsync
from xian_py import Wallet as XianSignerWallet

from intentkit.wallets.xian_networks import (
    XianNetworkConfig,
    get_xian_network_config,
)


class XianWalletProvider:
    """Wallet provider backed by xian-tech-py / xian_py for Ed25519 Xian accounts."""

    def __init__(
        self,
        *,
        private_key: str,
        network_config: XianNetworkConfig,
    ) -> None:
        self._wallet = XianSignerWallet(private_key=private_key)
        self._network_config = network_config

    @property
    def address(self) -> str:
        return self._wallet.public_key

    @property
    def network_id(self) -> str:
        return self._network_config.network_id

    @property
    def chain_id(self) -> str:
        return self._network_config.chain_id

    @property
    def rpc_url(self) -> str:
        return self._network_config.rpc_url

    @property
    def native_token_symbol(self) -> str:
        return self._network_config.native_token_symbol

    @property
    def wallet(self) -> XianSignerWallet:
        return self._wallet

    def get_address(self) -> str:
        return self.address

    async def get_balance(
        self,
        *,
        token: str = "currency",
        address: str | None = None,
    ) -> Any:
        async with self._client() as client:
            return await client.get_balance(
                address=address or self.address,
                contract=token,
            )

    async def transfer(
        self,
        *,
        token: str,
        to_address: str,
        amount: int | float | str | Decimal,
        mode: Literal["async", "checktx", "commit"] | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        stamps: int | None = None,
    ) -> Any:
        async with self._client() as client:
            return await client.send(
                amount=amount,
                to_address=to_address,
                token=token,
                stamps=stamps,
                mode=mode,
                wait_for_tx=wait_for_tx,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )

    async def approve(
        self,
        *,
        token: str,
        spender: str,
        amount: int | float | str | Decimal,
        mode: Literal["async", "checktx", "commit"] | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        stamps: int | None = None,
    ) -> Any:
        async with self._client() as client:
            return await client.approve(
                contract=spender,
                token=token,
                amount=amount,
                stamps=stamps,
                mode=mode,
                wait_for_tx=wait_for_tx,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )

    async def get_allowance(
        self,
        *,
        token: str,
        spender: str,
        owner: str | None = None,
    ) -> Any:
        async with self._client() as client:
            return await client.token(token).allowance(spender, owner=owner)

    async def simulate_contract(
        self,
        contract: str,
        function: str,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._client() as client:
            return await client.simulate(contract, function, kwargs)

    async def call_contract(
        self,
        contract: str,
        function: str,
        kwargs: dict[str, Any],
    ) -> Any:
        async with self._client() as client:
            return await client.call(contract, function, kwargs)

    async def send_contract_transaction(
        self,
        *,
        contract: str,
        function: str,
        kwargs: dict[str, Any],
        stamps: int | None = None,
        nonce: int | None = None,
        mode: Literal["async", "checktx", "commit"] | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> Any:
        async with self._client() as client:
            return await client.send_tx(
                contract=contract,
                function=function,
                kwargs=kwargs,
                stamps=stamps,
                nonce=nonce,
                chain_id=self.chain_id,
                mode=mode,
                wait_for_tx=wait_for_tx,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )

    async def get_state(
        self,
        contract: str,
        variable: str,
        *keys: str,
    ) -> Any:
        async with self._client() as client:
            return await client.get_state(contract, variable, *keys)

    async def get_contract_source(self, contract: str) -> str | None:
        async with self._client() as client:
            return await client.get_contract(contract)

    async def get_contract_code(self, contract: str) -> str | None:
        async with self._client() as client:
            return await client.get_contract_code(contract)

    async def get_transaction(self, tx_hash: str) -> Any:
        async with self._client() as client:
            return await client.get_tx(tx_hash)

    async def wait_for_transaction_receipt(
        self,
        tx_hash: str,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> Any:
        async with self._client() as client:
            return await client.wait_for_tx(
                tx_hash,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )

    async def list_events(
        self,
        *,
        contract: str,
        event: str,
        limit: int = 100,
        offset: int = 0,
        after_id: int | None = None,
    ) -> list[Any]:
        async with self._client() as client:
            return await client.list_events(
                contract,
                event,
                limit=limit,
                offset=offset,
                after_id=after_id,
            )

    async def get_node_status(self) -> Any:
        async with self._client() as client:
            return await client.get_node_status()

    async def get_bds_status(self) -> Any:
        async with self._client() as client:
            return await client.get_bds_status()

    async def get_indexed_transaction(self, tx_hash: str) -> Any:
        async with self._client() as client:
            indexed_tx = await client.get_indexed_tx(tx_hash)
        if (
            indexed_tx is not None
            and indexed_tx.tx_hash is None
            and isinstance(indexed_tx.raw.get("hash"), str)
        ):
            return IndexedTransaction.from_dict(
                {
                    **indexed_tx.raw,
                    "tx_hash": indexed_tx.raw["hash"],
                }
            )
        return indexed_tx

    def _client(self) -> XianAsync:
        return XianAsync(
            self.rpc_url,
            chain_id=self.chain_id,
            wallet=self._wallet,
        )


def create_xian_wallet(network_id: str) -> dict[str, str]:
    network_config = get_xian_network_config(network_id)
    wallet = XianSignerWallet()
    return {
        "address": wallet.public_key,
        "public_key": wallet.public_key,
        "private_key": wallet.private_key,
        "network_id": network_config.network_id,
        "chain_id": network_config.chain_id,
        "provider": "xian",
    }


def get_wallet_provider(xian_wallet_data: dict[str, Any]) -> XianWalletProvider:
    network_id = str(xian_wallet_data.get("network_id") or "")
    return XianWalletProvider(
        private_key=str(xian_wallet_data["private_key"]),
        network_config=get_xian_network_config(network_id),
    )


def get_wallet_signer(xian_wallet_data: dict[str, Any]) -> XianSignerWallet:
    return XianSignerWallet(private_key=str(xian_wallet_data["private_key"]))


__all__ = [
    "XianWalletProvider",
    "create_xian_wallet",
    "get_wallet_provider",
    "get_wallet_signer",
]
