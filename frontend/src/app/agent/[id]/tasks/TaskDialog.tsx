import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AutonomousTask, XianEventTrigger } from "@/lib/api";
import { cn } from "@/lib/utils";

type TriggerType = "schedule" | "xian_event";
type EventPreset = "dex_price_change" | "dex_swap" | "custom";

interface FilterRow {
  id: string;
  key: string;
  value: string;
}

interface TaskDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  task?: AutonomousTask | null;
  onSave: (task: Partial<AutonomousTask>) => Promise<void>;
}

const DEFAULT_CRON = "0 0 * * *";

const selectClassName =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";

function createFilterRow(key = "", value = ""): FilterRow {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    key,
    value,
  };
}

function filtersToRows(filters?: Record<string, string> | null): FilterRow[] {
  const entries = Object.entries(filters ?? {});
  if (entries.length === 0) {
    return [createFilterRow()];
  }
  return entries.map(([key, value]) => createFilterRow(key, value));
}

function rowsToFilters(rows: FilterRow[]): Record<string, string> | null {
  const filters = rows.reduce<Record<string, string>>((acc, row) => {
    const key = row.key.trim();
    const value = row.value.trim();
    if (key && value) {
      acc[key] = value;
    }
    return acc;
  }, {});
  return Object.keys(filters).length > 0 ? filters : null;
}

function inferTriggerType(task?: AutonomousTask | null): TriggerType {
  return task?.trigger_type ?? (task?.xian_event ? "xian_event" : "schedule");
}

function inferPreset(xianEvent?: XianEventTrigger | null): EventPreset {
  if (xianEvent?.dex_price_change) {
    return "dex_price_change";
  }
  if (xianEvent?.contract === "con_pairs" && xianEvent.event === "Swap") {
    return "dex_swap";
  }
  return "custom";
}

function getDefaultEvent(preset: EventPreset): XianEventTrigger {
  if (preset === "dex_swap") {
    return {
      contract: "con_pairs",
      event: "Swap",
      filters: { pair: "" },
      cooldown_seconds: 60,
      dex_price_change: null,
    };
  }

  if (preset === "custom") {
    return {
      contract: "",
      event: "",
      filters: null,
      cooldown_seconds: 0,
      dex_price_change: null,
    };
  }

  return {
    contract: "con_pairs",
    event: "Sync",
    filters: { pair: "" },
    cooldown_seconds: 60,
    dex_price_change: {
      threshold_pct: 3,
      direction: "either",
      pair_field: "pair",
      reserve0_field: "reserve0",
      reserve1_field: "reserve1",
      price_base: "token1_per_token0",
    },
  };
}

function normalizeXianEvent(
  xianEvent: XianEventTrigger | null | undefined,
  preset: EventPreset,
  filterRows: FilterRow[],
): XianEventTrigger {
  const fallback = getDefaultEvent(preset);
  const current = xianEvent ?? fallback;
  const cooldown = Number(current.cooldown_seconds ?? fallback.cooldown_seconds ?? 0);
  const normalized: XianEventTrigger = {
    contract: current.contract.trim(),
    event: current.event.trim(),
    filters: rowsToFilters(filterRows),
    cooldown_seconds:
      Number.isFinite(cooldown) && cooldown > 0 ? Math.floor(cooldown) : 0,
    dex_price_change: null,
  };

  if (preset === "dex_price_change") {
    const threshold = Number(current.dex_price_change?.threshold_pct ?? 3);
    normalized.dex_price_change = {
      threshold_pct: Number.isFinite(threshold) && threshold > 0 ? threshold : 3,
      direction: current.dex_price_change?.direction ?? "either",
      pair_field: current.dex_price_change?.pair_field?.trim() || "pair",
      reserve0_field:
        current.dex_price_change?.reserve0_field?.trim() || "reserve0",
      reserve1_field:
        current.dex_price_change?.reserve1_field?.trim() || "reserve1",
      price_base:
        current.dex_price_change?.price_base ?? "token1_per_token0",
    };
  }

  return normalized;
}

export function TaskDialog({
  open,
  onOpenChange,
  task,
  onSave,
}: TaskDialogProps) {
  const [loading, setLoading] = useState(false);
  const [eventPreset, setEventPreset] =
    useState<EventPreset>("dex_price_change");
  const [filterRows, setFilterRows] = useState<FilterRow[]>([
    createFilterRow("pair", ""),
  ]);
  const [formData, setFormData] = useState<Partial<AutonomousTask>>({
    name: "",
    description: "",
    cron: DEFAULT_CRON,
    trigger_type: "schedule",
    xian_event: null,
    prompt: "",
    enabled: true,
    has_memory: false,
  });

  useEffect(() => {
    const triggerType = inferTriggerType(task);
    const preset = task?.xian_event
      ? inferPreset(task.xian_event)
      : "dex_price_change";
    const xianEvent = task?.xian_event ?? getDefaultEvent(preset);

    setEventPreset(preset);
    setFilterRows(filtersToRows(xianEvent.filters));
    setFormData({
      name: task?.name || "",
      description: task?.description || "",
      cron: triggerType === "schedule" ? task?.cron || DEFAULT_CRON : null,
      trigger_type: triggerType,
      xian_event: triggerType === "xian_event" ? xianEvent : null,
      prompt: task?.prompt || "",
      enabled: task?.enabled ?? true,
      has_memory: task?.has_memory ?? false,
    });
  }, [task, open]);

  const triggerType = formData.trigger_type ?? "schedule";
  const xianEvent = formData.xian_event ?? getDefaultEvent(eventPreset);

  const updateXianEvent = (patch: Partial<XianEventTrigger>) => {
    setFormData((current) => ({
      ...current,
      xian_event: {
        ...(current.xian_event ?? getDefaultEvent(eventPreset)),
        ...patch,
      },
    }));
  };

  const updateDexPriceChange = (
    patch: Partial<NonNullable<XianEventTrigger["dex_price_change"]>>,
  ) => {
    setFormData((current) => {
      const currentEvent = current.xian_event ?? getDefaultEvent(eventPreset);
      const currentDex =
        currentEvent.dex_price_change ??
        getDefaultEvent("dex_price_change").dex_price_change!;

      return {
        ...current,
        xian_event: {
          ...currentEvent,
          dex_price_change: {
            ...currentDex,
            ...patch,
          },
        },
      };
    });
  };

  const handleTriggerTypeChange = (value: string) => {
    const nextTriggerType = value as TriggerType;
    if (nextTriggerType === "schedule") {
      setFormData((current) => ({
        ...current,
        trigger_type: "schedule",
        cron: current.cron || DEFAULT_CRON,
        xian_event: null,
      }));
      return;
    }

    const nextEvent = formData.xian_event ?? getDefaultEvent(eventPreset);
    setFilterRows(filtersToRows(nextEvent.filters));
    setFormData((current) => ({
      ...current,
      trigger_type: "xian_event",
      cron: null,
      xian_event: nextEvent,
    }));
  };

  const handlePresetChange = (value: string) => {
    const preset = value as EventPreset;
    const nextEvent = getDefaultEvent(preset);
    setEventPreset(preset);
    setFilterRows(filtersToRows(nextEvent.filters));
    setFormData((current) => ({
      ...current,
      xian_event: nextEvent,
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const prompt = formData.prompt?.trim() ?? "";
      const payload: Partial<AutonomousTask> = {
        name: formData.name?.trim() || null,
        description: formData.description?.trim() || null,
        prompt,
        enabled: formData.enabled ?? true,
        has_memory: formData.has_memory ?? false,
      };

      if (triggerType === "xian_event") {
        payload.trigger_type = "xian_event";
        payload.cron = null;
        payload.xian_event = normalizeXianEvent(
          formData.xian_event,
          eventPreset,
          filterRows,
        );
      } else {
        payload.trigger_type = "schedule";
        payload.cron = formData.cron?.trim() || DEFAULT_CRON;
        payload.xian_event = null;
      }

      await onSave(payload);
      onOpenChange(false);
    } catch (error) {
      console.error("Failed to save task:", error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="sm:max-w-[680px] max-h-[90vh] overflow-y-auto">
        <form onSubmit={handleSubmit}>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {task ? "Edit Autonomous Task" : "New Autonomous Task"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              Configure when this autonomous agent task runs and what it should do.
            </AlertDialogDescription>
          </AlertDialogHeader>

          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <label
                htmlFor="name"
                className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
              >
                Name
              </label>
              <Input
                id="name"
                value={formData.name || ""}
                onChange={(e) =>
                  setFormData({ ...formData, name: e.target.value })
                }
                placeholder="e.g. Watch DEX price moves"
              />
            </div>

            <div className="grid gap-2">
              <label
                htmlFor="description"
                className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
              >
                Description
              </label>
              <Input
                id="description"
                value={formData.description || ""}
                onChange={(e) =>
                  setFormData({ ...formData, description: e.target.value })
                }
                placeholder="Brief description of what this task does"
              />
            </div>

            <div className="grid gap-2">
              <label className="text-sm font-medium leading-none">
                Trigger
              </label>
              <Tabs value={triggerType} onValueChange={handleTriggerTypeChange}>
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="schedule">Schedule</TabsTrigger>
                  <TabsTrigger value="xian_event">Xian Event</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>

            {triggerType === "schedule" ? (
              <div className="grid gap-2">
                <label
                  htmlFor="cron"
                  className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                >
                  Cron Schedule <span className="text-destructive">*</span>
                </label>
                <Input
                  id="cron"
                  value={formData.cron || ""}
                  onChange={(e) =>
                    setFormData({ ...formData, cron: e.target.value })
                  }
                  required={triggerType === "schedule"}
                  placeholder="0 0 * * *"
                  className="font-mono"
                />
                <p className="text-[0.8rem] text-muted-foreground">
                  Minute Hour Day Month DayOfWeek
                </p>
              </div>
            ) : (
              <div className="grid gap-4 rounded-md border border-border p-4">
                <div className="grid gap-2">
                  <label
                    htmlFor="event_preset"
                    className="text-sm font-medium leading-none"
                  >
                    Event Type
                  </label>
                  <select
                    id="event_preset"
                    value={eventPreset}
                    onChange={(e) => handlePresetChange(e.target.value)}
                    className={selectClassName}
                  >
                    <option value="dex_price_change">DEX price move</option>
                    <option value="dex_swap">DEX swap</option>
                    <option value="custom">Custom event</option>
                  </select>
                </div>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div className="grid gap-2">
                    <label
                      htmlFor="contract"
                      className="text-sm font-medium leading-none"
                    >
                      Contract <span className="text-destructive">*</span>
                    </label>
                    <Input
                      id="contract"
                      value={xianEvent.contract}
                      onChange={(e) =>
                        updateXianEvent({ contract: e.target.value })
                      }
                      required={triggerType === "xian_event"}
                      className="font-mono"
                    />
                  </div>

                  <div className="grid gap-2">
                    <label
                      htmlFor="event"
                      className="text-sm font-medium leading-none"
                    >
                      Event <span className="text-destructive">*</span>
                    </label>
                    <Input
                      id="event"
                      value={xianEvent.event}
                      onChange={(e) =>
                        updateXianEvent({ event: e.target.value })
                      }
                      required={triggerType === "xian_event"}
                      className="font-mono"
                    />
                  </div>
                </div>

                <div className="grid gap-2">
                  <label
                    htmlFor="cooldown_seconds"
                    className="text-sm font-medium leading-none"
                  >
                    Cooldown Seconds
                  </label>
                  <Input
                    id="cooldown_seconds"
                    type="number"
                    min={0}
                    max={86400}
                    value={xianEvent.cooldown_seconds ?? 0}
                    onChange={(e) =>
                      updateXianEvent({
                        cooldown_seconds: Number(e.target.value),
                      })
                    }
                  />
                </div>

                {eventPreset === "dex_price_change" && (
                  <div className="grid gap-4 rounded-md bg-muted/40 p-3">
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                      <div className="grid gap-2">
                        <label
                          htmlFor="threshold_pct"
                          className="text-sm font-medium leading-none"
                        >
                          Threshold %
                        </label>
                        <Input
                          id="threshold_pct"
                          type="number"
                          min={0.0001}
                          step="0.1"
                          value={
                            xianEvent.dex_price_change?.threshold_pct ?? 3
                          }
                          onChange={(e) =>
                            updateDexPriceChange({
                              threshold_pct: Number(e.target.value),
                            })
                          }
                          required={eventPreset === "dex_price_change"}
                        />
                      </div>

                      <div className="grid gap-2">
                        <label
                          htmlFor="direction"
                          className="text-sm font-medium leading-none"
                        >
                          Direction
                        </label>
                        <select
                          id="direction"
                          value={xianEvent.dex_price_change?.direction ?? "either"}
                          onChange={(e) =>
                            updateDexPriceChange({
                              direction: e.target.value as
                                | "either"
                                | "up"
                                | "down",
                            })
                          }
                          className={selectClassName}
                        >
                          <option value="either">Either</option>
                          <option value="up">Up</option>
                          <option value="down">Down</option>
                        </select>
                      </div>

                      <div className="grid gap-2">
                        <label
                          htmlFor="price_base"
                          className="text-sm font-medium leading-none"
                        >
                          Price Base
                        </label>
                        <select
                          id="price_base"
                          value={
                            xianEvent.dex_price_change?.price_base ??
                            "token1_per_token0"
                          }
                          onChange={(e) =>
                            updateDexPriceChange({
                              price_base: e.target.value as
                                | "token1_per_token0"
                                | "token0_per_token1",
                            })
                          }
                          className={selectClassName}
                        >
                          <option value="token1_per_token0">
                            Token1 per Token0
                          </option>
                          <option value="token0_per_token1">
                            Token0 per Token1
                          </option>
                        </select>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                      <div className="grid gap-2">
                        <label
                          htmlFor="pair_field"
                          className="text-sm font-medium leading-none"
                        >
                          Pair Field
                        </label>
                        <Input
                          id="pair_field"
                          value={xianEvent.dex_price_change?.pair_field ?? "pair"}
                          onChange={(e) =>
                            updateDexPriceChange({
                              pair_field: e.target.value,
                            })
                          }
                          className="font-mono"
                        />
                      </div>

                      <div className="grid gap-2">
                        <label
                          htmlFor="reserve0_field"
                          className="text-sm font-medium leading-none"
                        >
                          Reserve0 Field
                        </label>
                        <Input
                          id="reserve0_field"
                          value={
                            xianEvent.dex_price_change?.reserve0_field ??
                            "reserve0"
                          }
                          onChange={(e) =>
                            updateDexPriceChange({
                              reserve0_field: e.target.value,
                            })
                          }
                          className="font-mono"
                        />
                      </div>

                      <div className="grid gap-2">
                        <label
                          htmlFor="reserve1_field"
                          className="text-sm font-medium leading-none"
                        >
                          Reserve1 Field
                        </label>
                        <Input
                          id="reserve1_field"
                          value={
                            xianEvent.dex_price_change?.reserve1_field ??
                            "reserve1"
                          }
                          onChange={(e) =>
                            updateDexPriceChange({
                              reserve1_field: e.target.value,
                            })
                          }
                          className="font-mono"
                        />
                      </div>
                    </div>
                  </div>
                )}

                <div className="grid gap-2">
                  <div className="flex items-center justify-between gap-2">
                    <label className="text-sm font-medium leading-none">
                      Filters
                    </label>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        setFilterRows((rows) => [...rows, createFilterRow()])
                      }
                    >
                      <Plus className="mr-2 h-4 w-4" />
                      Add
                    </Button>
                  </div>
                  <div className="grid gap-2">
                    {filterRows.map((row, index) => (
                      <div
                        key={row.id}
                        className="grid grid-cols-[1fr_1fr_auto] gap-2"
                      >
                        <Input
                          value={row.key}
                          onChange={(e) =>
                            setFilterRows((rows) =>
                              rows.map((item) =>
                                item.id === row.id
                                  ? { ...item, key: e.target.value }
                                  : item,
                              ),
                            )
                          }
                          placeholder="key"
                          className="font-mono"
                        />
                        <Input
                          value={row.value}
                          onChange={(e) =>
                            setFilterRows((rows) =>
                              rows.map((item) =>
                                item.id === row.id
                                  ? { ...item, value: e.target.value }
                                  : item,
                              ),
                            )
                          }
                          placeholder="value"
                          className="font-mono"
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-10 w-10"
                          onClick={() =>
                            setFilterRows((rows) =>
                              rows.length > 1
                                ? rows.filter((item) => item.id !== row.id)
                                : [createFilterRow()],
                            )
                          }
                          disabled={filterRows.length === 1 && index === 0}
                        >
                          <Trash2 className="h-4 w-4" />
                          <span className="sr-only">Remove filter</span>
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            <div className="grid gap-2">
              <label
                htmlFor="prompt"
                className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
              >
                Trigger Prompt <span className="text-destructive">*</span>
              </label>
              <textarea
                id="prompt"
                value={formData.prompt || ""}
                onChange={(e) =>
                  setFormData({ ...formData, prompt: e.target.value })
                }
                required
                className={cn(
                  "flex min-h-[120px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
                )}
                placeholder="Instructions for the agent to execute..."
              />
            </div>

            <div className="flex items-center gap-4">
              <div className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  id="enabled"
                  checked={formData.enabled}
                  onChange={(e) =>
                    setFormData({ ...formData, enabled: e.target.checked })
                  }
                  className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                />
                <label
                  htmlFor="enabled"
                  className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                >
                  Enabled
                </label>
              </div>

              <div className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  id="has_memory"
                  checked={formData.has_memory}
                  onChange={(e) =>
                    setFormData({ ...formData, has_memory: e.target.checked })
                  }
                  className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                />
                <label
                  htmlFor="has_memory"
                  className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                >
                  Enable Memory
                </label>
              </div>
            </div>
          </div>

          <AlertDialogFooter>
            <AlertDialogCancel type="button" disabled={loading}>
              Cancel
            </AlertDialogCancel>
            <Button type="submit" disabled={loading}>
              {loading ? "Saving..." : "Save"}
            </Button>
          </AlertDialogFooter>
        </form>
      </AlertDialogContent>
    </AlertDialog>
  );
}
