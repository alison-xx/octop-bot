import type { OctopCronRow } from "../../api/types";
import type { CloudRule } from "../../api/modules/botCloud";

export interface CloudScheduleDraft {
  name: string;
  instruction: string;
  frequency: CloudRule["frequency"];
  time: string;
  weekday: number;
  once: string;
}

export function cloudDraftFromTimer(
  job: OctopCronRow,
): CloudScheduleDraft | null {
  if (job.enabled || job.task_type !== "agent" || !job.prompt?.trim())
    return null;
  const draft = { name: job.name ?? "", instruction: job.prompt, weekday: 1 };
  const once = /^date:(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(?::00)?$/.exec(
    job.trigger,
  );
  if (once)
    return {
      ...draft,
      frequency: "once",
      time: once[1].slice(-5),
      once: once[1],
    };
  const cron =
    /^cron:(\d{1,2}) (\d{1,2}) \* \* (\*|mon-fri|mon|tue|wed|thu|fri|sat|sun)$/.exec(
      job.trigger,
    );
  if (!cron) return null;
  const day = cron[3];
  return {
    ...draft,
    frequency:
      day === "*" ? "daily" : day === "mon-fri" ? "weekdays" : "weekly",
    time: cron[2].padStart(2, "0") + ":" + cron[1].padStart(2, "0"),
    weekday: Math.max(
      1,
      ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].indexOf(day) + 1,
    ),
    once: "",
  };
}
