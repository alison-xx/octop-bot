import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { botCloudComputerApi } from "../../api/modules/botCloudComputer";
import CloudComputerHandoff from "./CloudComputerHandoff";

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});
vi.mock("./CloudComputerScreen", () => ({
  default: ({
    wsPath,
    interactive,
  }: {
    wsPath: string;
    interactive: boolean;
  }) => (
    <div data-testid="screen">
      {wsPath} {interactive ? "control" : "view"}
    </div>
  ),
}));

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("cloud computer handoff", () => {
  it("takes the computer over and opens its screen in one click", async () => {
    const takeover = vi
      .spyOn(botCloudComputerApi, "takeover")
      .mockResolvedValue({} as never);
    vi.spyOn(botCloudComputerApi, "openScreen").mockResolvedValue({
      ws_path: "/ws?ticket=t",
      expires_in: 60,
      session: "s",
    });
    render(<CloudComputerHandoff botId="bot1" />);
    fireEvent.click(
      screen.getByRole("button", { name: /cloudComputer.handoffOpen/ }),
    );
    expect(await screen.findByTestId("screen")).toHaveTextContent(
      "/ws?ticket=t control",
    );
    expect(takeover).toHaveBeenCalledWith("bot1", true);
  });
  it("opens a legacy desktop screen without taking control away from the Bot", async () => {
    const takeover = vi.spyOn(botCloudComputerApi, "takeover");
    vi.spyOn(botCloudComputerApi, "openScreen").mockResolvedValue({
      ws_path: "/ws?ticket=read",
      expires_in: 60,
      session: { viewOnly: true },
    });
    render(<CloudComputerHandoff botId="bot1" />);
    fireEvent.click(
      screen.getByRole("button", { name: /cloudComputer.handoffOpen/ }),
    );
    expect(await screen.findByTestId("screen")).toHaveTextContent(
      "/ws?ticket=read view",
    );
    expect(
      screen.getByText("cloudComputer.legacyViewOnly"),
    ).toBeInTheDocument();
    expect(takeover).not.toHaveBeenCalled();
  });
});
