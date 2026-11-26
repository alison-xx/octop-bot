import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { lynxceWalletApi } from "../../api/modules/lynxceWallet";
import AccountMenu from "./AccountMenu";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ username: "member", display_name: "Member" }),
}));
vi.mock("./useLynxceCredits", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./useLynxceCredits")>()),
  useLynxceCredits: () => ({
    status: "ready",
    wallet: { credits: 120, source: "cloud", account_id: "member-id" },
  }),
}));

it.each([
  ["botCredits.recharge", "recharge", "pricing.html", "ticket", "button"],
  ["botCredits.menu", "recharge", "pricing.html", "ticket", "menuitem"],
  [
    "botClient.menu.accountCenter",
    "account",
    "account.html",
    "code",
    "menuitem",
  ],
])(
  "opens %s for the displayed account",
  async (name, scope, page, param, role) => {
    const code = "a".repeat(43);
    const replace = vi.fn();
    const tab = { opener: window, location: { replace } };
    const popup = vi
      .spyOn(window, "open")
      .mockReturnValue(tab as unknown as Window);
    const issue = vi
      .spyOn(lynxceWalletApi, "websiteCode")
      .mockResolvedValue({ code });
    try {
      render(
        <MemoryRouter>
          <AccountMenu />
        </MemoryRouter>,
      );
      fireEvent.click(
        screen.getByRole("button", { name: /botClient.menu.settings/ }),
      );
      fireEvent.click(
        await screen.findByRole(role, { name: new RegExp(name) }),
      );
      await vi.waitFor(() =>
        expect(replace).toHaveBeenCalledWith(
          "https://octop-bot.lynxce.cn/" +
            page +
            "?from=web#" +
            param +
            "=" +
            code,
        ),
      );
      expect(issue).toHaveBeenCalledWith(scope, "member-id");
      expect(tab.opener).toBeNull();
    } finally {
      popup.mockRestore();
      issue.mockRestore();
    }
  },
);

it("opens the account page in the desktop system browser after the ticket is issued", async () => {
  const agent = vi
    .spyOn(navigator, "userAgent", "get")
    .mockReturnValue("Electron/39");
  const popup = vi.spyOn(window, "open").mockReturnValue(null);
  const code = "b".repeat(43);
  const issue = vi
    .spyOn(lynxceWalletApi, "websiteCode")
    .mockResolvedValue({ code });
  try {
    render(
      <MemoryRouter>
        <AccountMenu />
      </MemoryRouter>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /botClient.menu.settings/ }),
    );
    fireEvent.click(
      await screen.findByRole("menuitem", {
        name: /botClient.menu.accountCenter/,
      }),
    );
    await vi.waitFor(() =>
      expect(popup).toHaveBeenCalledWith(
        "https://octop-bot.lynxce.cn/account.html?from=desktop#code=" + code,
        "_blank",
        "noopener,noreferrer",
      ),
    );
    expect(popup).toHaveBeenCalledTimes(1);
    expect(issue).toHaveBeenCalledWith("account", "member-id");
  } finally {
    popup.mockRestore();
    issue.mockRestore();
    agent.mockRestore();
  }
});
