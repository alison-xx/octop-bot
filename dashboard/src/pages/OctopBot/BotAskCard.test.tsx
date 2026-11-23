import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BotAskCard, { parseAskAnswers } from "./BotAskCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const questions = [
  {
    header: "Dates",
    question: "Which days?",
    options: [{ label: "This weekend" }, { label: "Next weekend" }],
  },
  {
    header: "Food",
    question: "What to eat?",
    multi_select: true,
    options: [{ label: "Noodles" }, { label: "Tea" }],
  },
  { header: "Notes", question: "Anything else?" },
];

const visible = (name: string) => screen.getByRole("button", { name });

/** Single-choice picks stay on screen briefly before the card moves on. */
const pickAndWait = (name: string) => {
  fireEvent.click(screen.getByRole("radio", { name }));
  act(() => {
    vi.advanceTimersByTime(300);
  });
};

describe("BotAskCard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("advances on a single choice and submits on Done", () => {
    const onSubmit = vi.fn();
    const { container } = render(
      <BotAskCard questions={questions} onSubmit={onSubmit} />,
    );

    expect(screen.queryByRole("button", { name: "chat.ask.back" })).toBeNull();
    // The pick shows as selected before the card moves on.
    fireEvent.click(screen.getByRole("radio", { name: "This weekend" }));
    expect(screen.getByRole("radio", { name: "This weekend" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    act(() => {
      vi.advanceTimersByTime(300);
    });

    // Multi-select waits for Next.
    fireEvent.click(screen.getByRole("checkbox", { name: "Noodles" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Tea" }));
    fireEvent.click(visible("chat.ask.next"));

    // Open-ended: Enter on the text row answers and finishes.
    const input = screen.getByPlaceholderText("chat.ask.freeTextPlaceholder");
    fireEvent.change(input, { target: { value: "No spice" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onSubmit).toHaveBeenCalledWith(
      "Dates: This weekend\nFood: Noodles; Tea\nNotes: No spice",
    );
    // The card stays, now as a read-only review.
    expect(container.querySelector('[data-bot-ask="review"]')).not.toBeNull();
    expect(screen.queryByRole("radio")).toBeNull();
  });

  it("skips questions and sends the skip message when none were answered", () => {
    const onSubmit = vi.fn();
    render(<BotAskCard questions={questions} onSubmit={onSubmit} />);
    fireEvent.click(visible("octopBot.ask.skip"));
    fireEvent.click(visible("octopBot.ask.skip"));
    fireEvent.click(visible("octopBot.ask.skip"));
    expect(onSubmit).toHaveBeenCalledWith("chat.ask.skipMessage");
  });

  it("submits when an option is picked on the last page", () => {
    const onSubmit = vi.fn();
    const { container } = render(
      <BotAskCard questions={questions.slice(0, 1)} onSubmit={onSubmit} />,
    );
    expect(visible("octopBot.ask.done")).toBeInTheDocument();
    pickAndWait("Next weekend");
    expect(onSubmit).toHaveBeenCalledWith("Dates: Next weekend");
    // The review keeps the choice visible.
    expect(screen.getByText("Next weekend")).toBeInTheDocument();
    expect(container.querySelector('[data-bot-ask="review"]')).not.toBeNull();
  });

  it("does not submit when Something else is opened on the last page", () => {
    const onSubmit = vi.fn();
    render(
      <BotAskCard questions={questions.slice(0, 1)} onSubmit={onSubmit} />,
    );
    fireEvent.click(visible("octopBot.ask.somethingElse"));
    expect(onSubmit).not.toHaveBeenCalled();
    const input = screen.getByPlaceholderText("octopBot.ask.somethingElse");
    fireEvent.change(input, { target: { value: "Monday" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledWith("Dates: Monday");
  });

  it("turns Something else into a text row", () => {
    const onSubmit = vi.fn();
    render(<BotAskCard questions={questions} onSubmit={onSubmit} />);
    fireEvent.click(visible("octopBot.ask.somethingElse"));
    const input = screen.getByPlaceholderText("octopBot.ask.somethingElse");
    fireEvent.change(input, { target: { value: "Monday" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("checkbox", { name: "Noodles" })).toBeVisible();
  });

  it("reads answers back from the sent reply", () => {
    expect(
      parseAskAnswers(questions, "Dates: Next weekend\nFood: Tea; Dumplings"),
    ).toEqual([
      { picked: ["Next weekend"], other: "" },
      { picked: ["Tea"], other: "Dumplings" },
      null,
    ]);
    expect(parseAskAnswers(questions, "You decide")).toBeNull();
  });
});
