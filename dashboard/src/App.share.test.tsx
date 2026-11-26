import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { createInstance } from "i18next";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import { fetchPublicShare } from "./api/modules/octopThreads";
import { authApi } from "./api/modules/auth";

vi.mock("./api/modules/octopThreads", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api/modules/octopThreads")>()),
  fetchPublicShare: vi.fn(),
}));

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

it("opens a Bot web share directly for an anonymous reader outside the auth guard", async () => {
  vi.stubEnv("VITE_OCTOP_BOT_WEB", "1");
  const authStatus = vi.spyOn(authApi, "getAuthStatus");
  const id = "a".repeat(24);
  window.history.replaceState(null, "", "/share/" + id);
  vi.mocked(fetchPublicShare).mockResolvedValue({
    title: "Visitor transcript",
    agent_name: "Chief",
    timezone: "UTC",
    ready: true,
    truncated: false,
    messages: [],
  });
  const i18n = createInstance();
  await i18n.init({ lng: "en", resources: { en: { translation: {} } } });
  render(
    <I18nextProvider i18n={i18n}>
      <App />
    </I18nextProvider>,
  );

  expect(
    await screen.findByRole("heading", { name: "Visitor transcript" }),
  ).toBeVisible();
  expect(fetchPublicShare).toHaveBeenCalledWith(id);
  expect(authStatus).not.toHaveBeenCalled();
  expect(window.location.pathname).toBe("/share/" + id);
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});
