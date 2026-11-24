import { request } from "../request";

/** A model a vendor offers, as the catalog or the key's own `/models` lists it. */
export type OwnKeyModel = { id: string; name: string };

/** A model vendor the user can add their own API key for. */
export type OwnKeyVendor = {
  id: string;
  name: string;
  /** Company, e.g. `tencent`, `aliyun`, `volcengine`. */
  vendor: string;
  /** Icon key in the dashboard's provider icon set. */
  logo_id: string;
  base_url: string;
  protocol: string;
  api_key_prefix: string;
  models: OwnKeyModel[];
};

export type OwnKeyVendors = {
  vendors: OwnKeyVendor[];
  /** Whether a custom OpenAI-compatible base URL may be added (desktop only). */
  custom_allowed: boolean;
};

/** A saved key; the key itself never comes back, only `key_hint` (`****` + last four). */
export type OwnKey = {
  id: string;
  vendor: string;
  name: string;
  base_url: string;
  key_hint: string;
  models: OwnKeyModel[];
  created_at: number;
};

export type OwnKeyList = {
  keys: OwnKey[];
  /** Id of the key the user is chatting on, if any. */
  in_use: string | null;
  selected_model: string | null;
};

export type AddOwnKey = {
  vendor: string;
  api_key: string;
  name?: string;
  base_url?: string;
  protocol?: string;
};

const base = "/octop-bot/model-keys";

export const ownModelKeysApi = {
  vendors: () => request<OwnKeyVendors>(base + "/vendors"),
  list: () => request<OwnKeyList>(base),
  add: (body: AddOwnKey) =>
    request<OwnKey>(base, { method: "POST", body: JSON.stringify(body) }),
  remove: (id: string) =>
    request<void>(`${base}/${encodeURIComponent(id)}`, { method: "DELETE" }),
  useModel: (id: string, model_id: string) =>
    request<OwnKeyList>(`${base}/${encodeURIComponent(id)}/model`, {
      method: "PUT",
      body: JSON.stringify({ model_id }),
    }),
};
