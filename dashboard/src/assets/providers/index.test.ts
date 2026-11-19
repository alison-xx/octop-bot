import { describe, expect, it } from "vitest";
import yuanbaoIcon from "../channels/yuanbao.svg";
import iflytekIcon from "./iflytek.svg";
import magpieIcon from "./magpie.svg";
import deepseekIcon from "./deepseek.png";
import genericIcon from "./custom-provider.svg";
import { getProviderLogo } from "./index";

describe("getProviderLogo", () => {
  it("uses the generic service icon on Bot screens and retains the regular provider catalog", () => {
    const url = window.location.href;
    try {
      window.history.replaceState({}, "", "/octop-bot/settings");
      expect(getProviderLogo("deepseek")).toBe(genericIcon);
      expect(getProviderLogo("deepseek-chat")).toBe(genericIcon);
      window.history.replaceState({}, "", "/settings");
      expect(getProviderLogo("deepseek")).toBe(deepseekIcon);
    } finally {
      window.history.replaceState({}, "", url);
    }
  });
  it("uses the Yuanbao product mark shared with the channel", () => {
    expect(getProviderLogo("yuanbao")).toBe(yuanbaoIcon);
    expect(getProviderLogo("yuanbao-search")).toBe(yuanbaoIcon);
  });

  it("resolves logos for iflytek and magpie", () => {
    expect(getProviderLogo("iflytek")).toBe(iflytekIcon);
    expect(getProviderLogo("iflytek-astron")).toBe(iflytekIcon);
    expect(getProviderLogo("iflytek-astron-token-plan")).toBe(iflytekIcon);
    expect(getProviderLogo("magpie")).toBe(magpieIcon);
  });
});
