import { describe, expect, it } from "vitest";

import type { BotActivitySnapshot } from "@/api/modules/botActivity";
import {
  advanceSeen,
  badgedTitle,
  newArrivals,
  parseTarget,
  previewText,
  totalUnread,
  unreadByTarget,
} from "./botActivity";

const snapshot = (
  bots: Array<[string, number, number | null]>,
  groups: Array<[string, number]> = [],
): BotActivitySnapshot => ({
  bots: bots.map(([agent_id, unread_count, last_active]) => ({
    agent_id,
    unread_count,
    last_active,
  })),
  groups: groups.map(([group_id, unread_count]) => ({
    group_id,
    unread_count,
    last_message: null,
  })),
});

describe("bot activity", () => {
  it("opens without a burst of badges on the first snapshot", () => {
    const first = snapshot([["a", 0, 100]]);
    const seen = advanceSeen(first, {}, null, true);
    expect(seen).toEqual({ a: 100 });
    expect(unreadByTarget(first, seen, null)).toEqual({});
  });

  it("marks a bot that replied while another chat was open", () => {
    const seen = { a: 100 };
    const later = snapshot([["a", 0, 160]]);
    expect(unreadByTarget(later, seen, "bot:b")).toEqual({ "bot:a": 1 });
    const opened = advanceSeen(later, seen, "bot:a", false);
    expect(unreadByTarget(later, opened, null)).toEqual({});
  });

  it("counts server pushes and group replies but never the open target", () => {
    const snap = snapshot([["a", 3, 160]], [["g", 2]]);
    expect(unreadByTarget(snap, { a: 100 }, null)).toEqual({
      "bot:a": 3,
      "group:g": 2,
    });
    expect(unreadByTarget(snap, { a: 100 }, "group:g")).toEqual({
      "bot:a": 3,
    });
  });

  it("lets a bot created after launch count its first reply", () => {
    const seen = advanceSeen(snapshot([["new", 0, 50]]), {}, null, false);
    expect(seen).toEqual({ new: 0 });
  });

  it("reports only targets whose count went up", () => {
    expect(
      newArrivals({ "bot:a": 1, "group:g": 2 }, { "bot:a": 1, "group:g": 3 }),
    ).toEqual(["group:g"]);
    expect(totalUnread({ "bot:a": 1, "group:g": 3 })).toBe(4);
  });

  it("formats titles, previews and targets", () => {
    expect(badgedTitle("Octop Bot", 0)).toBe("Octop Bot");
    expect(badgedTitle("Octop Bot", 150)).toBe("(99+) Octop Bot");
    expect(previewText("**Done**\n\nsee `x`")).toBe("Done see x");
    expect(parseTarget("group:01H")).toEqual({ kind: "group", id: "01H" });
    expect(parseTarget("nope")).toBeNull();
  });
});
