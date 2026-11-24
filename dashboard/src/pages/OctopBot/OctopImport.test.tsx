import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OctopImport from "./OctopImport";

const preview = vi.fn();
const run = vi.fn();

vi.mock("../../api/modules/octopImport", () => ({
  octopImportApi: { preview: () => preview(), run: () => run() },
}));
vi.mock("../../utils/desktopBridge", () => ({
  getDesktopBridge: () => ({}),
  isBotWebClient: () => false,
}));

const found = {
  available: true,
  home: "/Users/me/.octop",
  agents: [
    { agent_id: "A1", name: "Writer", threads: 3, exists: false },
    { agent_id: "A2", name: "Editor", threads: 2, exists: true },
  ],
  providers: ["deepseek"],
};

beforeEach(() => {
  preview.mockReset();
  run.mockReset();
});

describe("OctopImport", () => {
  it("shows nothing when Octop is not installed", async () => {
    preview.mockResolvedValue({ available: false, agents: [], providers: [] });
    const { container } = render(<OctopImport />);
    await waitFor(() => expect(preview).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("imports after confirming and reports what came in", async () => {
    preview.mockResolvedValue(found);
    run.mockResolvedValue({
      home: found.home,
      providers: ["deepseek"],
      agents: [
        {
          agent_id: "A1",
          name: "Writer",
          status: "imported",
          reason: "",
          detail: "",
          threads: 3,
          channels: 1,
          cron_jobs: 0,
        },
        {
          agent_id: "A2",
          name: "Editor",
          status: "skipped",
          reason: "exists",
          detail: "",
          threads: 0,
          channels: 0,
          cron_jobs: 0,
        },
      ],
    });
    render(<OctopImport />);
    // Only the assistant not imported yet counts.
    expect(
      await screen.findByText("botClient.octopImport.found"),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /botClient.octopImport.action/ }),
    );
    expect(
      await screen.findByText("botClient.octopImport.confirmBody"),
    ).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", {
      name: /botClient.octopImport.action/,
    });
    await userEvent.click(buttons[buttons.length - 1]);

    expect(run).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText("botClient.octopImport.done"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("botClient.octopImport.paused"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("botClient.octopImport.skipped"),
    ).toBeInTheDocument();
    expect(preview).toHaveBeenCalledTimes(2);
  });
});
