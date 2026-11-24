import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import {
  botMarketApi,
  type MarketCard,
  type MarketDetail,
} from "../../api/modules/botMarket";
import BotMarket from "./BotMarket";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) =>
      values?.name ? `${key}:${values.name}` : key,
  }),
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: 1, role: "admin", username: "me" }),
}));
vi.mock("../../utils/permissions", () => ({ navAllowed: () => true }));

const look = { shape: "orb", color: "orange" };
const cards: MarketCard[] = [
  {
    slug: "store-daily-brief",
    category: "ecommerce",
    featured: true,
    name: "Store Daily Brief",
    tagline: "Yesterday on one page",
    look,
    avatar: null,
  },
  {
    slug: "code-reviewer",
    category: "engineering",
    featured: false,
    name: "Code Reviewer",
    tagline: "Findings ranked by severity",
    look,
    avatar: null,
  },
];
const detail: MarketDetail = {
  ...cards[0],
  version: 1,
  description: "Send it your exports.",
  role: "You are an analyst.",
  instructions: ["Never invent numbers."],
  memories: ["Conversion = buyers / visitors."],
  skills: [
    { id: "daily-brief", name: "Write the brief", summary: "Use when…" },
  ],
  routines: [
    {
      id: "morning",
      name: "Morning brief",
      when: "Daily 8:30",
      prompt: "…",
      suggested: true,
    },
    {
      id: "night",
      name: "Night check",
      when: "Daily 23:00",
      prompt: "…",
      suggested: false,
    },
  ],
  integrations: [
    { kind: "tencent-docs", name: "Tencent Docs", color: "#0052d9" },
  ],
  starters: ["Write me a brief"],
};

function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/octop-bot/market/:slug?/:action?"
          element={<BotMarket />}
        />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Bot market", () => {
  const getComputedStyle = window.getComputedStyle;
  beforeAll(() => {
    vi.spyOn(window, "getComputedStyle").mockImplementation((el) =>
      getComputedStyle(el),
    );
    vi.spyOn(botMarketApi, "list").mockResolvedValue({
      categories: [
        { id: "ecommerce", name: "E-commerce", blurb: "Shops", count: 1 },
        { id: "engineering", name: "Engineering", blurb: "Code", count: 1 },
      ],
      templates: cards,
    });
    vi.spyOn(botMarketApi, "mine").mockResolvedValue({
      imports: { "code-reviewer": ["MINE01"] },
    });
    vi.spyOn(botMarketApi, "get").mockResolvedValue(detail);
  });
  afterAll(() => {
    vi.restoreAllMocks();
  });

  it("lists featured and industry rows, filters by search, and opens an imported Bot", async () => {
    renderAt("/octop-bot/market");
    expect(await screen.findAllByText("Store Daily Brief")).toHaveLength(2);
    expect(
      screen.getByRole("heading", { name: "Engineering" }),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("botMarket.search"), {
      target: { value: "severity" },
    });
    expect(screen.queryByText("Store Daily Brief")).not.toBeInTheDocument();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "botMarket.openNamed:Code Reviewer",
      }),
    );
    expect(screen.getByTestId("where")).toHaveTextContent(
      "/octop-bot/bots/MINE01",
    );
  });

  it("imports with the suggested routines from a deep link and opens the new Bot", async () => {
    const install = vi.spyOn(botMarketApi, "install").mockResolvedValue({
      agent_id: "NEW123",
      name: "Store Daily Brief",
      routines: ["c1"],
      integrations: ["tencent-docs"],
    });
    renderAt("/octop-bot/market/store-daily-brief/import");
    expect(
      await screen.findByText("botMarket.importTitle"),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "botMarket.importConfirm" }),
    );
    await waitFor(() =>
      expect(install).toHaveBeenCalledWith(
        "store-daily-brief",
        "Store Daily Brief",
        ["morning"],
      ),
    );
    expect(await screen.findByTestId("where")).toHaveTextContent(
      "/octop-bot/bots/NEW123",
    );
  });
});
