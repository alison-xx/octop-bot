import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  botProfileApi,
  type LibraryFile,
  type UpcomingJob,
} from "../../api/modules/botProfile";
import { octopCronApi } from "../../api/modules/cronjob";
import { saveBlobAsFile } from "../../utils/saveBlobAsFile";
import BotActivityLibrary, { fileIcon } from "./BotActivityLibrary";

const i18n = vi.hoisted(() => ({
  t: (k: string, p?: Record<string, string>) =>
    p?.name ? k + " " + p.name : k,
}));
vi.mock("react-i18next", () => ({ useTranslation: () => i18n }));
vi.mock("../../api/modules/botProfile", () => ({
  botProfileApi: { upcoming: vi.fn(), library: vi.fn(), download: vi.fn() },
}));
vi.mock("../../api/modules/cronjob", () => ({
  octopCronApi: { patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("../../utils/saveBlobAsFile", () => ({ saveBlobAsFile: vi.fn() }));

function job(n: number, extra: Partial<UpcomingJob> = {}): UpcomingJob {
  return {
    id: "job-" + n,
    name: "Task " + n,
    enabled: true,
    trigger: "cron:0 9 * * *",
    schedule: "工作日 8:50",
    next_run_at: 1_700_000_000 + n,
    can_toggle: true,
    ...extra,
  };
}

function file(name: string, period: LibraryFile["period"]): LibraryFile {
  return {
    name,
    path: "outbound/" + name,
    size: 10,
    mime: null,
    created_at: 1,
    thread_id: "t1",
    period,
    url: "/api/agents/writer/workspace/download?path=outbound%2F" + name,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(octopCronApi.patch).mockResolvedValue({} as never);
});

describe("Bot profile activity", () => {
  it("shows five upcoming tasks first, then the rest on Show more", async () => {
    vi.mocked(botProfileApi.upcoming).mockResolvedValue({
      timezone: "Asia/Shanghai",
      jobs: [1, 2, 3, 4, 5, 6, 7].map((n) => job(n)),
    });
    render(<BotActivityLibrary agentId="writer" canToggle />);
    expect(await screen.findByText("Task 1")).toBeInTheDocument();
    expect(screen.getAllByText("工作日 8:50")).toHaveLength(5);
    expect(screen.queryByText("Task 6")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "botProfile.showMore" }),
    );
    expect(screen.getByText("Task 7")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "botProfile.showMore" }),
    ).not.toBeInTheDocument();
  });

  it("deletes a task after confirming, and only for someone who may manage it", async () => {
    vi.mocked(botProfileApi.upcoming).mockResolvedValue({
      timezone: "UTC",
      jobs: [job(1), job(2)],
    });
    vi.mocked(octopCronApi.delete).mockResolvedValue(undefined);
    const { unmount } = render(
      <BotActivityLibrary agentId="writer" canToggle />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "botProfile.delete Task 1" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "common.delete" }),
    );
    expect(octopCronApi.delete).toHaveBeenCalledWith("writer", "job-1");
    await vi.waitFor(() =>
      expect(screen.queryByText("Task 1")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Task 2")).toBeInTheDocument();
    unmount();
    render(<BotActivityLibrary agentId="writer" canToggle={false} />);
    expect(await screen.findByText("Task 1")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "botProfile.delete Task 1" }),
    ).not.toBeInTheDocument();
  });

  it("turns a task off through the cron API and reloads the order", async () => {
    vi.mocked(botProfileApi.upcoming)
      .mockResolvedValueOnce({ timezone: "UTC", jobs: [job(1)] })
      .mockResolvedValue({
        timezone: "UTC",
        jobs: [job(1, { enabled: false, next_run_at: null })],
      });
    render(<BotActivityLibrary agentId="writer" canToggle />);
    const toggle = await screen.findByRole("switch", {
      name: "botProfile.toggle Task 1",
    });
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
    expect(octopCronApi.patch).toHaveBeenCalledWith("writer", "job-1", {
      enabled: false,
    });
    await vi.waitFor(() =>
      expect(botProfileApi.upcoming).toHaveBeenCalledTimes(2),
    );
    expect(
      screen.getByRole("switch", { name: "botProfile.toggle Task 1" }),
    ).not.toBeChecked();
  });

  it("keeps toggles read-only without schedule permission", async () => {
    vi.mocked(botProfileApi.upcoming).mockResolvedValue({
      timezone: "UTC",
      jobs: [job(1)],
    });
    render(<BotActivityLibrary agentId="writer" canToggle={false} />);
    expect(
      await screen.findByRole("switch", { name: "botProfile.toggle Task 1" }),
    ).toBeDisabled();
  });

  it("says when there is nothing scheduled", async () => {
    vi.mocked(botProfileApi.upcoming).mockResolvedValue({
      timezone: "UTC",
      jobs: [],
    });
    render(<BotActivityLibrary agentId="writer" canToggle />);
    expect(
      await screen.findByText("botProfile.noUpcoming"),
    ).toBeInTheDocument();
  });
});

describe("Bot profile library", () => {
  it("groups files by recency and downloads one on click", async () => {
    vi.mocked(botProfileApi.upcoming).mockResolvedValue({
      timezone: "UTC",
      jobs: [],
    });
    vi.mocked(botProfileApi.library).mockResolvedValue({
      files: [
        file("brief.pdf", "today"),
        file("old.xlsx", "older"),
        file("plan.md", "week"),
      ],
    });
    const blob = new Blob(["x"]);
    vi.mocked(botProfileApi.download).mockResolvedValue(blob);
    render(<BotActivityLibrary agentId="writer" canToggle />);
    fireEvent.click(screen.getByText("botProfile.library"));
    const today = await screen.findByRole("region", {
      name: "botProfile.today",
    });
    expect(within(today).getByText("brief.pdf")).toBeInTheDocument();
    const headings = screen
      .getAllByRole("heading")
      .map((node) => node.textContent);
    expect(headings).toEqual([
      "botProfile.today",
      "botProfile.week",
      "botProfile.older",
    ]);
    fireEvent.click(
      screen.getByRole("button", { name: "botProfile.download plan.md" }),
    );
    expect(botProfileApi.download).toHaveBeenCalledWith(
      "writer",
      "outbound/plan.md",
    );
    await vi.waitFor(() =>
      expect(saveBlobAsFile).toHaveBeenCalledWith(blob, "plan.md"),
    );
  });

  it("says when the Bot has made nothing yet", async () => {
    vi.mocked(botProfileApi.upcoming).mockResolvedValue({
      timezone: "UTC",
      jobs: [],
    });
    vi.mocked(botProfileApi.library).mockResolvedValue({ files: [] });
    render(<BotActivityLibrary agentId="writer" canToggle />);
    fireEvent.click(screen.getByText("botProfile.library"));
    expect(await screen.findByText("botProfile.noFiles")).toBeInTheDocument();
  });

  it("picks an icon from the type or the extension", () => {
    expect(fileIcon({ name: "a.png", mime: "image/png" }).displayName).toBe(
      "FileImage",
    );
    expect(fileIcon({ name: "deck.key", mime: null }).displayName).toBe(
      "Presentation",
    );
    expect(fileIcon({ name: "blob.bin", mime: null }).displayName).toBe("File");
  });
});

describe.each(["activity", "library"] as const)(
  "profile %s recovery",
  (tab) => {
    const activate = () => {
      render(<BotActivityLibrary agentId="writer" canToggle />);
      if (tab === "library")
        fireEvent.click(screen.getByText("botProfile.library"));
    };
    const request =
      tab === "activity"
        ? vi.mocked(botProfileApi.upcoming)
        : vi.mocked(botProfileApi.library);
    const data = {
      jobs: [job(1)],
      timezone: "UTC",
      files: [file("report.pdf", "today")],
    };
    it("recovers after an unexpected successful response", async () => {
      request
        .mockResolvedValueOnce("<html></html>" as never)
        .mockResolvedValueOnce(data);
      activate();
      fireEvent.click(
        await screen.findByRole("button", { name: "common.retry" }),
      );
      expect(
        await screen.findByText(tab === "activity" ? "Task 1" : "report.pdf"),
      ).toBeVisible();
    });
    it("aborts a stalled request and allows another attempt", async () => {
      vi.useFakeTimers();
      try {
        request
          .mockReturnValueOnce(new Promise(() => {}))
          .mockResolvedValueOnce(data);
        activate();
        const signal = request.mock.lastCall?.[1];
        await act(async () => {
          await vi.advanceTimersByTimeAsync(15000);
        });
        expect(signal?.aborted).toBe(true);
        expect(screen.getByText("botProfile.loadTimeout")).toBeVisible();
        await act(async () => {
          fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
        });
        expect(
          screen.getByText(tab === "activity" ? "Task 1" : "report.pdf"),
        ).toBeVisible();
      } finally {
        vi.useRealTimers();
      }
    });
  },
);
