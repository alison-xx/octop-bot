import { afterEach, describe, expect, it, vi } from "vitest";
import {
  botClientDestination,
  loginDestination,
  rememberBotLoginPath,
} from "./botClientRoute";

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});
describe("standalone Bot navigation", () => {
  it.each([
    ["/chat/expert/previous", "/octop-bot/bots/expert/previous"],
    ["/octop-bot/groups/team", "/octop-bot/groups/team"],
    ["/octop-bot/settings", "/octop-bot/settings"],
    ["/octop-bot/cloud", "/octop-bot/cloud"],
    ["/octop-bot/guide", "/octop-bot/guide"],
    ["/admin/users", "/octop-bot"],
    ["/invite", "/octop-bot"],
    ["//external.test", "/octop-bot"],
    ["/octop-bot/settings/admin", "/octop-bot"],
  ])("maps %s into the chat client", (url, expected) => {
    expect(botClientDestination(url)).toBe(expected);
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
  it("preserves normal dashboard login destinations", () => {
    rememberBotLoginPath("/octop-bot/settings");
    expect(loginDestination("/tasks")).toBe("/tasks");
  });
});
