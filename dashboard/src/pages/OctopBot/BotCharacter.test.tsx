import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { BotCharacter, GroupCharacter } from "./BotCharacter";
import { type WorkspaceBot } from "../../api/modules/octopBot";
import { AppearancePicker, type AppearanceChoice } from "./AppearancePicker";
import octopMascot from "../../assets/avatars/octop-mascot.webp";

const chief: WorkspaceBot = {
  agent_id: "chief",
  name: "Chief",
  is_main: true,
  is_private: false,
  avatar: { shape: "whale", color: "deepseek", source: "character" },
};
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));
vi.mock("../../hooks/useAuthImageSrc", () => ({
  useAuthImageSrc: (url: string) => ({ src: url }),
}));
describe("Octop Bot character identity", () => {
  it("uses the official mascot for a default Chief, preserves a photo and keeps it in group mosaics", () => {
    const bot = { ...chief, avatar: undefined };
    const { container, rerender } = render(
      <>
        <BotCharacter bot={bot} />
        <GroupCharacter members={[bot]} />
      </>,
    );
    expect(
      container.querySelectorAll('[data-shape="octop"][data-ink="rose"] img'),
    ).toHaveLength(2);
    expect(container.querySelector("img")).toHaveAttribute("src", octopMascot);
    rerender(<BotCharacter bot={{ ...bot, icon_url: "/portrait.png" }} />);
    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "/portrait.png",
    );
    fireEvent.error(container.querySelector("img")!);
    expect(container.querySelector("img")).toHaveAttribute("src", octopMascot);
  });
  it("restores the Octop mascot for a saved Chief whale and offers only unbranded looks", () => {
    const choose = vi.fn();
    function Picker() {
      const [value, setValue] = useState<AppearanceChoice | null>(null);
      return (
        <AppearancePicker
          bot={chief}
          value={value}
          onChange={(v) => {
            choose(v);
            setValue(v);
          }}
        />
      );
    }
    const { container } = render(<Picker />);
    expect(screen.queryByRole("button", { name: /whale/i })).toBeNull();
    const octop = screen.getByRole("button", {
      name: "octopBot.avatar.shapes.octop",
    });
    expect(octop).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(octop);
    expect(choose).toHaveBeenLastCalledWith({
      kind: "character",
      shape: "octop",
      color: "rose",
    });
    expect(container.querySelector('input[type="color"]')).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "octopBot.avatar.shapes.sparkle" }),
    );
    expect(container.querySelector('input[type="color"]')).not.toBeNull();
    expect(screen.queryByRole("button", { name: /deepseek/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "common.reset" }));
    expect(
      container.querySelector('[data-bot-avatar="chief"] img'),
    ).toHaveAttribute("src", octopMascot);
  });
  it("gives identical gradient characters distinct paint references, eyes and independent live state", () => {
    const look = {
      shape: "star",
      color: "aurora",
      source: "character" as const,
    };
    const { container } = render(
      <>
        <BotCharacter bot={chief} look={look} />
        <BotCharacter bot={chief} look={look} state="waiting" />
      </>,
    );
    const gradients = container.querySelectorAll("linearGradient");
    expect(gradients).toHaveLength(2);
    expect(gradients[0].id).not.toBe(gradients[1].id);
    expect(container.querySelectorAll("rect")).toHaveLength(4);
    expect(
      screen.getByRole("img", { name: "octopBot.avatar.chief" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "octopBot.avatar.waiting" }),
    ).toBeInTheDocument();
  });
  it("uses the official motion sources for larger Chiefs and the still image in reduced motion or mosaics", () => {
    const { container, rerender } = render(
      <BotCharacter bot={chief} size={54} />,
    );
    const source = container.querySelector("picture source")!;
    expect(source).toHaveAttribute(
      "media",
      "(prefers-reduced-motion: no-preference)",
    );
    expect(source.getAttribute("srcset")).toMatch(/octop-mascot-peek.webp$/);
    expect(container.querySelector("picture img")).toHaveAttribute(
      "src",
      octopMascot,
    );
    rerender(<BotCharacter bot={chief} size={74} state="working" />);
    expect(source.getAttribute("srcset")).toMatch(/octop-mascot-type.webp$/);
    rerender(<GroupCharacter members={[chief, chief]} size={112} />);
    expect(container.querySelector("source")).toBeNull();
  });
  it("retains an uploaded photo and falls back to the same character when that photo fails", () => {
    const bot = {
      ...chief,
      is_main: false,
      icon_url: "/picture.png",
      avatar: { ...chief.avatar!, source: "photo" as const },
    };
    const { container } = render(
      <BotCharacter bot={bot} size={74} state="searching" />,
    );
    const img = container.querySelector("img")!;
    expect(img).toHaveAttribute("src", "/picture.png");
    expect(container.querySelector("picture")).toBeNull();
    fireEvent.error(img);
    expect(
      container.querySelectorAll('[data-shape="orb"][data-ink="blue"] rect'),
    ).toHaveLength(2);
  });
  it("shows three identities and the remaining count for a large group", () => {
    const { container } = render(
      <GroupCharacter
        members={Array.from({ length: 5 }, (_, i) => ({
          ...chief,
          agent_id: String(i),
        }))}
      />,
    );
    expect(container.querySelectorAll("[data-bot-avatar]")).toHaveLength(3);
    expect(screen.getByText("+2")).toBeInTheDocument();
  });
});
