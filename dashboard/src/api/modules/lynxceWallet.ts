import { request } from "../request";

export type WalletSource = "model" | "cloud";

export interface LynxceWallet {
  source: WalletSource;
  account_id: string | null;
  connection_id: string | null;
  credits: number;
  status: "available";
  recharge_mode: "ticket";
}

const path = "/octop-bot/wallet";
export const lynxceWalletApi = {
  balance: (source: WalletSource, signal?: AbortSignal) =>
    request<LynxceWallet>(path + "?source=" + source, {
      signal,
      cache: "no-store",
    }),
  recharge: (wallet: LynxceWallet, signal?: AbortSignal) =>
    request<{ url: string; expires_at: string }>(path + "/recharge", {
      method: "POST",
      body: JSON.stringify({
        source: wallet.source,
        expected_account_id: wallet.account_id,
        ...(wallet.source === "model" && {
          expected_connection_id: wallet.connection_id,
        }),
      }),
      signal,
    }),
};
