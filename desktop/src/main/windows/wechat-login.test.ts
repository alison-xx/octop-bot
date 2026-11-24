import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { test } from "node:test";

test("WeChat accepts only the configured HTTPS landing page and WeChat QR host", async (t) => {
  const url = "data:text/javascript," + encodeURIComponent("export const BrowserWindow = class {}; export const session = {};");
  const hooks = registerHooks({ resolve(specifier, context, next) { return specifier === "electron" ? { url, shortCircuit: true } : next(specifier, context); } });
  t.after(() => hooks.deregister());
  const { readWechatLanding, validWechatUrls } = await import("./wechat-login");
  const qr = "https://open.weixin.qq.com/connect/qrconnect";
  const redirect = "https://example.test/callback";
  assert.equal(validWechatUrls(qr, redirect), true);
  assert.equal(validWechatUrls("https://open.weixin.qq.com.evil.test/", redirect), false);
  assert.equal(validWechatUrls(qr, "http://example.test/callback"), false);
  assert.deepEqual(readWechatLanding(`${redirect}?code=test-code&state=test-state`, redirect), { ok: true, code: "test-code", state: "test-state" });
  assert.equal(readWechatLanding("https://example.test/callback-other?code=x&state=y", redirect), null);
  assert.deepEqual(readWechatLanding(`${redirect}?error=access_denied`, redirect), { ok: false, reason: "denied" });
});
