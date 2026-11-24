import { afterEach, describe, expect, it, vi } from "vitest";
import {
  copyToThisDevice,
  installMacShortcuts,
  isApplePlatform,
} from "./macShortcuts";

const CONTROL = 0xffe3;

function setup(withClipboard = true) {
  const host = document.createElement("div");
  const canvas = document.createElement("canvas");
  host.appendChild(canvas);
  document.body.appendChild(host);
  const sent: [number, string | null, boolean | undefined][] = [];
  // noVNC listens on its canvas; anything reaching it would go to the desktop as-is.
  const reachedNoVnc = vi.fn();
  canvas.addEventListener("keydown", reachedNoVnc);
  const clipboard = { paste: vi.fn(), copyBack: vi.fn() };
  const cleanup = installMacShortcuts(
    host,
    () => ({ sendKey: (k, c, d) => void sent.push([k, c, d]) }),
    withClipboard ? clipboard : null,
  );
  const press = (init: KeyboardEventInit) => {
    const event = new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      ...init,
    });
    canvas.dispatchEvent(event);
    return event;
  };
  return { host, sent, reachedNoVnc, clipboard, cleanup, press };
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("Mac shortcuts on the cloud computer", () => {
  it("knows a Mac", () => {
    expect(isApplePlatform("MacIntel")).toBe(true);
    expect(isApplePlatform("iPhone")).toBe(true);
    expect(isApplePlatform("Win32")).toBe(false);
  });

  it("sends ⌘ shortcuts as Ctrl and never sends ⌘ itself", () => {
    const { sent, reachedNoVnc, press, cleanup } = setup(false);
    expect(
      press({ key: "Meta", code: "MetaLeft", metaKey: true }).defaultPrevented,
    ).toBe(true);
    press({ key: "a", code: "KeyA", metaKey: true });
    press({ key: "Z", code: "KeyZ", metaKey: true, shiftKey: true });
    expect(sent).toEqual([
      [CONTROL, "ControlLeft", true],
      [0x61, "KeyA", undefined],
      [CONTROL, "ControlLeft", false],
      [CONTROL, "ControlLeft", true],
      [0x7a, "KeyZ", undefined],
      [CONTROL, "ControlLeft", false],
    ]);
    expect(reachedNoVnc).not.toHaveBeenCalled();
    // Plain typing still goes to noVNC.
    press({ key: "a", code: "KeyA" });
    expect(reachedNoVnc).toHaveBeenCalledOnce();
    cleanup();
  });

  it("copies back after ⌘C and pastes this Mac's clipboard on ⌘V", () => {
    const { sent, clipboard, press, cleanup } = setup();
    press({ key: "c", code: "KeyC", metaKey: true });
    expect(sent[1]).toEqual([0x63, "KeyC", undefined]);
    expect(clipboard.copyBack).toHaveBeenCalledOnce();

    // ⌘V is left to the browser, whose paste event carries this Mac's clipboard.
    const keydown = press({ key: "v", code: "KeyV", metaKey: true });
    expect(keydown.defaultPrevented).toBe(false);
    const paste = new Event("paste", { bubbles: true, cancelable: true });
    Object.assign(paste, {
      clipboardData: { getData: () => "你好，Mac" },
    });
    document.body.dispatchEvent(paste);
    expect(clipboard.paste).toHaveBeenCalledWith("你好，Mac");
    expect(sent).toHaveLength(3); // no Ctrl+V of the cloud's own clipboard

    // A later paste somewhere else on the page is not taken.
    document.body.dispatchEvent(paste);
    expect(clipboard.paste).toHaveBeenCalledOnce();
    cleanup();
  });

  it("falls back to writeText when ClipboardItem is unavailable", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    expect(await copyToThisDevice(Promise.resolve("剪贴板"))).toBe(true);
    expect(writeText).toHaveBeenCalledWith("剪贴板");
  });
});
