import { modelDisplayName, modelVendor } from "./ModelName";
import type { ModelItem } from "./ModelSelect";

/** One model as the picker lists it; `routes` are the channels that serve it (线路 1/2/3). */
export type ModelChoice = {
  key: string;
  vendor: string;
  name: string;
  routes: ModelItem[];
};

/** Case, spaces, hyphens and underscores do not matter: "GLM-5.1" and "glm 5.1" are one model. */
function nameKey(name: string): string {
  return name
    .toLowerCase()
    .replace(/[\s\-_]+/g, " ")
    .trim();
}

/**
 * Lynxce lists a model once per route (supplier or compatible entry), so the
 * same name came up several times. As in Lynxce's own picker, items with the
 * same maker and name (and the same `group`, e.g. provider) become one choice
 * whose routes keep the given order. Only the display merges: every route
 * keeps its own value.
 */
export function groupModelItems(items: ModelItem[]): ModelChoice[] {
  const choices = new Map<string, ModelChoice>();
  for (const item of items) {
    const vendor = modelVendor(`${item.id} ${item.name ?? ""}`)?.key ?? "other";
    const name = modelDisplayName(item.id, item.name);
    const key = [item.group ?? "", vendor, nameKey(name)].join("\u0000");
    const choice = choices.get(key);
    if (choice) {
      if (!choice.routes.some((r) => r.value === item.value))
        choice.routes.push(item);
    } else {
      choices.set(key, { key, vendor, name, routes: [item] });
    }
  }
  return [...choices.values()];
}

/** The route a choice stands for in the list: the selected one if it is in there, else the first. */
export function choiceValue(choice: ModelChoice, value: string | undefined) {
  return (
    choice.routes.find((r) => r.value === value)?.value ??
    choice.routes[0].value
  );
}
