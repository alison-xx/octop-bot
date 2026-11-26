import assert from "node:assert/strict";
import { test } from "node:test";
import { botDocumentPath, isBotProduct } from "./product";

test("select Bot from its development flag or native package identity", () => {
  assert.equal(isBotProduct(["electron", ".", "--octop-bot"], "Electron", undefined), true);
  assert.equal(isBotProduct([], "Octop Bot", {}), true);
  assert.equal(isBotProduct([], "octop-bot", undefined), true);
  assert.equal(isBotProduct([], "Octop Desktop", { octopBotClient: true }), true);
  assert.equal(isBotProduct(["--octop-bot-test"], "Octop", { octopBotClient: "true" }), false);
});

test("Bot document navigation admits its workspace, login, setup and legacy thread links", () => {
  for (const path of ["/octop-bot", "/octop-bot/groups/group", "/octop-bot/settings", "/octop-bot/capabilities/connectors", "/chat",
    "/chat/bot/thread", "/login", "/login/oidc/complete", "/setup", "/share/example-token"]) {
    assert.equal(botDocumentPath(path), true, path);
  }
  for (const path of ["/", "/admin", "/octop-bot-fake", "/chat-admin", "/login/profile", "/share", "/share/a/b"]) {
    assert.equal(botDocumentPath(path), false, path);
  }
});
