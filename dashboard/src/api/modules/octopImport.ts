import { request } from "../request";

/** An assistant in the Octop install on this computer. */
export type OctopImportAgent = {
  agent_id: string;
  name: string;
  threads: number;
  /** Already here (imported before); importing skips it. */
  exists: boolean;
};

export type OctopImportPreview = {
  /** Whether Octop is installed on this computer. */
  available: boolean;
  home?: string | null;
  agents: OctopImportAgent[];
  /** Octop model providers not here yet. */
  providers: string[];
};

export type OctopImportedAgent = {
  agent_id: string;
  name: string;
  status: "imported" | "skipped" | "failed";
  reason: string;
  detail: string;
  threads: number;
  channels: number;
  cron_jobs: number;
};

export type OctopImportReport = {
  home: string;
  agents: OctopImportedAgent[];
  providers: string[];
};

const path = "/octop-bot/octop-import";

/** Desktop app only: bring in the assistants, chats and model keys of a local Octop. */
export const octopImportApi = {
  preview: () => request<OctopImportPreview>(path),
  run: () => request<OctopImportReport>(path, { method: "POST" }),
};
