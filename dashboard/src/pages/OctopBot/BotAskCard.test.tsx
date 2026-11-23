import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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

const visible = (name: string) =>
  screen
    .getAllByRole("button", { name })
    .find((el) => !el.closest("[aria-hidden='true']"))!;

describe("BotAskCard", () => {
  it("advances on a single choice and submits on Done", () => {
    const onSubmit = vi.fn();
    const { container } = render(
      <BotAskCard questions={questions} onSubmit={onSubmit} />,
    );

    expect(screen.queryByRole("button", { name: "chat.ask.back" })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "This weekend" }));

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
