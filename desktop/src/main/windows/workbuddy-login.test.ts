import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { test } from "node:test";

const code = "wb-handoff.eyJ1c2VySWQiOiJ3YiIsImV4cCI6MX0." + "s".repeat(43);

test("only Lynxce's landing page yields a WorkBuddy hand-off code", async (t) => {
  const url = "data:text/javascript," + encodeURIComponent("export const BrowserWindow = class {}; export const session = {};");
  const hooks = registerHooks({
    resolve(specifier, context, next) {
      return specifier === "electron" ? { url, shortCircuit: true } : next(specifier, context);
    },
  });
  t.after(() => hooks.deregister());
  const { readWorkbuddyLanding, WORKBUDDY_START_URL } = await import("./workbuddy-login");

  assert.ok(WORKBUDDY_START_URL.startsWith("https://api.lynxce.cn/api/oauth/workbuddy/start?site=agent&"));
  assert.deepEqual(readWorkbuddyLanding(`https://web.lynxce.cn/oauth/workbuddy?code=${code}&next=%2F`), { ok: true, code });
  assert.deepEqual(readWorkbuddyLanding(`https://agent.lynxce.cn/oauth/workbuddy/?code=${code}`), { ok: true, code });
  assert.deepEqual(readWorkbuddyLanding("https://web.lynxce.cn/oauth/workbuddy?error=authorize_denied"), {
    ok: false,
    reason: "denied",
  });
  assert.deepEqual(readWorkbuddyLanding("https://web.lynxce.cn/oauth/workbuddy?code=not-a-code"), {
    ok: false,
    reason: "failed",
  });
  for (const other of [
    `http://web.lynxce.cn/oauth/workbuddy?code=${code}`,
    `https://web.lynxce.cn.example.com/oauth/workbuddy?code=${code}`,
    `https://web.lynxce.cn/oauth/workbuddy-other?code=${code}`,
    `https://www.workbuddy.cn/openapi/v2/authorize?code=${code}`,
    "https://web.lynxce.cn/",
    "not a url",
  ]) {
    assert.equal(readWorkbuddyLanding(other), null, other);
  }
});
