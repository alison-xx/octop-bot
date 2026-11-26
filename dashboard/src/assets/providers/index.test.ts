import { describe, expect, it } from "vitest";
import yuanbaoIcon from "../channels/yuanbao.svg";
import iflytekIcon from "./iflytek.svg";
import magpieIcon from "./magpie.svg";
import lynxceIcon from "./lynxce.png";
import deepseekIcon from "./deepseek.png";
import { getProviderLogo } from "./index";

describe("getProviderLogo", () => {
  it("shows the DeepSeek whale in Bot settings and the provider catalog", () => {
    const url = window.location.href;
    try {
      window.history.replaceState({}, "", "/octop-bot/settings");
      expect(getProviderLogo("deepseek")).toBe(deepseekIcon);
      expect(getProviderLogo("deepseek-chat")).toBe(deepseekIcon);
      window.history.replaceState({}, "", "/settings");
      expect(getProviderLogo("deepseek")).toBe(deepseekIcon);
    } finally {
      window.history.replaceState({}, "", url);
    }
  });
  it("shows the Lynxce mark for the Lynxce API key preset", () => {
    expect(getProviderLogo("lynxce")).toBe(lynxceIcon);
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
