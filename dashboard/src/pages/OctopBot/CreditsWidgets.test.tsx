import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { request } from "../../api/request";
import type { LynxceWallet } from "../../api/modules/lynxceWallet";
import {
  CreditsPanel,
  CreditsRequiredCard,
  LowCreditsBanner,
} from "./CreditsWidgets";
import {
  formatCredits,
  resetCredits,
  RECHARGE_RETURN,
  rememberCheckout,
  reportCheckoutBalance,
} from "./useLynxceCredits";
import { message } from "@/utils/antdMessage";

vi.mock("@/utils/antdMessage", () => ({
  message: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("../../api/request", () => ({ request: vi.fn() }));
vi.mock("react-i18next", () => {
  const t = (key: string, vars?: Record<string, string>) =>
    vars?.value ? `${key}:${vars.value}` : key;
  return { useTranslation: () => ({ t, i18n: { language: "en" } }) };
});

const wallet = (credits: number): LynxceWallet => ({
  source: "cloud",
  account_id: "user-a",
  connection_id: null,
  credits,
  status: "available",
  recharge_mode: "ticket",
});
const checkout = {
  url: "https://admin.lynxce.cn/recharge?token=eyJjIjoxfQ." + "a".repeat(43),
  expires_at: new Date(Date.now() + 900000).toISOString(),
};

let balance = 0;
beforeEach(() => {
  resetCredits();
  localStorage.clear();
  balance = 0;
  vi.mocked(request).mockReset();
  vi.mocked(request).mockImplementation(async (path: string) => {
    if (path === "/octop-bot/server-info") return { edition: "cloud" };
    if (path.startsWith("/octop-bot/wallet?")) return wallet(balance);
    if (path === "/octop-bot/wallet/recharge") return checkout;
    throw new Error("unexpected " + path);
  });
});

it("formats large balances without cents and small ones with two decimals", () => {
  expect(formatCredits(4454029.04, "en")).toBe("4,454,029");
  expect(formatCredits(12.5, "en")).toBe("12.50");
  expect(formatCredits(1280, "en")).toBe("1,280");
});

it("turns an out-of-credit reply into recharge, then continue once credits arrive", async () => {
  const tab = { opener: {}, location: { href: "" }, close: vi.fn() };
  const open = vi
    .spyOn(window, "open")
    .mockReturnValue(tab as unknown as Window);
  const onContinue = vi.fn();
  render(<CreditsRequiredCard onContinue={onContinue} />);
  expect(screen.getByText("botCredits.outTitle")).toBeInTheDocument();
  expect(
    await screen.findByText("botCredits.balanceNow:0"),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "botCredits.recharge" }));
  await waitFor(() => expect(tab.location.href).toBe(checkout.url));
  expect(tab.opener).toBeNull();
  expect(request).toHaveBeenCalledWith(
    "/octop-bot/wallet/recharge",
    expect.objectContaining({ method: "POST" }),
  );

  // Back from checkout: focusing the window reloads the balance.
  balance = 500;
  await act(async () => {
    window.dispatchEvent(new Event("focus"));
  });
  expect(await screen.findByText("botCredits.outReady")).toBeInTheDocument();
  expect(screen.getByText("botCredits.readyTitle")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "botCredits.recharge" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "botCredits.continue" }));
  expect(onContinue).toHaveBeenCalledOnce();
  open.mockRestore();
});

it("warns below 100 credits until dismissed, and forgets the dismissal once topped up", async () => {
  balance = 42;
  const { unmount } = render(<LowCreditsBanner />);
  expect(
    await screen.findByText("botCredits.lowBanner:42"),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "botCredits.dismiss" }));
  expect(screen.queryByText(/botCredits.lowBanner/)).not.toBeInTheDocument();
  unmount();

  resetCredits();
  render(<LowCreditsBanner />);
  await waitFor(() => expect(request).toHaveBeenCalled());
  expect(screen.queryByText(/botCredits.lowBanner/)).not.toBeInTheDocument();

  balance = 5000;
  await act(async () => {
    window.dispatchEvent(new Event("focus"));
  });
  balance = 10;
  await act(async () => {
    window.dispatchEvent(new Event("focus"));
  });
  expect(
    await screen.findByText("botCredits.lowBanner:10"),
  ).toBeInTheDocument();
});

it("tells a used-up daily limit apart from an empty wallet: no top-up, just continue later", async () => {
  balance = 5000;
  const onContinue = vi.fn();
  render(<CreditsRequiredCard kind="limit" onContinue={onContinue} />);
  expect(screen.getByText("botCredits.limitTitle")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "botCredits.recharge" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("link")).toHaveAttribute(
    "href",
    "https://admin.lynxce.cn",
  );
  fireEvent.click(screen.getByRole("button", { name: "botCredits.continue" }));
  expect(onContinue).toHaveBeenCalledOnce();
});

it("shows the balance beside the month's usage, by Bot or by model", async () => {
  balance = 1280;
  const usage = (rows: [string, number][]) => ({
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 1500,
    model_calls: 7,
    turns: 3,
    buckets: rows.map(([label, total_tokens]) => ({
      key: label,
      label,
      total_tokens,
    })),
  });
  vi.mocked(request).mockImplementation(async (path: string) => {
    if (path === "/octop-bot/server-info") return { edition: "cloud" };
    if (path.startsWith("/octop-bot/wallet?")) return wallet(balance);
    if (path.includes("granularity=by_agent"))
      return usage([
        ["Chief", 500],
        ["Writer", 1000],
        ["Idle", 0],
      ]);
    if (path.includes("granularity=by_model"))
      return usage([["deepseek-v3", 1500]]);
    throw new Error("unexpected " + path);
  });
  render(<CreditsPanel />);
  expect(await screen.findByText("1,280")).toBeInTheDocument();
  const rows = await screen.findByRole("list", {
    name: "botCredits.usageTitle",
  });
  // Biggest first; Bots that used nothing are left out.
  expect(
    [...rows.querySelectorAll("li > span:first-child")].map(
      (el) => el.textContent,
    ),
  ).toEqual(["Writer", "Chief"]);
  fireEvent.click(screen.getByRole("button", { name: "botCredits.byModel" }));
  expect(
    screen.getByRole("button", { name: "botCredits.byModel" }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(rows).toHaveTextContent("deepseek-v3");
  expect(rows).not.toHaveTextContent("Writer");
  expect(
    screen.getByRole("link", { name: "botCredits.accountCentre" }),
  ).toHaveAttribute("href", "https://admin.lynxce.cn");
});

it("refreshes a focused wallet on a desktop checkout callback", async () => {
  render(<CreditsPanel />);
  await screen.findByText("0", { selector: "strong" });
  balance = 240;
  await act(async () => {
    window.dispatchEvent(new Event(RECHARGE_RETURN));
  });
  expect(
    await screen.findByText("240", { selector: "strong" }),
  ).toBeInTheDocument();
});

it("checks the wallet and never reports a payment from the callback alone", () => {
  const success = vi.mocked(message.success);
  success.mockClear();
  rememberCheckout(wallet(100), checkout.expires_at);
  reportCheckoutBalance({ ...wallet(500), account_id: "different" });
  reportCheckoutBalance(wallet(100));
  expect(success).not.toHaveBeenCalled();
  reportCheckoutBalance(wallet(200));
  reportCheckoutBalance(wallet(200));
  expect(success).toHaveBeenCalledTimes(1);
});
