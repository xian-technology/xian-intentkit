import type { Agent } from "@/types/agent";

export interface AgentFundingWallet {
  label: string;
  address: string;
}

export function getAgentFundingWallet(agent: Agent): AgentFundingWallet | null {
  if (agent.wallet_provider === "xian" && agent.xian_wallet_address) {
    return {
      label: "Xian funding address",
      address: agent.xian_wallet_address,
    };
  }

  if (
    ["cdp", "native", "safe", "privy"].includes(agent.wallet_provider ?? "") &&
    agent.evm_wallet_address
  ) {
    return {
      label: "EVM funding address",
      address: agent.evm_wallet_address,
    };
  }

  return null;
}
