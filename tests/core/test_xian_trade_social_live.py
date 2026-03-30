from intentkit.testing.xian_trade_social_live import (
    DexContracts,
    SocialConfig,
    _extract_trade_hash_from_text,
    build_agent_payload,
    load_social_config,
)


def test_load_social_config_defaults_to_linked_account(monkeypatch):
    monkeypatch.setenv("INTENTKIT_E2E_TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("INTENTKIT_E2E_TELEGRAM_CHAT_ID", "chat-id")
    monkeypatch.delenv("INTENTKIT_E2E_TWITTER_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("INTENTKIT_E2E_TWITTER_CONSUMER_SECRET", raising=False)
    monkeypatch.delenv("INTENTKIT_E2E_TWITTER_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("INTENTKIT_E2E_TWITTER_ACCESS_TOKEN_SECRET", raising=False)

    social = load_social_config(twitter_auth_mode="auto")

    assert social.twitter_auth_mode == "linked_account"
    assert social.twitter_access_token is None


def test_build_agent_payload_uses_linked_account_mode():
    dex = DexContracts(
        token_contract="con_token",
        pairs_contract="con_pairs_test",
        dex_contract="con_dex_test",
        helper_contract="con_dex_helper_test",
        pair_id=7,
    )
    social = SocialConfig(
        telegram_bot_token="bot-token",
        telegram_chat_id="chat-id",
        twitter_auth_mode="linked_account",
    )

    payload = build_agent_payload(
        suffix="abc123",
        model="gpt-4o-mini",
        dex=dex,
        social=social,
    )

    twitter_skill = payload["skills"]["twitter"]
    assert twitter_skill["auth_mode"] == "linked_account"
    assert "consumer_key" not in twitter_skill
    assert "access_token" not in twitter_skill


def test_build_agent_payload_uses_self_key_mode():
    dex = DexContracts(
        token_contract="con_token",
        pairs_contract="con_pairs_test",
        dex_contract="con_dex_test",
        helper_contract="con_dex_helper_test",
        pair_id=7,
    )
    social = SocialConfig(
        telegram_bot_token="bot-token",
        telegram_chat_id="chat-id",
        twitter_auth_mode="self_key",
        twitter_consumer_key="consumer-key",
        twitter_consumer_secret="consumer-secret",
        twitter_access_token="access-token",
        twitter_access_token_secret="access-token-secret",
    )

    payload = build_agent_payload(
        suffix="abc123",
        model="gpt-4o-mini",
        dex=dex,
        social=social,
    )

    twitter_skill = payload["skills"]["twitter"]
    assert twitter_skill["auth_mode"] == "self_key"
    assert twitter_skill["consumer_key"] == "consumer-key"
    assert twitter_skill["access_token_secret"] == "access-token-secret"


def test_extract_trade_hash_uses_last_transaction_hash():
    text = """
Quoted Xian DEX trade.

Submitted Xian DEX helper approval for con_dex_helper on currency.
Transaction hash: 18D72EC4D61D3A61F2A2D49DF3D46A54A5A82E56E48DE8CF085D2D9B0D63B8C1

Submitted Xian DEX sell trade on con_dex_helper for pair 1.
Transaction hash: D12B9D56C329391567B75635E1F1C16DE93F31CC832CBE33A40034BF515922AB
"""

    assert _extract_trade_hash_from_text(text) == (
        "D12B9D56C329391567B75635E1F1C16DE93F31CC832CBE33A40034BF515922AB"
    )
