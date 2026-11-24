import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ChatInputActionsRow from "./ChatInputActionsRow";

// `isSttAvailable()` runs at module load, so the browser APIs it probes must
// exist before this module graph is imported.
vi.hoisted(() => {
  vi.stubGlobal("MediaRecorder", class {});
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getUserMedia: () => Promise.resolve() },
    configurable: true,
  });
  return true;
});

vi.mock("../../../utils/desktopBridge", async (original) => ({
  ...(await original<typeof import("../../../utils/desktopBridge")>()),
  isBotClient: () => true,
}));
vi.mock("./ContextWindowRing", () => ({
  default: () => <div data-testid="context-window-ring" />,
}));

const props = {
  isMobile: false,
  isStreaming: false,
  canSend: false,
  text: "",
  polishing: false,
  uploading: false,
  recording: false,
  transcribing: false,
  availableModels: [],
  onModelChange: vi.fn(),
  onConversationModeChange: vi.fn(),
  onHitlPolicyChange: vi.fn(),
  slashPickerGroups: null,
  slashMenuItems: [],
  onSlashShortcutSelect: vi.fn(),
  onFileSelect: vi.fn(),
  onFolderSelect: vi.fn(),
  onNewChat: vi.fn(),
  onPolish: vi.fn(),
  onToggleVoice: vi.fn(),
  onCancel: vi.fn(),
  onSubmit: vi.fn(),
};

function renderRow(overrides: Partial<typeof props>) {
  return render(
    <MemoryRouter>
      <ChatInputActionsRow {...props} {...overrides} />
    </MemoryRouter>,
  );
}

describe("Octop Bot composer voice input", () => {
  it("offers one voice control while there is nothing to send", () => {
    const onToggleVoice = vi.fn();
    renderRow({ onToggleVoice });
    const voice = screen.getAllByRole("button", { name: "语音输入" });
    expect(voice).toHaveLength(1);
    fireEvent.click(voice[0]);
    expect(onToggleVoice).toHaveBeenCalledTimes(1);
  });

  it("turns that control into stop while recording", () => {
    renderRow({ recording: true });
    expect(screen.getAllByRole("button", { name: "停止录音" })).toHaveLength(1);
  });

  it("sends once there is text, keeping the mic to dictate more", () => {
    const onSubmit = vi.fn();
    renderRow({ canSend: true, text: "hi", onSubmit });
    expect(screen.getAllByRole("button", { name: "语音输入" })).toHaveLength(1);
    const buttons = screen.getAllByRole("button");
    fireEvent.click(buttons[buttons.length - 1]);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
