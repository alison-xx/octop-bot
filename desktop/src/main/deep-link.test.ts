import assert from "node:assert/strict";
import { test } from "node:test";

import { deepLinkPath, deepLinkPathFromArgv } from "./deep-link";

test("a market link opens that template's import dialog", () => {
  assert.equal(deepLinkPath("octop-bot://market/store-daily-brief"), "/octop-bot/market/store-daily-brief/import");
  assert.equal(deepLinkPath("octop-bot://market/store-daily-brief/"), "/octop-bot/market/store-daily-brief/import");
});

test("anything else is ignored", () => {
  for (const url of [
    "octop-bot://market/",
    "octop-bot://market/a%2Fb",
    "octop-bot://market/Store",
    "octop-bot://market/a/b",
    "octop-bot://settings/x",
    "https://market/store-daily-brief",
    "not a url",
  ])
    assert.equal(deepLinkPath(url), null, url);
});

test("Windows passes the link among the launch arguments", () => {
  assert.equal(
    deepLinkPathFromArgv(["Octop Bot.exe", "--octop-bot", "octop-bot://market/code-reviewer"]),
    "/octop-bot/market/code-reviewer/import",
  );
  assert.equal(deepLinkPathFromArgv(["Octop Bot.exe"]), null);
});
