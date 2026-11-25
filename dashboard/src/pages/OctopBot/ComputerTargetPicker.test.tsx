import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { desktopComputerApi } from "../../api/modules/botCloudComputer";
import ComputerTargetPicker from "./ComputerTargetPicker";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: "en" } }),
}));
vi.mock("../../api/modules/botCloudComputer", () => ({
  desktopComputerApi: { set: vi.fn(), login: vi.fn() },
}));
vi.mock("./LynxceSignInForm", () => ({
  default: (props: { onPassword(a: string, p: string): Promise<unknown> }) => (
    <button onClick={() => void props.onPassword("test", "test-value")}>
      verify account
    </button>
  ),
}));
beforeEach(() => vi.resetAllMocks());
it("asks before switching to cloud and leaves the target alone on cancellation", async () => {
  render(
    <ComputerTargetPicker id="writer" target="local" onChanged={vi.fn()} />,
  );
  fireEvent.click(screen.getByText("cloudComputer.targetCloud"));
  await waitFor(() =>
    expect(screen.getByText("cloudComputer.targetConsent")).toBeVisible(),
  );
  fireEvent.click(screen.getByText("Cancel"));
  expect(desktopComputerApi.set).not.toHaveBeenCalled();
});
it("retries the switch after cloud account verification", async () => {
  vi.mocked(desktopComputerApi.set)
    .mockRejectedValueOnce(
      new Error(
        JSON.stringify({ error: { code: "BOT_CLOUD_REVERIFY_REQUIRED" } }),
      ),
    )
    .mockResolvedValueOnce({ target: "cloud" });
  const changed = vi.fn();
  render(
    <ComputerTargetPicker id="writer" target="local" onChanged={changed} />,
  );
  fireEvent.click(screen.getByText("cloudComputer.targetCloud"));
  fireEvent.click(await screen.findByText("OK"));
  fireEvent.click(await screen.findByText("verify account"));
  await waitFor(() => expect(changed).toHaveBeenCalledOnce());
  expect(desktopComputerApi.login).toHaveBeenCalledWith("test", "test-value");
  expect(desktopComputerApi.set).toHaveBeenCalledTimes(2);
});
it("switches back to local directly", async () => {
  const changed = vi.fn();
  render(
    <ComputerTargetPicker id="writer" target="cloud" onChanged={changed} />,
  );
  fireEvent.click(screen.getByText("cloudComputer.targetLocal"));
  await waitFor(() => expect(changed).toHaveBeenCalledOnce());
  expect(desktopComputerApi.set).toHaveBeenCalledWith("writer", "local");
});
