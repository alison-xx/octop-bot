import { request } from "../request";

export type Placement = "auto" | "local" | "cloud";
export interface ComputerLocations {
  default: Placement;
  devices: Record<string, string>;
}

const path = (bot: string) =>
  "/octop-bot/local-devices/placement/" + encodeURIComponent(bot);
export const botPlacement = {
  get: (bot: string) => request<ComputerLocations>(path(bot)),
  save: (bot: string, value: Placement) =>
    request<{ default: Placement }>(path(bot), {
      method: "PUT",
      body: JSON.stringify({ default: value }),
    }),
};
