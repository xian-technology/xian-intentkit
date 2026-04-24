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

export function TaskTriggerDetails({ task }: { task: AutonomousTask }) {
  if (inferTriggerType(task) === "xian_event" && task.xian_event) {
    const event = task.xian_event;
    const filters = Object.entries(event.filters ?? {});
    const dexPriceChange = event.dex_price_change;

    return (
      <div className="grid grid-cols-1 gap-4 text-sm md:grid-cols-2">
        <div>
          <span className="font-semibold text-muted-foreground">
            Trigger:{" "}
          </span>
          <div className="flex flex-col">
            <span>Xian event</span>
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
        {filters.length > 0 && (
          <div>
            <span className="font-semibold text-muted-foreground">
              Filters:{" "}
            </span>
            <div className="mt-0.5 break-all font-mono text-xs text-muted-foreground">
              {filters.map(([key, value]) => `${key}=${value}`).join(", ")}
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
                {dexPriceChange.threshold_pct}% {dexPriceChange.direction ?? "either"}
              </span>
              <span className="mt-0.5 font-mono text-xs text-muted-foreground">
                {dexPriceChange.price_base ?? "token1_per_token0"}
              </span>
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
