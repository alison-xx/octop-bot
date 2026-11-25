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
import WalletBalance from "./WalletBalance";

vi.mock("../../api/request", () => ({ request: vi.fn() }));
vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t, i18n: { language: "en" } }) };
});

const cloud: LynxceWallet = {
  source: "cloud",
  account_id: "user-a",
  connection_id: null,
  credits: 0,
  status: "available",
  recharge_mode: "ticket",
};
const model: LynxceWallet = {
  ...cloud,
  source: "model",
  account_id: null,
  connection_id: "grant-a",
  credits: 1234.5,
};
const official =
  "https://admin.lynxce.cn/recharge?token=eyJjIjoxfQ." + "a".repeat(43);
const modelUrl =
  "https://admin.lynxce.cn/recharge?token=mcrt1." + "b".repeat(64);
const ticket = {
  url: modelUrl,
  expires_at: new Date(Date.now() + 900000).toISOString(),
};
const api = vi.mocked(request);
const button = (key: string) =>
  screen.getByRole("button", { name: "botWallet." + key });
beforeEach(() => {
  api.mockReset();
  vi.spyOn(window, "open").mockClear().mockReturnValue(null);
});

it("distinguishes no balance yet, zero, stale data and the next focus refresh", async () => {
  let resolve!: (value: LynxceWallet) => void;
  api.mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  render(<WalletBalance source="cloud" accountId="user-a" />);
  expect(screen.queryByText("0")).toBeNull();
  expect(
    screen.queryByRole("button", { name: "botWallet.recharge" }),
  ).toBeNull();
  await act(async () => resolve(cloud));
  expect(screen.getByText("0")).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith(
    "/octop-bot/wallet?source=cloud",
    expect.objectContaining({ cache: "no-store" }),
  );
  api.mockRejectedValueOnce(new Error("offline"));
  fireEvent.click(button("refresh"));
  expect(await screen.findByRole("alert")).toHaveTextContent("botWallet.stale");
  expect(screen.getByText("0")).toBeInTheDocument();
  api.mockResolvedValueOnce({ ...cloud, credits: 0.00025 });
  fireEvent.focus(window);
  expect(await screen.findByText("0.00025")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(window.open).not.toHaveBeenCalled();
});

it.each([cloud, model])(
  "pins a $source checkout to the balance currently on screen",
  async (wallet) => {
    const url = wallet.source === "cloud" ? official : modelUrl;
    api.mockResolvedValueOnce(wallet).mockResolvedValueOnce({ ...ticket, url });
    render(
      <WalletBalance
        source={wallet.source}
        accountId={wallet.account_id || undefined}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "botWallet.recharge" }),
    );
    await waitFor(() =>
      expect(window.open).toHaveBeenCalledExactlyOnceWith(
        url,
        "_blank",
        "noopener,noreferrer",
      ),
    );
    const expectedBody =
      wallet.source === "model"
        ? {
            source: "model",
            expected_account_id: null,
            expected_connection_id: "grant-a",
          }
        : { source: "cloud", expected_account_id: "user-a" };
    expect(api.mock.calls[1][0]).toBe("/octop-bot/wallet/recharge");
    expect(JSON.parse(String(api.mock.calls[1][1]?.body))).toEqual({
      ...expectedBody,
      from: "web",
    });
  },
);

it.each([
  { url: "https://admin.lynxce.cn/recharge" },
  { url: "https://evil.test/recharge?token=abc.def" },
  { url: official },
  { url: modelUrl + "&next=foo" },
  { url: modelUrl + "#fragment" },
  { url: "https://admin.lynxce.cn/recharge?token=old.bearer.jwt" },
  { expires_at: "2000-01-01T00:00:00Z" },
])(
  "rejects an invalid checkout response and lets the user retry",
  async (bad) => {
    api
      .mockResolvedValueOnce(model)
      .mockResolvedValueOnce({ ...ticket, ...bad })
      .mockResolvedValueOnce(ticket);
    render(<WalletBalance source="model" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "botWallet.recharge" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "botWallet.openFailed",
    );
    expect(window.open).not.toHaveBeenCalled();
    fireEvent.click(button("recharge"));
    await waitFor(() => expect(window.open).toHaveBeenCalledOnce());
  },
);

it("keeps encrypted model tickets out of a cloud checkout", async () => {
  api.mockResolvedValueOnce(cloud).mockResolvedValueOnce({
    ...ticket,
    url: "https://admin.lynxce.cn/recharge?token=mcrt1." + "s".repeat(43),
  });
  render(<WalletBalance source="cloud" accountId="user-a" />);
  fireEvent.click(
    await screen.findByRole("button", { name: "botWallet.recharge" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "botWallet.openFailed",
  );
  expect(window.open).not.toHaveBeenCalled();
});

it("drops a pending checkout when a balance refresh discovers a changed connection", async () => {
  let resolve!: (result: typeof ticket) => void;
  api
    .mockResolvedValueOnce(model)
    .mockImplementationOnce(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    )
    .mockResolvedValueOnce({ ...model, connection_id: "new", credits: 12 });
  render(<WalletBalance source="model" />);
  fireEvent.click(
    await screen.findByRole("button", { name: "botWallet.recharge" }),
  );
  fireEvent.focus(window);
  await screen.findByText("12");
  await act(async () => resolve(ticket));
  expect(window.open).not.toHaveBeenCalled();
});

it("clears credits when a cloud session changes and recovers on manual refresh", async () => {
  api
    .mockResolvedValueOnce(cloud)
    .mockResolvedValueOnce({ ...cloud, account_id: "other", credits: 199 })
    .mockResolvedValueOnce(cloud);
  render(<WalletBalance source="cloud" accountId="user-a" />);
  await screen.findByText("0");
  fireEvent.focus(window);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "botWallet.loadFailed",
  );
  expect(screen.queryByText("199")).toBeNull();
  expect(screen.queryByText("0")).toBeNull();
  fireEvent.click(button("refresh"));
  expect(await screen.findByText("0")).toBeInTheDocument();
});

it("handles an initial network failure without showing zero or enabling checkout", async () => {
  api.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(model);
  render(<WalletBalance source="model" />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "botWallet.loadFailed",
  );
  expect(
    screen.queryByRole("button", { name: "botWallet.recharge" }),
  ).toBeNull();
  fireEvent.click(button("refresh"));
  expect(await screen.findByText("1,234.5")).toBeInTheDocument();
});

it.each([
  [{ botOnly: true, supportsRechargeReturn: true }, "desktop"],
  [{ botOnly: true }, undefined],
])(
  "only advertises a desktop return for capable shells",
  async (bridge, expected) => {
    vi.stubGlobal("octopDesktop", bridge);
    try {
      const { lynxceWalletApi } = await import(
        "../../api/modules/lynxceWallet"
      );
      await lynxceWalletApi.recharge(cloud);
      expect(JSON.parse(String(api.mock.calls.at(-1)?.[1]?.body)).from).toBe(
        expected,
      );
    } finally {
      vi.unstubAllGlobals();
    }
  },
);
