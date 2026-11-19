import assert from "node:assert/strict";
import type { EventEmitter } from "node:events";
import { registerHooks } from "node:module";
import { test } from "node:test";
import { IPC_CHANNELS } from "../shared/ipc-contract";
import { BOT_CLIENT_FLAG } from "../shared/product";
import type { OctopDesktopBridge } from "./index";

test("preload publishes the product synchronously and preserves Settings until the SPA subscribes", async (t) => {
  const stub = `
    import { EventEmitter } from 'node:events';
    export const ipcRenderer = new EventEmitter();
    export const globals = new Map();
    export const contextBridge = { exposeInMainWorld: (key, value) => globals.set(key, value) };
  `;
  const url = "data:text/javascript," + encodeURIComponent(stub);
  const hooks = registerHooks({
    resolve(specifier, context, next) {
      return specifier === "electron" ? { url, shortCircuit: true } : next(specifier, context);
    },
  });
  t.after(() => hooks.deregister());

  const { ipcRenderer, globals } = await import(url) as {
    ipcRenderer: EventEmitter;
    globals: Map<string, OctopDesktopBridge>;
  };
  await import(new URL("./index.ts?full", import.meta.url).href);
  assert.equal(globals.get("octopDesktop")?.botOnly, false);
  assert.equal(ipcRenderer.listenerCount(IPC_CHANNELS.openBotSettings), 0);

  process.argv.push(BOT_CLIENT_FLAG);
  t.after(() => { process.argv.pop(); });
  await import(new URL("./index.ts?bot", import.meta.url).href);
  const bot = globals.get("octopDesktop");
  assert.ok(bot?.botOnly);
  const request = () => ipcRenderer.emit(IPC_CHANNELS.openBotSettings);
  request();
  let count = 0;
  const unsubscribe = bot.onOpenBotSettings(() => { count++; });
  assert.equal(count, 1);
  request();
  assert.equal(count, 2);
  unsubscribe();
  request();
  assert.equal(count, 2);
  bot.onOpenBotSettings(() => { count++; });
  assert.equal(count, 3);
});
