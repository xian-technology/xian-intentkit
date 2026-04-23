from unittest.mock import MagicMock

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from intentkit.utils.error import IntentKitAPIError

from app.team import auth


def _credentials(token: str = "token") -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.mark.asyncio
async def test_optional_auth_downgrades_invalid_tokens(monkeypatch):
    async def fake_get_current_user(*_args, **_kwargs):
        raise IntentKitAPIError(
            status_code=401,
            key="InvalidToken",
            message="Invalid token",
        )

    monkeypatch.setattr(auth, "get_current_user", fake_get_current_user)

    assert await auth.get_current_user_optional(_credentials()) is None


@pytest.mark.asyncio
async def test_optional_auth_surfaces_provider_failures(monkeypatch):
    async def fake_get_current_user(*_args, **_kwargs):
        raise IntentKitAPIError(
            status_code=503,
            key="AuthProviderUnavailable",
            message="Unable to verify token because the auth provider is unavailable",
        )

    monkeypatch.setattr(auth, "get_current_user", fake_get_current_user)

    with pytest.raises(IntentKitAPIError) as exc_info:
        await auth.get_current_user_optional(_credentials())

    assert exc_info.value.status_code == 503
    assert exc_info.value.key == "AuthProviderUnavailable"


def test_jwks_unexpected_verification_errors_are_provider_failures(monkeypatch):
    broken_client = MagicMock()
    broken_client.get_signing_key_from_jwt.side_effect = RuntimeError("jwks down")
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: broken_client)

    with pytest.raises(IntentKitAPIError) as exc_info:
        auth._verify_jwks("token")

    assert exc_info.value.status_code == 503
    assert exc_info.value.key == "AuthProviderUnavailable"
