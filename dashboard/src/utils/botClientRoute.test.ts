import { afterEach, describe, expect, it, vi } from "vitest";
import {
  botCapabilityLink,
  botClientDestination,
  loginDestination,
  rememberBotLoginPath,
} from "./botClientRoute";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  sessionStorage.clear();
});
describe("standalone Bot navigation", () => {
  it.each([
    ["/chat/expert/previous", "/octop-bot/bots/expert/previous"],
    ["/octop-bot/groups/team", "/octop-bot/groups/team"],
    ["/octop-bot/settings", "/octop-bot/settings"],
    ["/octop-bot/cloud", "/octop-bot/cloud"],
    ["/octop-bot/guide", "/octop-bot/guide"],
    ["/octop-bot/market", "/octop-bot/market"],
    [
      "/octop-bot/market/store-daily-brief",
      "/octop-bot/market/store-daily-brief",
    ],
    [
      "/octop-bot/market/store-daily-brief/import",
      "/octop-bot/market/store-daily-brief/import",
    ],
    ["/octop-bot/market/store-daily-brief/delete", "/octop-bot"],
    ["/admin/users", "/octop-bot"],
    ["/invite", "/octop-bot"],
    ["//external.test", "/octop-bot"],
    ["/octop-bot/settings/admin", "/octop-bot"],
    ["/octop-bot/capabilities", "/octop-bot/capabilities"],
    ["/octop-bot/capabilities/acp", "/octop-bot/capabilities/acp"],
    ["/octop-bot/capabilities/unknown", "/octop-bot"],
    ["/connectors", "/octop-bot/capabilities/connectors"],
    ["/skills", "/octop-bot/capabilities/skills"],
    ["/personalization/memory", "/octop-bot/capabilities/memory"],
    ["/channels/", "/octop-bot/capabilities/channels"],
    ["/plugins", "/octop-bot/capabilities/plugins"],
    ["/cron-jobs", "/octop-bot/capabilities/tasks"],
    ["/admin/models", "/octop-bot/settings"],
    ["/personalization/tools", "/octop-bot"],
  ])("maps %s into the chat client", (url, expected) => {
    expect(botClientDestination(url)).toBe(expected);
  });
  it("opens embedded chat links on the scoped Bot", () => {
    expect(botCapabilityLink("/chat", "team lead")).toBe(
      "/octop-bot/bots/team%20lead",
    );
    expect(botCapabilityLink("/chat/", null)).toBe("/octop-bot");
    expect(botCapabilityLink("/chat/expert/t1", "writer")).toBe(
      "/octop-bot/bots/expert/t1",
    );
    expect(botCapabilityLink("/knowledge-bases", "writer")).toBe(
      "/octop-bot/capabilities/knowledge",
    );
  });
  it("returns to the designated thread once after authentication", () => {
    vi.stubGlobal("octopDesktop", { botOnly: true });
    rememberBotLoginPath("/chat/chief/previous");
    expect(loginDestination("/chat", false)).toBe(
      "/octop-bot/bots/chief/previous",
    );
    expect(loginDestination()).toBe("/octop-bot/bots/chief/previous");
    expect(loginDestination()).toBe("/octop-bot");
  });
  it("restores the NAS chat after password login without an Electron bridge", () => {
    vi.stubEnv("VITE_OCTOP_BOT_WEB", "1");
    rememberBotLoginPath("/octop-bot/groups/project");
    expect(loginDestination()).toBe("/octop-bot/groups/project");
    expect(loginDestination()).toBe("/octop-bot");
  });
  it("preserves normal dashboard login destinations", () => {
    rememberBotLoginPath("/octop-bot/settings");
    expect(loginDestination("/tasks")).toBe("/tasks");
  });
});
