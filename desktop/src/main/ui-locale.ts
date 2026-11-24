import { app } from "electron";

import { pickUiLocale } from "./ui-locale-pick";

export function uiLocale(): string {
  return pickUiLocale(app.getPreferredSystemLanguages(), app.getLocale());
}
