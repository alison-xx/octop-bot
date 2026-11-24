import { getApiUrl } from "../config";
import { request } from "../request";
import type { BotAppearance } from "./octopBot";

export type MarketLook = Pick<BotAppearance, "shape" | "color">;

export interface MarketCategory {
  id: string;
  name: string;
  blurb: string;
  count: number;
}

export interface MarketRole {
  id: string;
  name: string;
  blurb: string;
  count: number;
  /** Position in the new-user role picker; null shows it only in the market. */
  onboarding: number | null;
}

export interface MarketCard {
  slug: string;
  category: string;
  /** Job role ids, see MarketRole. */
  roles: string[];
  featured: boolean;
  name: string;
  tagline: string;
  look: MarketLook;
  /** Server path of the portrait, or null to draw the SVG character. */
  avatar: string | null;
}

export interface MarketDetail extends MarketCard {
  version: number;
  description: string;
  role: string;
  instructions: string[];
  memories: string[];
  skills: { id: string; name: string; summary: string }[];
  routines: {
    id: string;
    name: string;
    when: string;
    prompt: string;
    suggested: boolean;
  }[];
  integrations: { kind: string; name: string; color: string | null }[];
  starters: string[];
}

export interface MarketImport {
  agent_id: string;
  state: string;
  preparing: boolean;
  last_error: string | null;
  name: string;
  routines: string[];
  integrations: string[];
}

export function marketAvatarUrl(path: string): string {
  return getApiUrl(path.replace(/^\/api(?=\/)/, ""));
}

export const botMarketApi = {
  list: () =>
    request<{
      categories: MarketCategory[];
      roles: MarketRole[];
      templates: MarketCard[];
    }>("/octop-bot/market"),
  get: (slug: string) =>
    request<MarketDetail>("/octop-bot/market/" + encodeURIComponent(slug)),
  mine: () =>
    request<{ imports: Record<string, string[]> }>("/octop-bot/market-imports"),
  install: (slug: string, name: string, routines: string[]) =>
    request<MarketImport>("/octop-bot/market-imports", {
      method: "POST",
      body: JSON.stringify({ slug, name, routines }),
    }),
};
