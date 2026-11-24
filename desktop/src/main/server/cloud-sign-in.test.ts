import assert from "node:assert/strict";
import { mkdtempSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  cloudOrigin,
  cloudSignInScript,
  isCloudAccessToken,
  pendingCloudSignInPath,
  savePendingCloudSignIn,
  takePendingCloudSignIn,
} from "./cloud-sign-in";

const token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl";

test("the cloud is bot.lynxce.cn unless a test origin is set", () => {
  assert.equal(cloudOrigin({}), "https://bot.lynxce.cn");
  assert.equal(cloudOrigin({ OCTOP_BOT_CLOUD_ORIGIN: "http://127.0.0.1:18830/" }), "http://127.0.0.1:18830");
  assert.equal(cloudOrigin({ OCTOP_BOT_CLOUD_ORIGIN: "http://example.com" }), "https://bot.lynxce.cn");
});

test("the cloud sign-in is given once, only to its own origin", () => {
  const file = pendingCloudSignInPath(mkdtempSync(join(tmpdir(), "cloud-sign-in-")));
  savePendingCloudSignIn(file, { origin: "https://bot.lynxce.cn", accessToken: token });
  if (process.platform !== "win32") assert.equal(statSync(file).mode & 0o777, 0o600);
  assert.equal(takePendingCloudSignIn(file, "https://bot.lynxce.cn"), token);
  assert.equal(takePendingCloudSignIn(file, "https://bot.lynxce.cn"), null);

  savePendingCloudSignIn(file, { origin: "https://bot.lynxce.cn", accessToken: token });
  assert.equal(takePendingCloudSignIn(file, "https://other.example.com"), null);
  assert.equal(takePendingCloudSignIn(file, "https://bot.lynxce.cn"), null);
});

test("only token-shaped strings are accepted and the page script quotes them", () => {
  assert.equal(isCloudAccessToken(token), true);
  assert.equal(isCloudAccessToken('x"; alert(1); "'), false);
  assert.equal(isCloudAccessToken(42), false);
  assert.equal(
    cloudSignInScript(token),
    `localStorage.setItem("auth_token", "${token}"); location.replace("/octop-bot");`,
  );
});
