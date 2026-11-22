import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DirectoryItem, type DirectoryEntry } from "./DirectoryItem";

const t = (key: string) => key;
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t }) }));
const renders = vi.hoisted(() => ({ count: 0 }));
vi.mock("./BotCharacter", () => ({
  BotCharacter: () => {
    renders.count++;
    return null;
  },
  GroupCharacter: () => null,
}));

const item: DirectoryEntry = {
  key: "bot:writer",
  name: "Writer",
  bot: {
    agent_id: "writer",
    name: "Writer",
    is_main: false,
    is_private: false,
  },
};
const sectionNames = ["Drafts"];
const events = () => ({});
const overflowProps = () => ({});
const onDragging = () => {};

describe("DirectoryItem", () => {
  it("skips re-rendering when the sidebar re-renders with unchanged props", () => {
    const onAction = vi.fn();
    const onPick = vi.fn();
    function Sidebar() {
      const [tick, setTick] = useState(0);
      return (
        <>
          <button onClick={() => setTick(tick + 1)}>tick {tick}</button>
          <DirectoryItem
            item={item}
            chief={false}
            pinned={false}
            selected={false}
            compact={false}
            standalone
            disabled={false}
            unread={0}
            subtitle="Teammate"
            motion="idle"
            sectionNames={sectionNames}
            bulkDisabled={false}
            menuEvents={events}
            overflowProps={overflowProps}
            onAction={onAction}
            onPick={onPick}
            onDragging={onDragging}
          />
        </>
      );
    }
    render(<Sidebar />);
    expect(renders.count).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "tick 0" }));
    expect(screen.getByRole("button", { name: "tick 1" })).toBeVisible();
    expect(renders.count).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Writer" }));
    expect(onPick).toHaveBeenCalledWith(item);
  });
});
