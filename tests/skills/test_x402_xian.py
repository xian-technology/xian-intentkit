from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from xian_py import (
    XianX402PaymentPayload,
    XianX402PaymentRequirement,
    encode_json_header,
    sign_xian_x402_payment,
    verify_xian_x402_payment,
)
from xian_py.wallet import Wallet
from xian_py.x402 import PAYMENT_RESPONSE_HEADER, PAYMENT_SIGNATURE_HEADER

from intentkit.skills.x402.check_price import _format_raw_payment_requirements
from intentkit.skills.x402.httpx_compat import PaymentError, X402HttpxCompatClient
from intentkit.skills.x402.pay import X402Pay


def _requirement() -> XianX402PaymentRequirement:
    return XianX402PaymentRequirement(
        network="xian:xian-localnet-1",
        asset="currency",
        amount="0.001",
        pay_to="seller-public-key",
        resource="https://seller.test/data",
        settlement_contract="con_x402_settlement",
        description="Xian paid resource",
    )


@pytest.mark.asyncio
async def test_x402_client_pays_xian_requirement_and_retries() -> None:
    wallet = Wallet()
    requirement = _requirement()
    captured_payloads: list[XianX402PaymentPayload] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payment_header = request.headers.get(PAYMENT_SIGNATURE_HEADER)
        if payment_header is None:
            return httpx.Response(
                402,
                headers={
                    "PAYMENT-REQUIRED": requirement.to_payment_required_header(),
                },
                json={"error": "payment required"},
                request=request,
            )

        payload = XianX402PaymentPayload.from_header(payment_header)
        verification = verify_xian_x402_payment(payload, requirement)
        assert verification.valid, verification.error
        captured_payloads.append(payload)
        return httpx.Response(
            200,
            headers={
                PAYMENT_RESPONSE_HEADER: encode_json_header(
                    {
                        "success": True,
                        "network": payload.network,
                        "asset": payload.asset,
                        "amount": payload.amount,
                        "paymentId": payload.payment_id,
                        "payer": payload.payer,
                        "payTo": payload.pay_to,
                        "transaction": "ABC123",
                    }
                )
            },
            text="paid content",
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with X402HttpxCompatClient(
        account=wallet,
        max_value=1,
        transport=transport,
    ) as client:
        response = await client.get("https://seller.test/data")

    assert response.status_code == 200
    assert response.text == "paid content"
    assert len(captured_payloads) == 1
    assert client.payment_hooks.last_paid_to == requirement.pay_to
    assert client.payment_hooks.last_payment_id == captured_payloads[0].payment_id
    assert client.payment_hooks.last_payment_payload == captured_payloads[0]


@pytest.mark.asyncio
async def test_x402_client_rejects_xian_payment_over_max_value() -> None:
    wallet = Wallet()
    requirement = XianX402PaymentRequirement(
        network="xian:xian-localnet-1",
        asset="currency",
        amount="2",
        pay_to="seller-public-key",
        resource="https://seller.test/data",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            headers={"PAYMENT-REQUIRED": requirement.to_payment_required_header()},
            json={"error": "payment required"},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with X402HttpxCompatClient(
        account=wallet,
        max_value=1,
        transport=transport,
    ) as client:
        with pytest.raises(PaymentError, match="exceeds max_value"):
            await client.get("https://seller.test/data")


def test_x402_check_price_formats_xian_profile_without_evm_schema_fields() -> None:
    result = _format_raw_payment_requirements(_requirement().to_payment_required())

    assert result is not None
    assert "Amount: 0.001" in result
    assert "Asset: currency" in result
    assert "Network: xian:xian-localnet-1" in result


@pytest.mark.asyncio
async def test_record_order_extracts_xian_payment_payload() -> None:
    wallet = Wallet()
    requirement = _requirement()
    payload = sign_xian_x402_payment(
        requirement,
        wallet,
        payment_id="pay_1234567890abcdef",
        deadline="2099-01-01 00:00:00",
    )
    request = httpx.Request(
        "GET",
        "https://seller.test/data",
        headers={PAYMENT_SIGNATURE_HEADER: payload.to_header()},
    )
    response = httpx.Response(
        200,
        headers={
            PAYMENT_RESPONSE_HEADER: encode_json_header(
                {
                    "success": True,
                    "network": requirement.network,
                    "asset": requirement.asset,
                    "amount": requirement.amount,
                    "paymentId": payload.payment_id,
                    "transaction": "ABC123",
                }
            )
        },
        text="paid content",
        request=request,
    )
    context = SimpleNamespace(
        agent_id="agent-xian",
        chat_id="chat-xian",
        user_id="user-xian",
    )
    skill = X402Pay()

    async def fake_get_signer(_: X402Pay) -> Wallet:
        return wallet

    with (
        patch(
            "intentkit.skills.base.IntentKitSkill.get_context",
            return_value=context,
        ),
        patch.object(X402Pay, "get_signer", new=fake_get_signer),
        patch(
            "intentkit.skills.x402.base.X402Order.create",
            new=AsyncMock(),
        ) as create_order,
    ):
        await skill.record_order(
            response=response,
            skill_name="x402_pay",
            method="GET",
            url="https://seller.test/data",
            max_value=1,
            pay_to_fallback=requirement.pay_to,
        )

    create_order.assert_awaited_once()
    order = create_order.call_args.args[0]
    assert order.agent_id == "agent-xian"
    assert order.amount == 0
    assert order.amount_text == "0.001"
    assert order.asset == "currency"
    assert order.network == "xian:xian-localnet-1"
    assert order.pay_to == requirement.pay_to
    assert order.payer == wallet.public_key
    assert order.payment_id == payload.payment_id
    assert order.tx_hash == "ABC123"
