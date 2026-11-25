import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { botCloudApi, type CloudAccount } from "../api/modules/botCloud";
import {
  LynxceAccountProvider,
  useLynxceAccount,
} from "../context/LynxceAccountContext";
import { LynxceAccountAvatar } from "./LynxceAccountAvatar";
import { AUTH_TOKEN_KEY } from "../api/request";

vi.mock("../pages/OctopBot/useBotServerInfo", () => ({
  useBotServerInfo: () => ({ edition: "cloud" }),
}));

const photo = "https://cdn.avatars.test/a.jpg?signature=fixture";

describe("Lynxce account portraits", () => {
  it("preserves signed photo URLs and falls back to the current initial on error", () => {
    const { container, rerender } = render(
      <LynxceAccountAvatar name="Alison" url={photo} />,
    );
    const img = container.querySelector("img")!;
    expect(img.getAttribute("src")).toBe(photo);
    expect(img).toHaveAttribute("referrerpolicy", "no-referrer");
    fireEvent.error(img);
    expect(screen.getByText("A")).toBeVisible();
    rerender(<LynxceAccountAvatar name=" 李平 " />);
    expect(screen.getByText("李")).toBeVisible();
    rerender(<LynxceAccountAvatar name="李平" url={photo + "2"} />);
    expect(container.querySelector("img")).toHaveAttribute("src", photo + "2");
  });

  it("shares one cloud read and ignores a late response from the previous account", async () => {
    let resolveOld!: (value: CloudAccount) => void;
    const read = vi
      .spyOn(botCloudApi, "account")
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveOld = resolve;
          }),
      )
      .mockResolvedValueOnce({
        connected: true,
        account_id: "b",
        display_name: "Bo",
        avatar_url: null,
      });
    function Portrait() {
      const account = useLynxceAccount();
      return (
        account && (
          <LynxceAccountAvatar
            name={account.display_name!}
            url={account.avatar_url}
          />
        )
      );
    }
    try {
      const { container } = render(
        <LynxceAccountProvider>
          <Portrait />
          <Portrait />
        </LynxceAccountProvider>,
      );
      expect(read).toHaveBeenCalledTimes(1);
      fireEvent.focus(window);
      await waitFor(() => expect(screen.getAllByText("B")).toHaveLength(2));
      await act(async () =>
        resolveOld({
          connected: true,
          account_id: "a",
          display_name: "Alison",
          avatar_url: photo,
        }),
      );
      expect(container.querySelector("img")).toBeNull();
    } finally {
      read.mockRestore();
    }
  });
  it("ignores another account's late HTTP response including its sliding renewal", async () => {
    vi.stubGlobal("BASE_URL", "");
    const tokenFor = (sub: string, stamp: number) =>
      "x." + btoa(JSON.stringify({ sub, stamp })) + ".x";
    let finish!: (response: Response) => void;
    const fetchAccount = vi.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    function Label() {
      return <span>{useLynxceAccount()?.display_name}</span>;
    }
    try {
      localStorage.setItem(AUTH_TOKEN_KEY, tokenFor("first", 1));
      render(
        <LynxceAccountProvider>
          <Label />
        </LynxceAccountProvider>,
      );
      expect(fetchAccount).toHaveBeenCalledTimes(1);
      localStorage.setItem(AUTH_TOKEN_KEY, tokenFor("second", 1));
      await act(async () =>
        finish(
          new Response(
            JSON.stringify({
              connected: true,
              account_id: "first",
              display_name: "Former person",
              avatar_url: photo,
            }),
            {
              headers: {
                "Content-Type": "application/json",
                "X-Octop-Access-Token": tokenFor("first", 2),
              },
            },
          ),
        ),
      );
      expect(localStorage.getItem(AUTH_TOKEN_KEY)).toBe(tokenFor("second", 1));
      expect(screen.queryByText("Former person")).not.toBeInTheDocument();
      fireEvent.focus(window);
      expect(fetchAccount).toHaveBeenCalledTimes(1);
    } finally {
      localStorage.removeItem(AUTH_TOKEN_KEY);
      fetchAccount.mockRestore();
      vi.unstubAllGlobals();
    }
  });
});
