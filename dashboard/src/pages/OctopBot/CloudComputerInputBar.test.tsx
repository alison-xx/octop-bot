import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { botCloudComputerApi } from "../../api/modules/botCloudComputer";
import CloudComputerInputBar from "./CloudComputerInputBar";

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

function Bar() {
  const [note, setNote] = useState("");
  return <CloudComputerInputBar session="s1" note={note} onNote={setNote} />;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("cloud computer input bar", () => {
  it("sends IME text on Enter, but not the Enter that picks a word", async () => {
    const typeText = vi
      .spyOn(botCloudComputerApi, "typeText")
      .mockResolvedValue(undefined);
    render(<Bar />);
    const field = screen.getByPlaceholderText("cloudComputer.inputPlaceholder");
    fireEvent.change(field, { target: { value: "你好" } });
    fireEvent.keyDown(field, { key: "Enter", isComposing: true });
    expect(typeText).not.toHaveBeenCalled();
    fireEvent.keyDown(field, { key: "Enter" });
    expect(typeText).toHaveBeenCalledWith("s1", "你好");
    expect(await screen.findByText("cloudComputer.typed")).toBeInTheDocument();
    expect(field).toHaveValue("");
  });

  it("copies the cloud clipboard to this device", async () => {
    vi.spyOn(botCloudComputerApi, "readClipboard").mockResolvedValue({
      text: "剪贴板",
    });
    const written: Blob[] = [];
    vi.stubGlobal(
      "ClipboardItem",
      class {
        constructor(items: Record<string, Promise<Blob>>) {
          void items["text/plain"].then((blob) => written.push(blob));
        }
      },
    );
    const write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { write },
      configurable: true,
    });
    render(<Bar />);
    await userEvent.click(
      screen.getByRole("button", { name: "cloudComputer.fetchClipboard" }),
    );
    expect(
      await screen.findByText("cloudComputer.clipboardCopied"),
    ).toBeInTheDocument();
    expect(write).toHaveBeenCalledOnce();
    // jsdom's Blob cannot be read back; "剪贴板" is 9 bytes of UTF-8.
    expect(written[0].type).toBe("text/plain");
    expect(written[0].size).toBe(9);
  });

  it("leaves the text in the field when it cannot write the clipboard", async () => {
    vi.spyOn(botCloudComputerApi, "readClipboard").mockResolvedValue({
      text: "剪贴板",
    });
    Object.defineProperty(navigator, "clipboard", {
      value: undefined,
      configurable: true,
    });
    render(<Bar />);
    await userEvent.click(
      screen.getByRole("button", { name: "cloudComputer.fetchClipboard" }),
    );
    expect(
      await screen.findByText("cloudComputer.clipboardShown"),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("cloudComputer.inputPlaceholder"),
    ).toHaveValue("剪贴板");
  });
});
