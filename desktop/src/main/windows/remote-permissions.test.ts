import assert from "node:assert/strict";
import { test } from "node:test";

import { allowRemotePermission } from "./remote-permissions";

const origin = "https://octop.example.com";

test("a self-hosted page gets the microphone but not the camera", () => {
  const ask = (mediaTypes?: string[]) =>
    allowRemotePermission({ origin, requestingUrl: `${origin}/bot`, permission: "media", mediaTypes });
  assert.equal(ask(["audio"]), true);
  assert.equal(ask(["video"]), false);
  assert.equal(ask(["audio", "video"]), false);
  assert.equal(ask([]), false);
  assert.equal(ask(undefined), false);
});

test("other origins and unlisted permissions are refused", () => {
  assert.equal(
    allowRemotePermission({ origin, requestingUrl: `${origin}/bot`, permission: "notifications" }),
    true,
  );
  assert.equal(
    allowRemotePermission({ origin, requestingUrl: "https://evil.example.com/", permission: "notifications" }),
    false,
  );
  assert.equal(allowRemotePermission({ origin, requestingUrl: `${origin}/bot`, permission: "geolocation" }), false);
  assert.equal(allowRemotePermission({ origin, requestingUrl: "not a url", permission: "notifications" }), false);
});
