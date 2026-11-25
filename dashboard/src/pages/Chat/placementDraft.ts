import type { Placement } from "../../api/modules/botPlacement";

// Only the composer currently mounted in this tab may choose the next message's location.
type Choice = { bot: string; value: Placement };
let selected: Choice | null = null;
const listeners = new Set<() => void>();

export function subscribePlacement(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function readPlacement(bot: string): Choice | null {
  return selected?.bot === bot ? selected : null;
}

export function choosePlacement(bot: string, value: Placement) {
  selected = { bot, value };
  for (const notify of listeners) notify();
}

export function clearPlacement(choice: Choice | null) {
  if (selected === null || selected !== choice) return;
  selected = null;
  for (const notify of listeners) notify();
}
