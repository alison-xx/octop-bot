import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ownModelKeysApi,
  type OwnKeyVendor,
} from "../../api/modules/ownModelKeys";
import AddModelKeyDialog, { groupCompanies } from "./AddModelKeyDialog";

vi.mock("react-i18next", () => {
  const t = (key: string, params?: Record<string, unknown>) =>
    params?.name ? `${key}:${params.name}` : key;
  return { useTranslation: () => ({ t }) };
});
vi.mock("../../api/modules/ownModelKeys", () => ({
  ownModelKeysApi: {
    vendors: vi.fn(),
    add: vi.fn(),
    useModel: vi.fn(),
  },
}));

function vendor(id: string, company: string): OwnKeyVendor {
  return {
    id,
    name: id,
    vendor: company,
    logo_id: company,
    base_url: `https://${id}.example/v1`,
    protocol: "openai",
    api_key_prefix: "sk-",
    models: [],
  };
}
const catalog = [
  vendor("openai", "openai"),
  vendor("tencent-coding-plan", "tencent"),
  vendor("tencent-tokenhub", "tencent"),
  vendor("deepseek", "deepseek"),
  vendor("dashscope", "aliyun"),
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(ownModelKeysApi.vendors).mockResolvedValue({
    vendors: catalog,
    custom_allowed: true,
  });
});

describe("own vendor keys", () => {
  it("puts the featured companies first and each one's usual plan first", () => {
    const companies = groupCompanies(catalog);
    expect(companies.map((c) => c.id)).toEqual([
      "tencent",
      "aliyun",
      "deepseek",
      "openai",
    ]);
    expect(companies[0].plans.map((p) => p.id)).toEqual([
      "tencent-tokenhub",
      "tencent-coding-plan",
    ]);
  });

  it("adds a Tencent Cloud key, then chats on one of its models", async () => {
    const onChanged = vi.fn();
    const onClose = vi.fn();
    vi.mocked(ownModelKeysApi.add).mockResolvedValue({
      id: "k1",
      vendor: "tencent-tokenhub",
      name: "Tencent Cloud TokenHub",
      base_url: "https://tencent-tokenhub.example/v1",
      key_hint: "****1234",
      models: [
        { id: "hunyuan-turbos", name: "Hunyuan TurboS" },
        { id: "deepseek-v3", name: "DeepSeek V3" },
      ],
      created_at: 1,
    });
    vi.mocked(ownModelKeysApi.useModel).mockResolvedValue({
      keys: [],
      in_use: "k1",
      selected_model: "deepseek-v3",
    });
    render(
      <AddModelKeyDialog
        open
        cloud={false}
        onClose={onClose}
        onChanged={onChanged}
      />,
    );
    // Without a translated company name, the tile falls back to its usual plan's name.
    fireEvent.click(
      await screen.findByRole("button", { name: "tencent-tokenhub" }),
    );
    // Several plans: the usual one is picked; the key is checked by the server.
    expect(screen.getByLabelText("botModels.add.plan")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("API Key"), {
      target: { value: " sk-secret-1234 " },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "botModels.add.verify" }),
    );
    await screen.findByRole("status");
    expect(ownModelKeysApi.add).toHaveBeenCalledWith({
      vendor: "tencent-tokenhub",
      api_key: "sk-secret-1234",
    });
    expect(onChanged).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("radio", { name: "DeepSeek V3" }));
    fireEvent.click(
      screen.getByRole("button", { name: "botModels.add.useModel" }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(ownModelKeysApi.useModel).toHaveBeenCalledWith("k1", "deepseek-v3");
  });

  it("offers a custom OpenAI-compatible URL only where the server allows it", async () => {
    vi.mocked(ownModelKeysApi.vendors).mockResolvedValue({
      vendors: catalog,
      custom_allowed: false,
    });
    render(
      <AddModelKeyDialog open cloud onClose={vi.fn()} onChanged={vi.fn()} />,
    );
    await screen.findByRole("button", { name: "tencent-tokenhub" });
    expect(
      screen.queryByRole("button", { name: "botModels.add.custom" }),
    ).toBeNull();
    expect(screen.getByText("botModels.add.hintCloud")).toBeInTheDocument();
  });
});
