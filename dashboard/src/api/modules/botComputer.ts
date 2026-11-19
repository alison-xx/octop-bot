import { request } from "../request";

export type ComputerLevel = "off" | "view" | "background" | "foreground";
export interface ComputerApp {
  id: string;
  name: string;
}
export interface ComputerState {
  available: boolean;
  level: ComputerLevel;
  apps: ComputerApp[];
  paused: boolean;
  active_app: string | null;
}
const endpoint = (id: string) =>
  `/octop-bot/bots/${encodeURIComponent(id)}/computer`;
export const botComputerApi = {
  state: (id: string) => request<ComputerState>(endpoint(id)),
  apps: (id: string) => request<ComputerApp[]>(endpoint(id) + "/apps"),
  save: (id: string, level: ComputerLevel, app_ids: string[]) =>
    request<ComputerState>(endpoint(id), {
      method: "PUT",
      body: JSON.stringify({ level, app_ids }),
    }),
  pause: (id: string, paused: boolean) =>
    request<ComputerState>(endpoint(id) + "/handoff", {
      method: "PUT",
      body: JSON.stringify({ paused }),
    }),
};
