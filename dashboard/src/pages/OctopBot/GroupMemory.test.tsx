import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { octopBotApi } from "../../api/modules/octopBot";
import GroupMemory from "./GroupMemory";

const t = (key: string) => key;
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t }) }));
vi.mock("../../api/modules/octopBot", () => ({
  octopBotApi: { memory: vi.fn(), saveMemory: vi.fn() },
}));

describe("GroupMemory", () => {
  const getComputedStyle = window.getComputedStyle;
  beforeAll(() => {
    vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
      getComputedStyle(element),
    );
  });

  it("retries a failed load and clears the error once the memory arrives", async () => {
    vi.mocked(octopBotApi.memory)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ text: "Remember the brief" });
    render(<GroupMemory id="room" onClose={() => {}} />);
    await screen.findByText("offline");
    expect(
      screen.getByRole("button", { name: "octopBot.save" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "octopBot.retry" }));
    expect(
      await screen.findByRole("textbox", { name: "octopBot.groupMemory" }),
    ).toHaveValue("Remember the brief");
    expect(screen.queryByText("offline")).toBeNull();
  });
});
