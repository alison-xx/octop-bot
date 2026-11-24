import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BotApprovalCard from "./BotApprovalCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const options = ["允许一次", "总是允许", "拒绝"];

describe("BotApprovalCard", () => {
  it("answers with the button pressed, and nothing is pre-selected", () => {
    const onAnswer = vi.fn();
    render(
      <BotApprovalCard
        title="需要你确认"
        question={"Bot 想要发送：zhang@example.com\n周报已附上"}
        options={options}
        onAnswer={onAnswer}
      />,
    );
    expect(screen.getByText(/zhang@example.com/)).toBeTruthy();
    expect(document.activeElement).toBe(document.body);
    fireEvent.click(screen.getByRole("button", { name: "总是允许" }));
    expect(onAnswer).toHaveBeenCalledWith("总是允许");
  });

  it("treats Escape as a no", () => {
    const onAnswer = vi.fn();
    render(
      <BotApprovalCard
        title="t"
        question="q"
        options={options}
        onAnswer={onAnswer}
      />,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onAnswer).toHaveBeenCalledWith("拒绝");
  });

  it("is read-only without a way to answer", () => {
    render(<BotApprovalCard title="t" question="q" options={options} />);
    expect(
      (screen.getByRole("button", { name: "允许一次" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });
});
