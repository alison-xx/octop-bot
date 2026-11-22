import assert from "node:assert/strict";
import { test } from "node:test";

import { sanitizeBadgeCount, sanitizeNotification, trayTooltip } from "./attention";

test("notifications keep a short plain title and body for a known target", () => {
  const long = "x".repeat(400);
  const result = sanitizeNotification({ title: " Writer \n", body: long, target: "bot:abc_1" });
  assert.equal(result?.title, "Writer");
  assert.equal(result?.body.length, 280);
  assert.equal(result?.silent, false);
});

test("notifications without a title or with an unknown target are dropped", () => {
  assert.equal(sanitizeNotification({ title: "", target: "bot:a" }), null);
  assert.equal(sanitizeNotification({ title: "Hi", target: "https://evil" }), null);
  assert.equal(sanitizeNotification("Hi"), null);
});

test("badge counts are whole and bounded", () => {
  assert.equal(sanitizeBadgeCount(3.7), 3);
  assert.equal(sanitizeBadgeCount(-2), 0);
  assert.equal(sanitizeBadgeCount(Number.NaN), 0);
  assert.equal(sanitizeBadgeCount("5"), 0);
});

test("the tray tooltip names the unread total", () => {
  assert.equal(trayTooltip("Octop Bot", 0, "en-US"), "Octop Bot");
  assert.equal(trayTooltip("Octop Bot", 4, "en-US"), "Octop Bot · 4 unread");
  assert.equal(trayTooltip("Octop Bot", 4, "zh-CN"), "Octop Bot · 4 条未读");
});
