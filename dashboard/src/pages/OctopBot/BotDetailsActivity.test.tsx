import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { octopCronApi } from "../../api/modules/cronjob";
import type { OctopCronRow } from "../../api/types";
import { request } from "../../api/request";
import BotDetailsPanel from "./BotDetailsPanel";

const getComputedStyle = window.getComputedStyle;
beforeAll(() => {
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
    getComputedStyle(element),
  );
});
afterAll(() => {
  vi.mocked(window.getComputedStyle).mockRestore();
});

const mock = vi.hoisted(() => ({
  owner: true,
  bridge: false,
  permissions: ["tasks", "token_usage"],
  t: (k: string, p?: Record<string, string>) =>
    p?.name ? k + " " + p.name : k,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: mock.t, i18n: { language: "en" } }),
}));
vi.mock("../../context/AgentContext", () => ({
  useAgent: () => ({
    agents: [{ agent_id: "writer", is_owner: mock.owner, bridge: mock.bridge }],
    refresh: vi.fn(),
  }),
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ role: "member", permissions: mock.permissions }),
}));
vi.mock("../../hooks/useLynxceStatus", () => ({
  useLynxceStatus: () => ({ status: null }),
}));
vi.mock("../../api/modules/provider", () => ({
  providerApi: { listResolvedModels: async () => [] },
}));
vi.mock("../../api/modules/cronjob", () => ({
  octopCronApi: {
    list: vi.fn(),
    settings: vi.fn(),
    create: vi.fn(),
    patch: vi.fn(),
  },
}));
vi.mock("../../api/request", () => ({ request: vi.fn() }));
vi.mock("./BotCharacter", () => ({ BotCharacter: () => null }));

const job: OctopCronRow = {
  id: "daily-plan",
  agent_id: "writer",
  name: "Morning plan",
  prompt: "Review open work",
  trigger: "cron:15 8 * * *",
  task_type: "agent",
  enabled: true,
  session_key: "thread:thread-2",
  fresh_thread: false,
  model: null,
  last_run_at: null,
  last_status: null,
  last_error: null,
};
function CapabilityProbe() {
  const loc = useLocation();
  return (
    <output>{loc.pathname + loc.search + " from " + loc.state?.from}</output>
  );
}
function openDetails(path = "/octop-bot/bots/writer/thread-2") {
  const noop = () => {};
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/octop-bot/bots/:agentId/:threadId?"
          element={
            <BotDetailsPanel
              bot={{
                name: "Writer",
                agent_id: "writer",
                is_main: false,
                is_private: false,
              }}
              onClose={noop}
              onDelete={noop}
              onEdit={noop}
              onAppearance={noop}
              onHistory={noop}
              onMemory={noop}
              onPrivacy={noop}
              onSide={noop}
            />
          }
        />
        <Route path="*" element={<CapabilityProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  mock.owner = true;
  mock.bridge = false;
  mock.permissions = ["tasks", "token_usage"];
  vi.mocked(octopCronApi.list).mockResolvedValue([]);
  vi.mocked(octopCronApi.settings).mockResolvedValue({
    timezone: "Asia/Shanghai",
  });
  vi.mocked(octopCronApi.create).mockResolvedValue(job);
  vi.mocked(octopCronApi.patch).mockImplementation(
    async (_agent, _id, patch) => ({
      ...job,
      ...patch,
      name: job.name,
      fresh_thread: false,
      enabled: patch.enabled ?? true,
      prompt: job.prompt,
      session_key: job.session_key,
    }),
  );
});

describe("activity from the standalone Bot profile", () => {
  it("creates an actual agent schedule for this thread and persists pause/resume via the owner-scoped API", async () => {
    openDetails();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "botClient.activity.schedules",
      }),
    );
    expect(
      await screen.findByText("botClient.activity.noSchedules"),
    ).toBeInTheDocument();
    expect(octopCronApi.list).toHaveBeenCalledWith("writer");
    fireEvent.click(screen.getByRole("button", { name: "cronJobs.createJob" }));
    fireEvent.change(screen.getByLabelText("botClient.activity.taskName"), {
      target: { value: "Morning plan" },
    });
    fireEvent.change(screen.getByLabelText("botClient.activity.instructions"), {
      target: { value: "Review open work" },
    });
    fireEvent.change(screen.getByLabelText("botClient.activity.time"), {
      target: { value: "08:15" },
    });
    expect(
      screen.getByText("botClient.activity.deliverHere"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "cronJobs.createJob" }));
    expect(await screen.findByText("Morning plan")).toBeInTheDocument();
    expect(octopCronApi.create).toHaveBeenCalledWith("writer", {
      name: "Morning plan",
      prompt: "Review open work",
      trigger: "cron:15 8 * * *",
      task_type: "agent",
      allow_all: false,
      enabled: true,
      session_key: "thread:thread-2",
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "botClient.activity.pause Morning plan",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "botClient.activity.resume Morning plan",
      }),
    );
    await screen.findByRole("button", {
      name: "botClient.activity.pause Morning plan",
    });
    expect(octopCronApi.patch).toHaveBeenNthCalledWith(
      1,
      "writer",
      "daily-plan",
      { enabled: false },
    );
    expect(octopCronApi.patch).toHaveBeenNthCalledWith(
      2,
      "writer",
      "daily-plan",
      { enabled: true },
    );
  });

  it("can retry a failed list, keeps the form after creation fails and uses the Bot's local chat when no thread exists", async () => {
    vi.mocked(octopCronApi.list).mockRejectedValueOnce(
      new Error("Job list offline"),
    );
    vi.mocked(octopCronApi.create).mockRejectedValueOnce(
      new Error("Cannot save"),
    );
    openDetails("/octop-bot/bots/writer");
    fireEvent.click(
      await screen.findByRole("button", {
        name: "botClient.activity.schedules",
      }),
    );
    await screen.findByText("Job list offline");
    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "cronJobs.createJob" }),
    );
    fireEvent.change(screen.getByLabelText("botClient.activity.instructions"), {
      target: { value: "Prepare meeting notes" },
    });
    expect(
      screen.getByText("botClient.activity.deliverLatest"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "cronJobs.createJob" }));
    expect(await screen.findByText("Cannot save")).toBeInTheDocument();
    expect(
      screen.getByLabelText("botClient.activity.instructions"),
    ).toHaveValue("Prepare meeting notes");
    expect(octopCronApi.create).toHaveBeenCalledWith(
      "writer",
      expect.objectContaining({ session_key: "latest" }),
    );
  });

  it("validates one-off dates and submits the selected wall clock in server time", async () => {
    openDetails();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "botClient.activity.schedules",
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "cronJobs.createJob" }),
    );
    fireEvent.change(screen.getByLabelText("botClient.activity.instructions"), {
      target: { value: "Prepare Friday's review" },
    });
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: "botClient.activity.frequency" }),
    );
    fireEvent.click(await screen.findByText("botClient.activity.once"));
    const date = screen.getByLabelText("botClient.activity.time");
    fireEvent.change(date, { target: { value: "2000-01-01T14:30" } });
    fireEvent.click(screen.getByRole("button", { name: "cronJobs.createJob" }));
    expect(
      await screen.findByText("botClient.activity.future"),
    ).toBeInTheDocument();
    expect(octopCronApi.create).not.toHaveBeenCalled();
    fireEvent.change(date, { target: { value: "2099-04-24T14:30" } });
    fireEvent.click(screen.getByRole("button", { name: "cronJobs.createJob" }));
    await waitFor(() =>
      expect(octopCronApi.create).toHaveBeenCalledWith(
        "writer",
        expect.objectContaining({ trigger: "date:2099-04-24T14:30:00" }),
      ),
    );
  });

  it("loads model totals for this account and Bot, then handles an empty time window", async () => {
    vi.mocked(request)
      .mockResolvedValueOnce({
        total_tokens: 2450,
        model_calls: 2,
        input_tokens: 2300,
        output_tokens: 150,
        turns: 1,
        buckets: [
          { key: "model-A", label: "My chat model", total_tokens: 2450 },
        ],
      })
      .mockResolvedValueOnce({
        total_tokens: 0,
        model_calls: 0,
        turns: 0,
        buckets: [],
      });
    openDetails();
    fireEvent.click(
      await screen.findByRole("button", { name: "botClient.activity.usage" }),
    );
    expect(await screen.findByText("My chat model")).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith(
      "/usage/summary?agent_id=writer&window=last_7d&granularity=by_model",
    );
    expect(screen.getAllByText("2,450").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("tokenUsage.today"));
    expect(
      await screen.findByText("botClient.activity.noUsage"),
    ).toBeInTheDocument();
    expect(screen.queryByText("My chat model")).toBeNull();
    expect(request).toHaveBeenCalledWith(
      "/usage/summary?agent_id=writer&window=today&granularity=by_model",
    );
  });

  it("opens skills and connectors scoped to this Bot", async () => {
    mock.permissions = ["skills"];
    openDetails();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "botCapabilities.profileEntry",
      }),
    );
    expect(
      await screen.findByText(
        "/octop-bot/capabilities/skills?bot=writer from /octop-bot/bots/writer/thread-2",
      ),
    ).toBeInTheDocument();
  });

  it("does not offer capabilities for a remote Bot or without the permission", async () => {
    mock.permissions = ["skills"];
    mock.bridge = true;
    const view = openDetails();
    await screen.findByRole("button", { name: "octopBot.history" });
    expect(
      screen.queryByRole("button", { name: "botCapabilities.profileEntry" }),
    ).toBeNull();
    view.unmount();
    mock.bridge = false;
    mock.permissions = ["tasks"];
    openDetails();
    await screen.findByRole("button", { name: "octopBot.history" });
    expect(
      screen.queryByRole("button", { name: "botCapabilities.profileEntry" }),
    ).toBeNull();
  });

  it("does not expose the scheduler for another user's agent or usage without the role permission", async () => {
    mock.owner = false;
    mock.permissions = ["tasks"];
    openDetails();
    await waitFor(() =>
      expect(
        within(screen.getByLabelText("botClient.profile.title")).getByText(
          "Writer",
        ),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: "botClient.activity.schedules" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "botClient.activity.usage" }),
    ).toBeNull();
    expect(octopCronApi.list).not.toHaveBeenCalled();
    expect(request).not.toHaveBeenCalled();
  });
});
