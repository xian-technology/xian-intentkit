import { describe, expect, it } from "vitest";
import type { Agent } from "@/types/agent";
import { getAgentFundingWallet } from "./agentWallet";

function agent(overrides: Partial<Agent>): Agent {
  return {
    id: "agent-1",
    name: null,
    slug: null,
    picture: null,
    purpose: null,
    description: null,
    personality: null,
    principles: null,
    model: "openai/gpt-4o-mini",
    prompt: null,
    prompt_append: null,
    temperature: null,
    frequency_penalty: null,
    presence_penalty: null,
    wallet_provider: "none",
    readonly_wallet_address: null,
    network_id: null,
    skills: null,
    version: null,
    statistics: null,
    assets: null,
    account_snapshot: null,
    extra: null,
    search_internet: null,
    super_mode: null,
    enable_todo: null,
    enable_long_term_memory: null,
    enable_activity: null,
    enable_post: null,
    deployed_at: null,
    public_info_updated_at: null,
    created_at: "2026-04-26T00:00:00Z",
    updated_at: "2026-04-26T00:00:00Z",
    owner: null,
    team_id: null,
    visibility: null,
    linked_twitter_username: null,
    linked_telegram_username: null,
    linked_twitter_name: null,
    linked_telegram_name: null,
    ...overrides,
  };
}

describe("getAgentFundingWallet", () => {
  it("returns the Xian funding address for Xian agents", () => {
    expect(
      getAgentFundingWallet(
        agent({
          wallet_provider: "xian",
          xian_wallet_address: "xian-address",
        }),
      ),
    ).toEqual({
      label: "Xian funding address",
      address: "xian-address",
    });
  });

  it("returns the active EVM wallet address for EVM-backed providers", () => {
    expect(
      getAgentFundingWallet(
        agent({
          wallet_provider: "safe",
          evm_wallet_address: "0xabc",
        }),
      ),
    ).toEqual({
      label: "EVM funding address",
      address: "0xabc",
    });
  });

  it("does not expose a funding address when the active wallet has none", () => {
    expect(
      getAgentFundingWallet(
        agent({
          wallet_provider: "xian",
          xian_wallet_address: null,
        }),
      ),
    ).toBeNull();
  });
});
