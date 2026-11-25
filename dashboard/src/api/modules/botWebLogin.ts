import { request } from "../request";

export const CLOUD_LOGIN = "https://bot.lynxce.cn/login";
export type Provider = "wechat" | "workbuddy";
type Config = { enabled: boolean; url: string; state: string };
type Grant = { access_token: string } | { bind_token: string };
export const botWebLogin = {
  config: (provider: Provider, signal?: AbortSignal) =>
    request<Config>("/auth/lynxce/web-login/config?provider=" + provider, {
      cache: "no-store",
      signal,
    }),
  exchange: (provider: Provider, code: string, state: string, locale: string) =>
    request<Grant>("/auth/lynxce/web-login/exchange", {
      method: "POST",
      body: JSON.stringify({ provider, code, state, locale }),
    }),
  bind: (bindToken: string, phone: string, code: string, locale: string) =>
    request<{ access_token: string }>("/auth/lynxce/web-login/bind", {
      method: "POST",
      body: JSON.stringify({ bind_token: bindToken, phone, code, locale }),
    }),
};
