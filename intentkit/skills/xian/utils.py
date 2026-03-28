from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any


def format_xian_amount(value: Any) -> str:
    if value is None:
        return "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return format(normalized, "f").rstrip("0").rstrip(".") or "0"
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)
    normalized = decimal_value.normalize()
    return format(normalized, "f").rstrip("0").rstrip(".") or "0"


def format_structured(value: Any) -> str:
    try:
        return json.dumps(value, indent=2, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def render_submission(action: str, submission: Any) -> str:
    lines = [f"{action}"]
    tx_hash = getattr(submission, "tx_hash", None)
    if tx_hash:
        lines.append(f"Transaction hash: {tx_hash}")

    mode = getattr(submission, "mode", None)
    if mode:
        lines.append(f"Mode: {mode}")

    accepted = getattr(submission, "accepted", None)
    if accepted is not None:
        lines.append(f"Accepted: {accepted}")

    finalized = getattr(submission, "finalized", None)
    if finalized is not None:
        lines.append(f"Finalized: {finalized}")

    message = getattr(submission, "message", None)
    if message:
        lines.append(f"Message: {message}")

    receipt = getattr(submission, "receipt", None)
    if receipt is not None:
        lines.append(f"Receipt success: {getattr(receipt, 'success', None)}")
        receipt_message = getattr(receipt, "message", None)
        if receipt_message:
            lines.append(f"Receipt message: {receipt_message}")

    return "\n".join(lines)


def render_receipt(receipt: Any) -> str:
    lines = [
        f"Transaction hash: {getattr(receipt, 'tx_hash', None)}",
        f"Success: {getattr(receipt, 'success', None)}",
    ]
    message = getattr(receipt, "message", None)
    if message:
        lines.append(f"Message: {message}")
    execution = getattr(receipt, "execution", None)
    if execution:
        lines.append("Execution:")
        lines.append(format_structured(execution))
    return "\n".join(lines)
