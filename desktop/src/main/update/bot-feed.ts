/**
 * Octop Bot update feed.
 *
 * The Bot build does not use the upstream Octop catalog. It reads one signed
 * manifest that every Octop Bot client shares (see docs/octop-bot-updates.md):
 * `manifest.json` plus a detached Ed25519 signature `manifest.json.sig`, both on
 * dl.lynxce.cn. A manifest that does not verify against the key built into the
 * app is a failed check, so a tampered mirror cannot offer a package.
 *
 * This module only verifies and translates the manifest into the shell's
 * `DownloadManifest`, so release selection, download and hand-off stay shared.
 */

import { createHash, createPublicKey, verify } from "node:crypto";
import { compareVersions, parseVersion } from "../supervisor/version";
import type { ChannelRelease, DownloadAsset, DownloadManifest, PlatformKey } from "./update-coordinator";

export const BOT_FEED_URL = "https://dl.lynxce.cn/releases/octop-bot/manifest.json";

/** Public half of the release signing key (`scripts/octop_bot_manifest.py`). */
export const BOT_FEED_PUBLIC_KEY = `-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAjfzS5kpiVxqx/79rU5tYno7Js31ezDt05RmrmXnRTa0=
-----END PUBLIC KEY-----
`;

const DESKTOP_KEYS: readonly PlatformKey[] = ["mac_arm", "mac_intel", "win_x64", "win_arm"];

export interface BotAsset {
  name?: string;
  url: string;
  sha256?: string;
  size?: number;
}

export interface BotRelease {
  version: string;
  tag?: string;
  date?: string;
  notes?: { zh?: string; en?: string };
  notes_url?: string;
  min_supported?: string;
  rollout?: number;
  assets: Partial<Record<string, BotAsset>>;
}

export interface BotManifest {
  schema: 1;
  product: "octop-bot";
  channels: { stable?: BotRelease; beta?: BotRelease };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Check the signature over the exact downloaded bytes, then parse.
 * @throws when the signature or the shape is wrong.
 */
export function verifyBotManifest(
  body: string,
  signature: string,
  publicKeyPem: string = BOT_FEED_PUBLIC_KEY,
): BotManifest {
  let ok = false;
  try {
    ok = verify(null, Buffer.from(body, "utf8"), createPublicKey(publicKeyPem), Buffer.from(signature.trim(), "base64"));
  } catch {
    ok = false;
  }
  if (!ok) throw new Error("update manifest signature is invalid");
  const parsed: unknown = JSON.parse(body);
  if (!isRecord(parsed) || parsed.schema !== 1 || parsed.product !== "octop-bot" || !isRecord(parsed.channels)) {
    throw new Error("update manifest has an unexpected shape");
  }
  for (const name of ["stable", "beta"] as const) {
    const release = parsed.channels[name];
    if (release === undefined) continue;
    if (!isRecord(release) || typeof release.version !== "string" || !parseVersion(release.version) || !isRecord(release.assets)) {
      throw new Error(`update manifest channel ${name} is malformed`);
    }
  }
  return parsed as unknown as BotManifest;
}

/** Stable 0–99 bucket for staged rollouts: the same install keeps its bucket per version. */
export function rolloutBucket(installId: string, version: string): number {
  return createHash("sha256").update(`${installId}:${version}`).digest().readUInt32BE(0) % 100;
}

export function inRollout(release: BotRelease, installId: string): boolean {
  const share = typeof release.rollout === "number" ? release.rollout : 100;
  if (share >= 100) return true;
  if (share <= 0) return false;
  return rolloutBucket(installId, release.version) < share;
}

/** Highest `min_supported` across channels: installs below it must update. */
export function minimumSupported(manifest: BotManifest): string | null {
  const floors = [manifest.channels.stable?.min_supported, manifest.channels.beta?.min_supported].filter(
    (v): v is string => typeof v === "string" && parseVersion(v) !== null,
  );
  floors.sort((a, b) => compareVersions(b, a));
  return floors[0] ?? null;
}

function extOf(asset: BotAsset): string {
  const name = asset.name ?? new URL(asset.url).pathname.split("/").pop() ?? "";
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : "";
}

function channelRelease(release: BotRelease, installId: string): ChannelRelease {
  const assets: ChannelRelease["assets"] = {};
  // Outside this rollout share the release is listed but has nothing to install.
  if (inRollout(release, installId)) {
    for (const key of DESKTOP_KEYS) {
      const asset = release.assets[key];
      if (!asset || typeof asset.url !== "string") continue;
      const entry: DownloadAsset = { name: asset.name ?? key, ext: extOf(asset), url: asset.url };
      if (typeof asset.sha256 === "string") entry.sha256 = asset.sha256.toLowerCase();
      if (typeof asset.size === "number") entry.size = asset.size;
      assets[key] = entry;
    }
  }
  return {
    tag: release.version,
    releasesUrl: release.notes_url ?? "https://octop-bot.lynxce.cn/download.html",
    assets,
  };
}

/** The shell's catalog view of a verified Bot manifest. */
export function botDownloadManifest(manifest: BotManifest, installId: string): DownloadManifest {
  const client: DownloadManifest["client"] = {};
  if (manifest.channels.stable) client.stable = channelRelease(manifest.channels.stable, installId);
  if (manifest.channels.beta) client.beta = channelRelease(manifest.channels.beta, installId);
  return { client };
}

/** Release notes for the selected version, in the UI language. */
export function releaseNotes(manifest: BotManifest, version: string, chinese: boolean): string {
  for (const release of [manifest.channels.stable, manifest.channels.beta]) {
    if (release && release.version === version) {
      return (chinese ? release.notes?.zh || release.notes?.en : release.notes?.en || release.notes?.zh) ?? "";
    }
  }
  return "";
}
