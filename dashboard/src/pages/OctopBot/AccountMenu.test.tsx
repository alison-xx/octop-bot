import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import AccountMenu from "./AccountMenu";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ username: "member", display_name: "Member" }),
}));
vi.mock("./useLynxceCredits", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./useLynxceCredits")>()),
  useLynxceCredits: () => ({ status: "ready", wallet: { credits: 120 } }),
}));

it("opens the official pricing page from the account menu recharge action", async () => {
  render(
    <MemoryRouter>
      <AccountMenu />
    </MemoryRouter>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: /botClient.menu.settings/ }),
  );
  const recharge = await screen.findByRole("link", {
    name: "botCredits.recharge",
  });
  expect(recharge).toHaveAttribute(
    "href",
    "https://octop-bot.lynxce.cn/pricing.html",
  );
  expect(recharge).toHaveAttribute("target", "_blank");
});
