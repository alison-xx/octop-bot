import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import { normalizeServerAddress, probeServer, ServerChoiceStore } from "./server-choice";

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
  const offline = async () => {
    throw new Error("ECONNREFUSED");
  };
  assert.deepEqual(await probeServer("https://down.example.com", offline), { ok: false, reason: "unreachable" });
});
