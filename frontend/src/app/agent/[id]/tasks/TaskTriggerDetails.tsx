import cronstrue from "cronstrue";
import { AutonomousTask } from "@/lib/api";

function inferTriggerType(task: AutonomousTask): "schedule" | "xian_event" {
  return task.trigger_type ?? (task.xian_event ? "xian_event" : "schedule");
}

function formatCooldown(seconds?: number): string {
  if (!seconds) {
    return "None";
  }
  if (seconds < 60) {
    return `${seconds}s`;
  }
  if (seconds % 60 === 0) {
    return `${seconds / 60}m`;
  }
  return `${seconds}s`;
}

function formatSchedule(task: AutonomousTask): string {
  if (task.cron) {
    try {
      return cronstrue.toString(task.cron);
    } catch {
      return task.cron;
    }
  }
  if (task.minutes) {
    return `Every ${task.minutes} minutes`;
  }
  return "Not scheduled";
}

function formatDirection(direction?: "either" | "up" | "down"): string {
  if (direction === "up") {
    return "price increases";
  }
  if (direction === "down") {
    return "price decreases";
  }
  return "either direction";
}

function formatPriceBase(priceBase?: "token1_per_token0" | "token0_per_token1") {
  return priceBase === "token0_per_token1"
    ? "Inverse pool quote"
    : "Pool quote";
}

export function TaskTriggerDetails({ task }: { task: AutonomousTask }) {
  if (inferTriggerType(task) === "xian_event" && task.xian_event) {
    const event = task.xian_event;
    const filters = Object.entries(event.filters ?? {});
    const pairFilter = event.filters?.pair;
    const dexPriceChange = event.dex_price_change;
    const isDexPriceMove =
      event.contract === "con_pairs" && event.event === "Sync" && dexPriceChange;
    const isDexSwap = event.contract === "con_pairs" && event.event === "Swap";
    const triggerLabel = isDexPriceMove
      ? "DEX price move"
      : isDexSwap
        ? "DEX swap"
        : "Xian event";
    const nonPairFilters = filters.filter(([key]) => key !== "pair");

    return (
      <div className="grid grid-cols-1 gap-4 text-sm md:grid-cols-2">
        <div>
          <span className="font-semibold text-muted-foreground">
            Trigger:{" "}
          </span>
          <div className="flex flex-col">
            <span>{triggerLabel}</span>
            <span className="mt-0.5 break-all font-mono text-xs text-muted-foreground">
              {event.contract}.{event.event}
            </span>
          </div>
        </div>
        <div>
          <span className="font-semibold text-muted-foreground">
            Cooldown:{" "}
          </span>
          {formatCooldown(event.cooldown_seconds)}
        </div>
        {(isDexPriceMove || isDexSwap) && (
          <div>
            <span className="font-semibold text-muted-foreground">
              Pair:{" "}
            </span>
            {pairFilter || "All pairs"}
          </div>
        )}
        {nonPairFilters.length > 0 && (
          <div>
            <span className="font-semibold text-muted-foreground">
              Filters:{" "}
            </span>
            <div className="mt-0.5 break-all font-mono text-xs text-muted-foreground">
              {nonPairFilters.map(([key, value]) => `${key}=${value}`).join(", ")}
            </div>
          </div>
        )}
        {dexPriceChange && (
          <div>
            <span className="font-semibold text-muted-foreground">
              Price Move:{" "}
            </span>
            <div className="flex flex-col">
              <span>
                {dexPriceChange.threshold_pct}%{" "}
                {formatDirection(dexPriceChange.direction)}
              </span>
              {dexPriceChange.direction && dexPriceChange.direction !== "either" && (
                <span className="mt-0.5 text-xs text-muted-foreground">
                  {formatPriceBase(dexPriceChange.price_base)}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 text-sm md:grid-cols-2">
      <div>
        <span className="font-semibold text-muted-foreground">
          Schedule:{" "}
        </span>
        <div className="flex flex-col">
          <span>{formatSchedule(task)}</span>
          {task.cron && (
            <span className="mt-0.5 font-mono text-xs text-muted-foreground">
              {task.cron}
            </span>
          )}
        </div>
      </div>
      <div>
        <span className="font-semibold text-muted-foreground">
          Next Run:{" "}
        </span>
        {task.next_run_time
          ? new Date(task.next_run_time).toLocaleString()
          : "Not scheduled"}
      </div>
    </div>
  );
}
