import assert from "node:assert/strict";
import { test } from "node:test";

import { pickUiLocale } from "./ui-locale-pick";

test("the system's first preferred language wins over the bundle locale", () => {
  assert.equal(pickUiLocale(["zh-Hans-CN", "en-US"], "en"), "zh-Hans-CN");
  assert.equal(pickUiLocale(["en-US"], "zh-CN"), "en-US");
  assert.equal(pickUiLocale([], "zh-CN"), "zh-CN");
  assert.equal(pickUiLocale([""], "en"), "en");
});
