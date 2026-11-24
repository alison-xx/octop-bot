import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  botProfileName,
  isLoopbackHost,
  normalizeServerAddress,
  probeServer,
  remoteFailurePrompt,
  ServerChoiceStore,
} from "./server-choice";

test("addresses become origins and public hosts need HTTPS", () => {
  assert.deepEqual(normalizeServerAddress(" octop.example.com/chat?x=1 "), { ok: true, origin: "https://octop.example.com" });
  assert.deepEqual(normalizeServerAddress("https://octop.example.com:8443"), { ok: true, origin: "https://octop.example.com:8443" });
  assert.deepEqual(normalizeServerAddress("http://192.168.1.20:18790"), { ok: true, origin: "http://192.168.1.20:18790" });
  assert.deepEqual(normalizeServerAddress("http://nas.local:8080"), { ok: true, origin: "http://nas.local:8080" });
  assert.deepEqual(normalizeServerAddress("http://octop.example.com"), { ok: false, reason: "insecure" });
  assert.deepEqual(normalizeServerAddress("http://8.8.8.8"), { ok: false, reason: "insecure" });
  assert.deepEqual(normalizeServerAddress("ftp://octop.example.com"), { ok: false, reason: "invalid" });
  assert.deepEqual(normalizeServerAddress("https://user:pw@octop.example.com"), { ok: false, reason: "invalid" });
  assert.deepEqual(normalizeServerAddress("   "), { ok: false, reason: "empty" });
});

test("the store keeps valid origins, newest first, and drops tampered ones", () => {
  const dir = mkdtempSync(join(tmpdir(), "server-choice-"));
  const store = new ServerChoiceStore(join(dir, "server.json"));
  assert.deepEqual(store.load(), { current: null, recent: [] });
  store.select("https://a.example.com");
  store.select("https://b.example.com");
  assert.deepEqual(store.select("https://a.example.com"), {
    current: "https://a.example.com",
    recent: ["https://a.example.com", "https://b.example.com"],
  });
  assert.deepEqual(store.select(null).recent, ["https://a.example.com", "https://b.example.com"]);
  assert.deepEqual(store.forget("https://a.example.com"), { current: null, recent: ["https://b.example.com"] });

  writeFileSync(join(dir, "server.json"), JSON.stringify({ current: "http://evil.example.com", recent: ["javascript:alert(1)", "https://ok.example.com/path"] }));
  assert.deepEqual(store.load(), { current: null, recent: [] });
});

test("probing accepts new and old Octop servers only", async () => {
  const reply = (routes: Record<string, unknown>) => async (url: string) => {
    const path = new URL(url).pathname;
    if (!(path in routes)) return { ok: false, status: 404, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => routes[path] };
  };
  assert.deepEqual(await probeServer("https://new.example.com", reply({ "/api/octop-bot/server-info": { product: "octop-bot" } })), { ok: true });
  assert.deepEqual(await probeServer("https://old.example.com", reply({ "/api/setup/status": { setup_required: false } })), { ok: true });
  assert.deepEqual(await probeServer("https://blog.example.com", reply({})), { ok: false, reason: "not-octop" });
  assert.deepEqual(await probeServer("https://api.example.com", reply({ "/api/setup/status": { status: "ok" } })), {
    ok: false,
    reason: "not-octop",
  });
  const offline = async () => {
    throw new Error("ECONNREFUSED");
  };
  assert.deepEqual(await probeServer("https://down.example.com", offline), { ok: false, reason: "unreachable" });
});

test("a loopback server left by a development run is forgotten, others are kept", () => {
  const dir = mkdtempSync(join(tmpdir(), "server-choice-"));
  const file = join(dir, "server.json");
  const store = new ServerChoiceStore(file);
  writeFileSync(
    file,
    JSON.stringify({
      current: "http://127.0.0.1:18830",
      recent: ["http://127.0.0.1:18830", "http://localhost:18790", "https://octop.example.com", "http://192.168.1.20:18790"],
    }),
  );
  assert.deepEqual(store.dropLoopback(), {
    current: null,
    recent: ["https://octop.example.com", "http://192.168.1.20:18790"],
  });
  assert.deepEqual(store.load(), { current: null, recent: ["https://octop.example.com", "http://192.168.1.20:18790"] });

  store.select("https://octop.example.com");
  assert.equal(store.dropLoopback().current, "https://octop.example.com");
});

test("loopback hosts are this computer only", () => {
  for (const host of ["localhost", "127.0.0.1", "127.1.2.3", "[::1]", "::1", "app.localhost"]) assert.equal(isLoopbackHost(host), true, host);
  for (const host of ["192.168.1.20", "10.0.0.1", "nas.local", "octop.example.com", "127.0.0.1.example.com"]) {
    assert.equal(isLoopbackHost(host), false, host);
  }
});

test("development runs keep their own profile", () => {
  assert.equal(botProfileName("Octop Bot", true), "Octop Bot");
  assert.equal(botProfileName("Octop Bot", false), "Octop Bot Dev");
});

test("the unreachable-server prompt speaks the user's language and defaults to this computer", () => {
  const zh = remoteFailurePrompt("https://octop.example.com", "ERR_FAILED", true);
  assert.equal(zh.message, "上次连接的服务器 octop.example.com 暂时连不上");
  assert.deepEqual(zh.buttons, ["改用本机", "换一个服务器…", "重试"]);
  assert.equal(zh.actions[zh.defaultId], "local");
  assert.equal(zh.actions[zh.cancelId], "retry");
  assert.match(zh.detail, /ERR_FAILED/);
  const en = remoteFailurePrompt("https://octop.example.com", "ERR_FAILED", false);
  assert.deepEqual(en.buttons, ["Use This Computer", "Another Server…", "Retry"]);
  assert.equal(en.actions[en.defaultId], "local");
});
