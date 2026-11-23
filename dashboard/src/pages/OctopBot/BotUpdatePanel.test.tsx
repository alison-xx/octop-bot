import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DesktopBotUpdateStatus } from "../../utils/desktopBridge";
import BotUpdatePanel, { plainNotes } from "./BotUpdatePanel";

const apply = vi.fn(() => Promise.resolve());
const check = vi.fn();
const set = vi.fn();
let push: ((status: DesktopBotUpdateStatus) => void) | null = null;

const status = (
  patch: Partial<DesktopBotUpdateStatus>,
): DesktopBotUpdateStatus => ({
  kind: "idle",
  currentVersion: "1.0.3",
  version: null,
  notes: null,
  urgent: false,
  error: null,
  ...patch,
});

beforeEach(() => {
  apply.mockClear();
  check.mockReset().mockResolvedValue(status({ kind: "idle" }));
  set.mockReset().mockImplementation((patch) =>
    Promise.resolve({
      launchAtLogin: false,
      closeBehavior: "tray",
      themeBackground: "system",
      stableOnly: true,
      autoDownloadUpdates: true,
      ...patch,
    }),
  );
  window.octopDesktop = {
    botOnly: true,
    getPlatformInfo: vi.fn(),
    openDirectoryPicker: vi.fn(),
    openFilePicker: vi.fn(),
    onBackendReady: () => () => {},
    setWindowChrome: () => {},
    clientSettings: {
      get: vi.fn().mockResolvedValue({
        launchAtLogin: false,
        closeBehavior: "tray",
        themeBackground: "system",
        stableOnly: true,
        autoDownloadUpdates: true,
      }),
      set,
    },
    session: { register: vi.fn(), renew: vi.fn(), revoke: vi.fn() },
    checkForUpdates: vi.fn(),
    installUpdate: vi.fn(),
    botUpdates: {
      state: vi
        .fn()
        .mockResolvedValue(
          status({ kind: "ready", version: "1.0.4", notes: "自动更新" }),
        ),
      check,
      apply,
      onChange: (callback) => {
        push = callback;
        return () => {
          push = null;
        };
      },
    },
  } as unknown as typeof window.octopDesktop;
});

afterEach(() => {
  delete window.octopDesktop;
  push = null;
});

describe("<BotUpdatePanel />", () => {
  it("offers a waiting release and installs it on request", async () => {
    const user = userEvent.setup();
    render(<BotUpdatePanel />);
    expect(
      await screen.findByText("botClient.update.ready"),
    ).toBeInTheDocument();
    expect(screen.getByText("自动更新")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "botClient.update.restart" }),
    );
    expect(apply).toHaveBeenCalledTimes(1);
  });

  it("follows pushed state and the switches write client settings", async () => {
    const user = userEvent.setup();
    render(<BotUpdatePanel />);
    await screen.findByText("botClient.update.ready");
    act(() => push?.(status({ kind: "idle" })));
    expect(screen.getByText("botClient.update.upToDate")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "botClient.update.check" }),
    );
    expect(check).toHaveBeenCalledTimes(1);
    const [autoDownload, beta] = screen.getAllByRole("switch");
    await user.click(autoDownload!);
    expect(set).toHaveBeenLastCalledWith({ autoDownloadUpdates: false });
    await user.click(beta!);
    expect(set).toHaveBeenLastCalledWith({ stableOnly: false });
  });

  it("renders nothing outside the Octop Bot desktop shell", () => {
    delete window.octopDesktop;
    const { container } = render(<BotUpdatePanel />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("plainNotes", () => {
  it("drops Markdown marks from changelog notes", () => {
    expect(
      plainNotes("### 新增\n\n- **自动更新**：用 `manifest`\n\n\n- 修复"),
    ).toBe("新增\n\n- 自动更新：用 manifest\n\n- 修复");
  });
});
