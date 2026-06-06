import pytest

from intentkit.testing.xian_trade_social_workflow import run_trade_social_workflow_test


@pytest.mark.asyncio
async def test_xian_trade_social_workflow_runs_once_for_threshold_cross():
    summary = await run_trade_social_workflow_test(threshold_pct=3.0)

    assert summary["acted_on_event_ids"] == [2]
    assert len(summary["trade_calls"]) == 1
    assert summary["trade_calls"][0]["contract"] == "con_dex"
    assert summary["trade_calls"][0]["function"] == "swapExactTokenForToken"
    assert len(summary["telegram_payloads"]) == 1
    assert "auto-sell executed on Xian" in summary["telegram_payloads"][0]["text"]
    assert len(summary["twitter_payloads"]) == 1
    assert "auto-sell executed on Xian" in summary["twitter_payloads"][0]["text"]
    assert summary["final_cursor"] == "2"
