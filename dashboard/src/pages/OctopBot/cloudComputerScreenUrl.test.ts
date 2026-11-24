import { describe, expect, it, vi } from "vitest";

vi.mock("@novnc/novnc", () => ({ default: class {} }));

describe("screen socket URL", () => {
  it("follows the page's scheme", async () => {
    const { screenSocketUrl } = await import("./CloudComputerScreen");
    expect(
      screenSocketUrl("/api/x/screen/ws?ticket=a", "https://bot.lynxce.cn"),
    ).toBe("wss://bot.lynxce.cn/api/x/screen/ws?ticket=a");
    expect(
      screenSocketUrl("/api/x/screen/ws?ticket=a", "http://127.0.0.1:18791"),
    ).toBe("ws://127.0.0.1:18791/api/x/screen/ws?ticket=a");
  });
});
