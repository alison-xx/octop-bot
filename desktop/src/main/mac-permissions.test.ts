import assert from "node:assert/strict";
import { test } from "node:test";

import { isMacPermission, requestMacPermission, type MacPermissionDeps } from "./mac-permissions";

function deps(overrides: Partial<MacPermissionDeps> = {}) {
  const calls: string[] = [];
  const base: MacPermissionDeps = {
    platform: "darwin",
    screenStatus: () => "denied",
    accessibilityTrusted: (prompt) => {
      calls.push(`ax:${prompt}`);
      return false;
    },
    touchScreenCapture: async () => {
      calls.push("capture");
    },
    openSettings: async (url) => {
      calls.push(url);
    },
  };
  return { calls, deps: { ...base, ...overrides } };
}

test("屏幕录制未授权：登记到系统列表，再打开对应设置页", async () => {
  const { calls, deps: d } = deps();
  assert.equal(await requestMacPermission("screen_recording", d), false);
  assert.deepEqual(calls, [
    "capture",
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
  ]);
});

test("辅助功能未授权：带提示询问，再打开对应设置页", async () => {
  const { calls, deps: d } = deps();
  assert.equal(await requestMacPermission("accessibility", d), false);
  assert.deepEqual(calls, [
    "ax:true",
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
  ]);
});

test("已经授权就不打开设置页", async () => {
  const { calls, deps: d } = deps({ screenStatus: () => "granted", accessibilityTrusted: () => true });
  assert.equal(await requestMacPermission("screen_recording", d), true);
  assert.equal(await requestMacPermission("accessibility", d), true);
  assert.deepEqual(calls, []);
});

test("不是 macOS 时什么都不做", async () => {
  const { calls, deps: d } = deps({ platform: "win32" });
  assert.equal(await requestMacPermission("screen_recording", d), true);
  assert.deepEqual(calls, []);
});

test("只接受已知的权限名", () => {
  assert.equal(isMacPermission("screen_recording"), true);
  assert.equal(isMacPermission("camera"), false);
  assert.equal(isMacPermission(undefined), false);
});
