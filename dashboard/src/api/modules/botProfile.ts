import { request, requestBlob } from "../request";

export interface UpcomingJob {
  id: string;
  name: string;
  enabled: boolean;
  trigger: string;
  /** One line from the server, localized and in the server timezone. */
  schedule: string;
  next_run_at: number | null;
  can_toggle: boolean;
}

export interface LibraryFile {
  name: string;
  path: string;
  size: number | null;
  mime: string | null;
  created_at: number;
  thread_id: string;
  period: "today" | "week" | "older";
  url: string;
}

const bot = (id: string) => "/octop-bot/bots/" + encodeURIComponent(id);

export const botProfileApi = {
  upcoming: (agentId: string, signal?: AbortSignal) =>
    request<{ timezone: string; jobs: UpcomingJob[] }>(
      bot(agentId) + "/upcoming",
      { signal },
    ),
  library: (agentId: string, signal?: AbortSignal) =>
    request<{ files: LibraryFile[] }>(bot(agentId) + "/library", { signal }),
  download: (agentId: string, path: string) =>
    requestBlob(
      "/agents/" +
        encodeURIComponent(agentId) +
        "/workspace/download?path=" +
        encodeURIComponent(path),
    ),
};
