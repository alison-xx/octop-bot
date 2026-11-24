import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { botCloudApi } from "../../api/modules/botCloud";
import CloudMove from "./CloudMove";

const useLynxceCloud = vi.fn().mockResolvedValue(true);
vi.mock("../../utils/desktopBridge", () => ({
  isBotOnlyDesktop: () => true,
  getDesktopBridge: () => ({ botOnly: true, useLynxceCloud }),
}));
vi.mock("../../api/modules/botCloud", () => ({
  botCloudApi: { account: vi.fn(), move: vi.fn(), moveStatus: vi.fn() },
}));
vi.mock("react-i18next", () => {
  const t = (key: string, vars?: { defaultValue?: string }) =>
    key.startsWith("apiErrors.") ? vars?.defaultValue ?? key : key;
  return { useTranslation: () => ({ t }) };
});

const api = vi.mocked(botCloudApi);
const idle = {
  state: "idle" as const,
  done: 0,
  total: 0,
  error_code: null,
  access_token: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.stubEnv("VITE_OCTOP_BOT_CLOUD_MOVE", "1");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

it("stays on this computer after a Lynxce sign-in unless the build turns the move on", async () => {
  vi.stubEnv("VITE_OCTOP_BOT_CLOUD_MOVE", "");
  api.account.mockResolvedValue({
    connected: true,
    account_id: "lx1",
    display_name: "Alison",
  });
  api.moveStatus.mockResolvedValue(idle);

  render(<CloudMove />);
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(screen.queryByText("botCloudMove.start")).toBeNull();
  expect(api.account).not.toHaveBeenCalled();
  expect(api.moveStatus).not.toHaveBeenCalled();
  expect(api.move).not.toHaveBeenCalled();
  expect(useLynxceCloud).not.toHaveBeenCalled();
});

it("moves the team after a Lynxce sign-in and reopens on the cloud", async () => {
  api.account.mockResolvedValue({
    connected: true,
    account_id: "lx1",
    display_name: "Alison",
  });
  api.moveStatus.mockResolvedValueOnce(idle).mockResolvedValue({
    ...idle,
    state: "done",
    done: 3,
    total: 3,
    access_token: "cloud-jwt",
  });
  api.move.mockResolvedValue({ ...idle, state: "running", total: 3 });

  render(<CloudMove />);
  fireEvent.click(await screen.findByText("botCloudMove.start"));
  await waitFor(
    () => expect(useLynxceCloud).toHaveBeenCalledWith("cloud-jwt"),
    {
      timeout: 3000,
    },
  );
  expect(screen.getByText("botCloudMove.switching")).toBeTruthy();
});

it("stays out of the way without a Lynxce sign-in, and after Not now", async () => {
  api.account.mockResolvedValue({
    connected: false,
    account_id: null,
    display_name: null,
  });
  api.moveStatus.mockResolvedValue(idle);
  const { unmount } = render(<CloudMove />);
  await waitFor(() => expect(api.moveStatus).toHaveBeenCalled());
  expect(screen.queryByText("botCloudMove.start")).toBeNull();
  unmount();

  api.account.mockResolvedValue({
    connected: true,
    account_id: "lx1",
    display_name: null,
  });
  render(<CloudMove />);
  fireEvent.click(await screen.findByText("botCloudMove.later"));
  await waitFor(() =>
    expect(screen.queryByText("botCloudMove.start")).toBeNull(),
  );
  expect(api.move).not.toHaveBeenCalled();
});

it("offers a retry when the move stopped", async () => {
  api.account.mockResolvedValue({
    connected: true,
    account_id: "lx1",
    display_name: null,
  });
  api.moveStatus.mockResolvedValue({
    ...idle,
    state: "failed",
    error_code: "NETWORK_ERROR",
  });
  render(<CloudMove />);
  expect(await screen.findByText("botCloudMove.failed")).toBeTruthy();
  expect(screen.getByText("botCloudMove.retry")).toBeTruthy();
});
