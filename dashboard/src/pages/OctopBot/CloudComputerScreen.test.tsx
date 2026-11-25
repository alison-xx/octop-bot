import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { botCloudComputerApi } from "../../api/modules/botCloudComputer";
import {
  ACCESS_TOKEN_RENEWED_EVENT,
  setAuthToken,
  clearAuthToken,
} from "../../api/request";
import CloudComputerScreen from "./CloudComputerScreen";

const clients: { viewOnly: boolean }[] = [];

vi.mock("@novnc/novnc", () => ({
  default: class extends EventTarget {
    viewOnly = true;
    scaleViewport = false;
    constructor() {
      super();
      clients.push(this);
    }
    disconnect() {}
    sendKey() {}
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("cloud computer screen", () => {
  it("takes control granted while noVNC was still loading", async () => {
    const { rerender } = render(
      <CloudComputerScreen
        wsPath="/api/x/screen/ws?ticket=t"
        interactive={false}
      />,
    );
    // Takeover lands before the noVNC chunk has loaded and the client exists.
    rerender(
      <CloudComputerScreen wsPath="/api/x/screen/ws?ticket=t" interactive />,
    );
    await waitFor(() => expect(clients).toHaveLength(1));
    expect(clients[0].viewOnly).toBe(false);
  });
  it("keeps the open screen on a renewed dashboard sign-in", async () => {
    const renew = vi
      .spyOn(botCloudComputerApi, "renewScreen")
      .mockResolvedValue(undefined);
    setAuthToken("first");
    const view = render(
      <CloudComputerScreen
        wsPath="/api/screen"
        session="view"
        botId="bot"
        interactive={false}
      />,
    );
    try {
      await waitFor(() => expect(renew).toHaveBeenCalledWith("bot", "view"));
      setAuthToken("second");
      window.dispatchEvent(new Event(ACCESS_TOKEN_RENEWED_EVENT));
      expect(renew).toHaveBeenCalledTimes(2);
      window.dispatchEvent(new Event(ACCESS_TOKEN_RENEWED_EVENT));
      expect(renew).toHaveBeenCalledTimes(2);
      view.unmount();
      setAuthToken("third");
      window.dispatchEvent(new Event(ACCESS_TOKEN_RENEWED_EVENT));
      expect(renew).toHaveBeenCalledTimes(2);
    } finally {
      clearAuthToken();
      renew.mockRestore();
    }
  });
});
