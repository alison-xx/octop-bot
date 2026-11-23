import { describe, expect, it } from "vitest";
import { modelDisplayName, modelVendorLogo } from "./ModelName";

describe("modelDisplayName", () => {
  it.each([
    ["deepseek::deepseek-ai/DeepSeek-V4-Pro", "DeepSeek V4 Pro"],
    ["relay::deepseek-flash", "DeepSeek Flash"],
    ["qianwen::qwen3.8-flash", "Qwen3.8 Flash"],
    ["bigmodel::glm-5.3-flash", "GLM 5.3 Flash"],
    ["kimi-k2.5", "Kimi K2.5"],
  ])("%s → %s", (id, name) => {
    expect(modelDisplayName(id)).toBe(name);
  });

  it("prefers the catalog name when there is one", () => {
    expect(modelDisplayName("x::abc", "Doubao Seed 2")).toBe("Doubao Seed 2");
  });
});

describe("modelVendorLogo", () => {
  it("follows the model's maker, not the serving channel", () => {
    const deepseek = modelVendorLogo("deepseek::deepseek-ai/DeepSeek-V4-Pro");
    expect(deepseek).toBeTruthy();
    expect(modelVendorLogo("relay::deepseek-flash")).toBe(deepseek);
    expect(modelVendorLogo("qianwen::qwen3.8-flash")).not.toBe(deepseek);
    expect(modelVendorLogo("relay::mystery-model")).toBeUndefined();
  });
});
