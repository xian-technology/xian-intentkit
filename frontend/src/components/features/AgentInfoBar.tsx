"use client";

import { useState } from "react";
import { Check, Copy, Info, Wallet } from "lucide-react";
import type { Agent } from "@/types/agent";
import { Button } from "@/components/ui/button";
import { getAgentFundingWallet } from "@/components/features/agentWallet";

interface AgentInfoBarProps {
  agent: Agent;
}

export function AgentInfoBar({ agent }: AgentInfoBarProps) {
  const [copiedAddress, setCopiedAddress] = useState(false);
  const fundingWallet = getAgentFundingWallet(agent);

  const handleCopyAddress = async () => {
    if (!fundingWallet) return;

    await navigator.clipboard.writeText(fundingWallet.address);
    setCopiedAddress(true);
    window.setTimeout(() => setCopiedAddress(false), 1500);
  };

  return (
    <div className="mb-4 rounded-lg border bg-muted/50 p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="inline-flex items-center gap-1 rounded-md bg-background px-2 py-0.5 text-xs font-medium ring-1 ring-inset ring-gray-500/10">
          <Info className="h-3 w-3 text-muted-foreground" />
          {agent.model}
        </span>
        {agent.skills &&
          Object.entries(agent.skills)
            .filter(([, config]) => (config as { enabled: boolean }).enabled)
            .map(([category]) => (
              <span
                key={category}
                className="inline-flex items-center rounded-md bg-primary/10 text-primary px-2 py-0.5 text-xs font-medium ring-1 ring-inset ring-primary/20"
              >
                {category}
              </span>
            ))}
        {agent.search_internet && (
          <span className="inline-flex items-center rounded-md bg-blue-500/10 text-blue-700 dark:text-blue-400 px-2 py-0.5 text-xs font-medium ring-1 ring-inset ring-blue-500/20">
            search
          </span>
        )}
        {agent.super_mode && (
          <span className="inline-flex items-center rounded-md bg-purple-500/10 text-purple-700 dark:text-purple-400 px-2 py-0.5 text-xs font-medium ring-1 ring-inset ring-purple-500/20">
            super
          </span>
        )}
        {agent.enable_todo && (
          <span className="inline-flex items-center rounded-md bg-green-500/10 text-green-700 dark:text-green-400 px-2 py-0.5 text-xs font-medium ring-1 ring-inset ring-green-500/20">
            todo
          </span>
        )}
        {agent.enable_long_term_memory && (
          <span className="inline-flex items-center rounded-md bg-amber-500/10 text-amber-700 dark:text-amber-400 px-2 py-0.5 text-xs font-medium ring-1 ring-inset ring-amber-500/20">
            memory
          </span>
        )}
      </div>
      {fundingWallet && (
        <div className="mt-3 flex flex-col gap-2 rounded-md border bg-background p-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
              <Wallet className="h-3 w-3" />
              {fundingWallet.label}
            </div>
            <div className="mt-1 break-all font-mono text-xs text-foreground">
              {fundingWallet.address}
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="shrink-0 self-start sm:self-center"
            onClick={handleCopyAddress}
          >
            {copiedAddress ? (
              <Check className="mr-2 h-4 w-4" />
            ) : (
              <Copy className="mr-2 h-4 w-4" />
            )}
            {copiedAddress ? "Copied" : "Copy"}
          </Button>
        </div>
      )}
    </div>
  );
}
