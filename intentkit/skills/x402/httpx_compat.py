"""Compatibility httpx client for x402 v2 transport with signer adapter.

This module replaces legacy event-hook based handling with the x402 v2
transport flow while keeping v1 seller compatibility.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any, cast, override

import aiohttp
import httpx
from x402 import max_amount, x402Client
from x402.http.x402_http_client import x402HTTPClient
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.mechanisms.evm.types import DOMAIN_TYPES, TypedDataDomain, TypedDataField
from xian_py.x402 import (
    PAYMENT_REQUIRED_HEADER,
    PAYMENT_SIGNATURE_HEADER,
    XianX402PaymentRequirement,
    canonical_amount,
    decode_json_header,
    sign_xian_x402_payment,
)

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    """Base class for payment-related errors."""


class MissingRequestConfigError(PaymentError):
    """Raised when request configuration is missing."""


def _is_xian_network(network: Any) -> bool:
    return isinstance(network, str) and network.startswith("xian:")


def _is_xian_signer(signer: Any) -> bool:
    return callable(getattr(signer, "sign_msg", None)) and isinstance(
        getattr(signer, "public_key", None),
        str,
    )


def _decimal_amount(value: Any) -> Decimal:
    try:
        return Decimal(canonical_amount(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid x402 payment amount: {value!r}") from exc


class IntentKitEvmSignerAdapter:
    """Adapter to satisfy x402 ClientEvmSigner protocol."""

    _signer: Any

    def __init__(self, signer: Any) -> None:
        self._signer = signer

    @property
    def address(self) -> str:
        return getattr(self._signer, "address")

    def sign_typed_data(
        self,
        domain: TypedDataDomain,
        types: dict[str, list[TypedDataField]],
        primary_type: str,
        message: dict[str, Any],
    ) -> bytes:
        # primary_type is unused in this adapter implementation
        _ = primary_type
        domain_data = {
            "name": domain.name,
            "version": domain.version,
            "chainId": domain.chain_id,
            "verifyingContract": domain.verifying_contract,
        }

        message_types: dict[str, list[dict[str, str]]] = {
            "EIP712Domain": list(DOMAIN_TYPES.get("EIP712Domain", []))
        }
        for type_name, fields in types.items():
            message_types[type_name] = [
                {"name": field.name, "type": field.type} for field in fields
            ]

        signature = self._signer.sign_typed_data(
            domain_data=domain_data,
            message_types=message_types,
            message_data=message,
            full_message=None,
        )
        return _signature_to_bytes(signature)


def _signature_to_bytes(signature: Any) -> bytes:
    if isinstance(signature, bytes):
        return signature
    if isinstance(signature, bytearray):
        return bytes(signature)
    if isinstance(signature, str):
        return bytes.fromhex(signature.removeprefix("0x"))
    if hasattr(signature, "signature"):
        return _signature_to_bytes(signature.signature)
    if hasattr(signature, "hex"):
        return bytes.fromhex(signature.hex().removeprefix("0x"))
    raise ValueError(f"Unsupported signature type: {type(signature).__name__}")


def _normalize_payment_error(exc: Exception) -> str:
    if isinstance(exc, ValueError):
        return f"Invalid payment required response: {exc}"
    if isinstance(exc, asyncio.TimeoutError):
        return f"Timeout during RPC or payment operation: {exc}"
    if isinstance(exc, aiohttp.ClientError):
        return f"Network error during RPC or payment operation: {exc}"
    return f"{type(exc).__name__}: {exc}"


def _wrap_selector(
    selector: Callable[[int, list[Any]], Any] | None,
    hooks: "X402HttpxCompatHooks | None",
) -> Callable[[int, list[Any]], Any] | None:
    if hooks is None:
        return selector

    def wrapped(version: int, requirements: list[Any]) -> Any:
        if not requirements:
            raise ValueError("Payment requirements list is empty.")
        selected = selector(version, requirements) if selector else requirements[0]
        hooks.last_selected_requirements = selected
        return selected

    return wrapped


class X402HttpxCompatHooks:
    """Compatibility container to expose last_paid_to."""

    last_paid_to: str | None
    last_payment_id: str | None
    last_payment_payload: Any | None
    last_payment_required: Any | None
    last_payment_required_version: int | None
    last_payment_error: str | None
    last_selected_requirements: Any | None

    def __init__(self) -> None:
        self.last_paid_to = None
        self.last_payment_id = None
        self.last_payment_payload = None
        self.last_payment_required = None
        self.last_payment_required_version = None
        self.last_payment_error = None
        self.last_selected_requirements = None


class X402CompatTransport(httpx.AsyncBaseTransport):
    """Async transport that handles 402 responses using x402 v2 client."""

    RETRY_KEY: str = "_x402_is_retry"

    _client: x402Client | None
    _http_client: x402HTTPClient | None
    _xian_signer: Any | None
    _transport: httpx.AsyncBaseTransport
    _payment_hooks: X402HttpxCompatHooks

    def __init__(
        self,
        client: x402Client | None,
        payment_hooks: X402HttpxCompatHooks,
        xian_signer: Any | None = None,
        max_value: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = client
        self._http_client = x402HTTPClient(client) if client is not None else None
        self._xian_signer = xian_signer
        self._max_value = max_value
        self._transport = transport or httpx.AsyncHTTPTransport()
        self._payment_hooks = payment_hooks

    @override
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._transport.handle_async_request(request)
        if response.status_code != 402:
            return response

        if request.extensions.get(self.RETRY_KEY):
            return response

        body_data: Any = None
        try:
            _ = await response.aread()
            try:
                body_data = response.json()
            except Exception:
                body_data = None

            if self._xian_signer is not None:
                payment_headers = self._create_xian_payment_headers(
                    response.headers,
                    body_data,
                    response.content,
                )
                return await self._retry_with_payment_headers(
                    request,
                    payment_headers,
                )

            if self._client is None or self._http_client is None:
                raise PaymentError("No x402 payment client is configured.")

            def get_header(name: str) -> str | None:
                return response.headers.get(name)

            payment_required = self._http_client.get_payment_required_response(
                get_header, body_data
            )
            self._payment_hooks.last_payment_required = payment_required
            self._payment_hooks.last_payment_required_version = getattr(
                payment_required, "x402_version", None
            )
            payment_payload = await self._client.create_payment_payload(payment_required)
            # Cast to Any to handle dynamic attributes like 'accepted' which might not be statically typed
            payment_payload = cast(Any, payment_payload)

            if hasattr(payment_payload, "accepted"):
                self._payment_hooks.last_selected_requirements = payment_payload.accepted
                self._payment_hooks.last_paid_to = payment_payload.accepted.pay_to
            elif self._payment_hooks.last_selected_requirements is not None:
                pay_to = getattr(self._payment_hooks.last_selected_requirements, "pay_to", None)
                if pay_to:
                    self._payment_hooks.last_paid_to = pay_to

            payment_headers = self._http_client.encode_payment_signature_header(payment_payload)

            return await self._retry_with_payment_headers(request, payment_headers)
        except PaymentError:
            raise
        except Exception as exc:
            error_message = _normalize_payment_error(exc)
            self._payment_hooks.last_payment_error = error_message
            try:
                response_body = body_data if body_data is not None else response.text
            except Exception:
                response_body = body_data

            debug_context = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": response_body,
                "url": str(request.url),
            }
            logger.debug(
                "Failed to parse payment required response",
                extra=debug_context,
                exc_info=exc,
            )
            raise PaymentError(
                "Failed to handle payment: "
                f"{error_message}; "
                f"status_code={response.status_code}; "
                f"url={request.url}; "
                f"headers={dict(response.headers)}; "
                f"body={response_body}"
            ) from exc

    def _create_xian_payment_headers(
        self,
        headers: httpx.Headers,
        body_data: Any,
        body: bytes,
    ) -> dict[str, str]:
        payment_required = _xian_payment_required_payload(headers, body_data, body)
        self._payment_hooks.last_payment_required = payment_required
        self._payment_hooks.last_payment_required_version = payment_required.get(
            "x402Version"
        ) or payment_required.get("x402_version")
        requirement = _select_xian_requirement(payment_required)
        if requirement is None:
            raise PaymentError(
                "Payment required response did not include a Xian exact payment option."
            )

        if self._max_value is not None:
            required = _decimal_amount(requirement.amount)
            max_allowed = _decimal_amount(self._max_value)
            if required > max_allowed:
                raise PaymentError(
                    f"Payment amount {requirement.amount} exceeds max_value {self._max_value}."
                )

        payment_payload = sign_xian_x402_payment(requirement, self._xian_signer)
        self._payment_hooks.last_selected_requirements = requirement
        self._payment_hooks.last_paid_to = requirement.pay_to
        self._payment_hooks.last_payment_id = payment_payload.payment_id
        self._payment_hooks.last_payment_payload = payment_payload
        return {PAYMENT_SIGNATURE_HEADER: payment_payload.to_header()}

    async def _retry_with_payment_headers(
        self,
        request: httpx.Request,
        payment_headers: dict[str, str],
    ) -> httpx.Response:
        new_headers = dict(request.headers)
        new_headers.update(payment_headers)
        new_headers["Access-Control-Expose-Headers"] = "PAYMENT-RESPONSE,X-PAYMENT-RESPONSE"

        new_extensions = dict(request.extensions)
        new_extensions[self.RETRY_KEY] = True

        retry_request = httpx.Request(
            method=request.method,
            url=request.url,
            headers=new_headers,
            content=request.content,
            extensions=new_extensions,
        )

        return await self._transport.handle_async_request(retry_request)

    @override
    async def aclose(self) -> None:
        await self._transport.aclose()


def _xian_payment_required_payload(
    headers: httpx.Headers,
    body_data: Any,
    body: bytes,
) -> dict[str, Any]:
    header_value = headers.get(PAYMENT_REQUIRED_HEADER)
    if header_value:
        return decode_json_header(header_value)
    if isinstance(body_data, dict):
        return body_data
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("402 response body is not valid UTF-8.") from exc
    try:
        payload = json.loads(decoded)
    except ValueError as exc:
        raise ValueError("402 response has no payment requirements.") from exc
    if not isinstance(payload, dict):
        raise ValueError("402 response body must be a JSON object.")
    return payload


def _select_xian_requirement(
    payment_required: dict[str, Any],
) -> XianX402PaymentRequirement | None:
    accepts = payment_required.get("accepts") or payment_required.get("paymentDetails")
    if not isinstance(accepts, list):
        return None
    for index, item in enumerate(accepts):
        if not isinstance(item, dict):
            continue
        if item.get("scheme", "exact") != "exact":
            continue
        if not _is_xian_network(item.get("network")):
            continue
        return XianX402PaymentRequirement.from_payment_required(
            payment_required,
            selected_index=index,
        )
    return None


def _build_x402_client(
    signer: Any,
    max_value: int | None = None,
    payment_requirements_selector: Callable[[int, list[Any]], Any] | None = None,
    hooks: "X402HttpxCompatHooks | None" = None,
) -> x402Client:
    wrapped_selector = _wrap_selector(payment_requirements_selector, hooks)
    client = x402Client(payment_requirements_selector=wrapped_selector)
    policies = [max_amount(max_value)] if max_value is not None else None
    adapter = IntentKitEvmSignerAdapter(signer)
    _ = register_exact_evm_client(client, adapter, policies=policies)
    return client


def x402_compat_payment_hooks(
    account: Any,
    max_value: int | None = None,
    payment_requirements_selector: Callable[[int, list[Any]], Any] | None = None,
) -> tuple[dict[str, list[Any]], X402HttpxCompatHooks]:
    """Return empty hooks and a compatibility hooks container."""
    hooks = X402HttpxCompatHooks()
    if not _is_xian_signer(account):
        _ = _build_x402_client(
            account,
            max_value=max_value,
            payment_requirements_selector=payment_requirements_selector,
            hooks=hooks,
        )
    return {"request": [], "response": []}, hooks


class X402HttpxCompatClient(httpx.AsyncClient):
    """AsyncClient with built-in x402 v2 transport and v1 compatibility."""

    payment_hooks: X402HttpxCompatHooks

    def __init__(
        self,
        account: Any,
        max_value: int | None = None,
        payment_requirements_selector: Callable[[int, list[Any]], Any] | None = None,
        **kwargs: Any,
    ) -> None:
        payment_hooks = X402HttpxCompatHooks()
        xian_signer = account if _is_xian_signer(account) else None
        client = (
            None
            if xian_signer is not None
            else _build_x402_client(
                account,
                max_value=max_value,
                payment_requirements_selector=payment_requirements_selector,
                hooks=payment_hooks,
            )
        )
        transport = X402CompatTransport(
            client=client,
            payment_hooks=payment_hooks,
            xian_signer=xian_signer,
            max_value=max_value,
            transport=kwargs.pop("transport", None),
        )
        super().__init__(transport=transport, **kwargs)
        self.payment_hooks = payment_hooks
