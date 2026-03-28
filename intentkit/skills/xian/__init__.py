"""Xian blockchain skills powered by xian-py."""

from typing import TypedDict

from intentkit.skills.base import SkillConfig, SkillState
from intentkit.skills.xian.approve_tokens import XianApproveTokens
from intentkit.skills.xian.base import XianBaseTool
from intentkit.skills.xian.call_contract import XianCallContract
from intentkit.skills.xian.get_allowance import XianGetAllowance
from intentkit.skills.xian.get_chain_status import XianGetChainStatus
from intentkit.skills.xian.get_token_balance import XianGetTokenBalance
from intentkit.skills.xian.get_transaction import XianGetTransaction
from intentkit.skills.xian.get_wallet_details import XianGetWalletDetails
from intentkit.skills.xian.list_events import XianListEvents
from intentkit.skills.xian.read_contract_state import XianReadContractState
from intentkit.skills.xian.send_contract_transaction import (
    XianSendContractTransaction,
)
from intentkit.skills.xian.transfer_tokens import XianTransferTokens


class SkillStates(TypedDict):
    xian_get_wallet_details: SkillState
    xian_get_token_balance: SkillState
    xian_transfer_tokens: SkillState
    xian_approve_tokens: SkillState
    xian_get_allowance: SkillState
    xian_read_contract_state: SkillState
    xian_call_contract: SkillState
    xian_send_contract_transaction: SkillState
    xian_get_transaction: SkillState
    xian_list_events: SkillState
    xian_get_chain_status: SkillState


class Config(SkillConfig):
    """Configuration for Xian skills."""

    states: SkillStates


_cache: dict[str, XianBaseTool] = {
    "xian_get_wallet_details": XianGetWalletDetails(),
    "xian_get_token_balance": XianGetTokenBalance(),
    "xian_transfer_tokens": XianTransferTokens(),
    "xian_approve_tokens": XianApproveTokens(),
    "xian_get_allowance": XianGetAllowance(),
    "xian_read_contract_state": XianReadContractState(),
    "xian_call_contract": XianCallContract(),
    "xian_send_contract_transaction": XianSendContractTransaction(),
    "xian_get_transaction": XianGetTransaction(),
    "xian_list_events": XianListEvents(),
    "xian_get_chain_status": XianGetChainStatus(),
}


async def get_skills(
    config: Config,
    is_private: bool,
    **_,
) -> list[XianBaseTool]:
    tools: list[XianBaseTool] = []

    for skill_name, state in config["states"].items():
        if state == "disabled":
            continue
        if state == "public" or (state == "private" and is_private):
            tool = _cache.get(skill_name)
            if tool is not None:
                tools.append(tool)

    return tools


def available() -> bool:
    return True
