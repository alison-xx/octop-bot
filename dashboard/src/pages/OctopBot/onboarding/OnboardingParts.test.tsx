import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  OnboardingAsk,
  OnboardingTeamReady,
  OnboardingWelcome,
} from "./OnboardingParts";

const options = vi.hoisted(() => vi.fn());
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) =>
      values ? `${key} ${JSON.stringify(values)}` : key,
  }),
}));
vi.mock("../BotCharacter", () => ({
  BotCharacter: () => null,
  octopCharacter: {},
}));
vi.mock("../../../api/modules/botOnboarding", () => ({
  botOnboardingApi: { options },
}));

afterEach(() => {
  cleanup();
  options.mockReset();
});

const OPTIONS = {
  industries: [
    { id: "ecommerce", name: "电商零售", hint: "商品上新文案, 店铺经营日报" },
    { id: "trade", name: "外贸出口", hint: "询盘报价" },
  ],
  roles: [
    { id: "founder", name: "老板 / 创业者", hint: "看全局、拍板" },
    { id: "sales", name: "销售", hint: "找线索" },
  ],
};

function welcome() {
  const onStart = vi.fn();
  const onSkip = vi.fn();
  render(<OnboardingWelcome busy={false} onStart={onStart} onSkip={onSkip} />);
  return { onStart, onSkip };
}
const startButton = () =>
  screen.getByRole("button", { name: "botOnboarding.guide.startTeam" });

describe("onboarding first screen", () => {
  it("opens on industries, names only, and skips right away", async () => {
    options.mockResolvedValue(OPTIONS);
    const { onSkip, onStart } = welcome();
    const ecommerce = await screen.findByRole("button", { name: "电商零售" });
    expect(ecommerce).toHaveAttribute("title", "商品上新文案, 店铺经营日报");
    expect(screen.queryByRole("button", { name: "销售" })).toBeNull();
    expect(startButton()).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "botOnboarding.guide.skip" }),
    );
    expect(onSkip).toHaveBeenCalledTimes(1);
    expect(onStart).not.toHaveBeenCalled();
  });

  it("starts with the picked industry and an optional note", async () => {
    options.mockResolvedValue(OPTIONS);
    const { onStart } = welcome();
    fireEvent.click(await screen.findByRole("button", { name: "外贸出口" }));
    expect(screen.getByRole("button", { name: "外贸出口" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.change(
      screen.getByPlaceholderText("botOnboarding.guide.notePlaceholder"),
      { target: { value: " 家居用品 " } },
    );
    fireEvent.click(startButton());
    expect(onStart).toHaveBeenLastCalledWith({
      kind: "industry",
      option: "trade",
      note: "家居用品",
      label: "外贸出口",
    });
  });

  it("the job tab lists jobs and a pick does not carry over", async () => {
    options.mockResolvedValue(OPTIONS);
    const { onStart } = welcome();
    fireEvent.click(await screen.findByRole("button", { name: "外贸出口" }));
    fireEvent.click(screen.getByText("botOnboarding.guide.roles"));
    expect(screen.queryByRole("button", { name: "外贸出口" })).toBeNull();
    expect(startButton()).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "老板 / 创业者" }));
    fireEvent.click(startButton());
    expect(onStart).toHaveBeenCalledWith({
      kind: "role",
      option: "founder",
      note: undefined,
      label: "老板 / 创业者",
    });
  });

  it("needs words for something else, even without the lists", async () => {
    options.mockRejectedValue(new Error("offline"));
    const { onStart } = welcome();
    fireEvent.click(
      await screen.findByRole("button", { name: "botOnboarding.guide.other" }),
    );
    expect(startButton()).toBeDisabled();
    fireEvent.change(
      screen.getByPlaceholderText(
        "botOnboarding.guide.customIndustryPlaceholder",
      ),
      { target: { value: "宠物店" } },
    );
    await waitFor(() => expect(startButton()).toBeEnabled());
    fireEvent.click(startButton());
    expect(onStart).toHaveBeenCalledWith({
      kind: "industry",
      custom: "宠物店",
      note: undefined,
      label: "宠物店",
    });
  });
});

describe("onboarding guide strips", () => {
  it("while Chief works, says so", () => {
    render(<OnboardingAsk building onSkip={vi.fn()} />);
    expect(
      screen.getByRole("region", { name: "botOnboarding.guide.buildingTitle" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "botOnboarding.guide.retry" }),
    ).toBeNull();
  });

  it("offers to send the pick again when no team came back", () => {
    const onRetry = vi.fn();
    const onSkip = vi.fn();
    render(
      <OnboardingAsk building={false} onRetry={onRetry} onSkip={onSkip} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "botOnboarding.guide.retry" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "botOnboarding.guide.skip" }),
    );
    expect(onRetry).toHaveBeenCalled();
    expect(onSkip).toHaveBeenCalled();
  });

  it("the ready team opens its group", () => {
    const onOpen = vi.fn();
    render(
      <OnboardingTeamReady
        name="Export"
        members={["Ada", "Ben"]}
        portraits={null}
        onOpen={onOpen}
        onSkip={vi.fn()}
      />,
    );
    expect(screen.getByText("Ada · Ben")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /botOnboarding.guide.openGroup/ }),
    );
    expect(onOpen).toHaveBeenCalled();
  });
});
