import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

/**
 * Which Octop server the Bot app talks to: its own local service (the default)
 * or a self-hosted one the user typed in. Kept by the main process only; the
 * Dashboard can ask to open the picker but never writes an address itself.
 */

export interface ServerChoice {
  /** Origin of the self-hosted server, or null for this computer's own service. */
  current: string | null;
  /** Recently used origins, newest first. */
  recent: string[];
}

export type AddressCheck = { ok: true; origin: string } | { ok: false; reason: "empty" | "invalid" | "insecure" };

const MAX_RECENT = 5;

/** Octop Bot cloud, run by Lynxce: sign in with a Lynxce account, nothing to install. */
export const LYNXCE_CLOUD_ORIGIN = "https://bot.lynxce.cn";

/** Private, loopback and mDNS hosts may use plain HTTP; anything public needs HTTPS. */
export function isLocalNetworkHost(hostname: string): boolean {
  const host = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (host === "localhost" || host.endsWith(".local") || host === "::1") return true;
  const parts = host.split(".").map(Number);
  if (parts.length !== 4 || parts.some((n) => !Number.isInteger(n) || n < 0 || n > 255)) return false;
  const [a = -1, b = -1] = parts;
  return a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
}

/** "octop.example.com" → "https://octop.example.com". Paths and queries are dropped. */
export function normalizeServerAddress(input: string): AddressCheck {
  const text = input.trim();
  if (!text) return { ok: false, reason: "empty" };
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : `https://${text}`;
  let url: URL;
  try {
    url = new URL(withScheme);
  } catch {
    return { ok: false, reason: "invalid" };
  }
  if ((url.protocol !== "https:" && url.protocol !== "http:") || !url.hostname || url.username || url.password) {
    return { ok: false, reason: "invalid" };
  }
  if (url.protocol === "http:" && !isLocalNetworkHost(url.hostname)) return { ok: false, reason: "insecure" };
  return { ok: true, origin: url.origin };
}

export class ServerChoiceStore {
  private readonly filePath: string;

  constructor(filePath: string) {
    this.filePath = filePath;
  }

  load(): ServerChoice {
    if (!existsSync(this.filePath)) return { current: null, recent: [] };
    try {
      const raw = JSON.parse(readFileSync(this.filePath, "utf8")) as Partial<ServerChoice>;
      const valid = (value: unknown): string | null => {
        if (typeof value !== "string") return null;
        const checked = normalizeServerAddress(value);
        return checked.ok && checked.origin === value ? value : null;
      };
      const recent = Array.isArray(raw.recent) ? raw.recent.map(valid).filter((v): v is string => v !== null) : [];
      return { current: valid(raw.current), recent: [...new Set(recent)].slice(0, MAX_RECENT) };
    } catch {
      return { current: null, recent: [] };
    }
  }

  /** Use this origin (null = the local service) and remember it. */
  select(origin: string | null): ServerChoice {
    const previous = this.load();
    const recent = origin ? [origin, ...previous.recent.filter((o) => o !== origin)].slice(0, MAX_RECENT) : previous.recent;
    const next: ServerChoice = { current: origin, recent };
    mkdirSync(dirname(this.filePath), { recursive: true });
    writeFileSync(this.filePath, JSON.stringify(next, null, 2), "utf8");
    return next;
  }

  forget(origin: string): ServerChoice {
    const previous = this.load();
    const next: ServerChoice = {
      current: previous.current === origin ? null : previous.current,
      recent: previous.recent.filter((o) => o !== origin),
    };
    mkdirSync(dirname(this.filePath), { recursive: true });
    writeFileSync(this.filePath, JSON.stringify(next, null, 2), "utf8");
    return next;
  }
}

export function defaultServerChoicePath(userDataDir: string): string {
  return join(userDataDir, "server.json");
}

export type ProbeResult = { ok: true } | { ok: false; reason: "unreachable" | "not-octop" };

type Fetch = (url: string, init?: { signal?: AbortSignal; redirect?: "error" }) => Promise<{
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}>;

/**
 * Is there an Octop server at this origin? Newer servers describe themselves at
 * /api/octop-bot/server-info; older ones still answer /api/setup/status.
 */
export async function probeServer(origin: string, fetchImpl: Fetch, timeoutMs = 8000): Promise<ProbeResult> {
  const attempt = async (path: string, accept: (body: unknown) => boolean): Promise<boolean | null> => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetchImpl(origin + path, { signal: controller.signal, redirect: "error" });
      if (!res.ok) return false;
      return accept(await res.json().catch(() => null));
    } catch {
      return null;
    } finally {
      clearTimeout(timer);
    }
  };
  const info = await attempt("/api/octop-bot/server-info", (body) =>
    (body as { product?: unknown } | null)?.product === "octop-bot",
  );
  if (info === true) return { ok: true };
  if (info === null) return { ok: false, reason: "unreachable" };
  const legacy = await attempt("/api/setup/status", (body) => typeof body === "object" && body !== null);
  if (legacy === true) return { ok: true };
  return { ok: false, reason: legacy === null ? "unreachable" : "not-octop" };
}
