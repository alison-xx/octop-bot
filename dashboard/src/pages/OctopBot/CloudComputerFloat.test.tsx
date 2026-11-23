import { describe, expect, it } from "vitest";
import type { CloudComputerStatus } from "../../api/modules/botCloudComputer";
import { nearestCorner, nextMode } from "./CloudComputerFloat";

const running: CloudComputerStatus = {
  state: "running",
  spec: "standard",
  running_since: 1,
  paid_until: 2,
  takeover: false,
  busy: false,
  activity: null,
  activity_at: null,
};
const now = 1_800_000_000_000;
const rules = { pillOnly: false, idleSinceMs: null, nowMs: now };

describe("cloud computer float", () => {
  it("opens the live window when the Bot starts working, unless kept as a pill", () => {
    const busy = { ...running, busy: true, activity: "click" };
    expect(nextMode("hidden", busy, rules)).toBe("window");
    expect(nextMode("pill", busy, { ...rules, pillOnly: true })).toBe("pill");
    expect(nextMode("expanded", busy, rules)).toBe("expanded");
  });

  it("shrinks to the pill 30 s after the Bot stops, and hides when the computer is off", () => {
    expect(
      nextMode("window", running, { ...rules, idleSinceMs: now - 5_000 }),
    ).toBe("window");
    expect(
      nextMode("window", running, { ...rules, idleSinceMs: now - 31_000 }),
    ).toBe("pill");
    expect(nextMode("pill", { ...running, state: "paused" }, rules)).toBe(
      "hidden",
    );
    expect(nextMode("window", null, rules)).toBe("hidden");
  });

  it("goes big for a takeover and shows a pill for a computer used just now", () => {
    expect(nextMode("pill", { ...running, takeover: true }, rules)).toBe(
      "expanded",
    );
    const recent = { ...running, activity_at: now / 1000 - 30 };
    expect(nextMode("hidden", recent, rules)).toBe("pill");
    const old = { ...running, activity_at: now / 1000 - 600 };
    expect(nextMode("hidden", old, rules)).toBe("hidden");
  });

  it("snaps a dragged window to the nearest corner", () => {
    expect(nearestCorner(900, 700, 1000, 800)).toBe("br");
    expect(nearestCorner(10, 10, 1000, 800)).toBe("tl");
    expect(nearestCorner(10, 700, 1000, 800)).toBe("bl");
  });
});
