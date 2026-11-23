import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { octopAgentsApi } from "../../api/modules/octopAgents";
import { octopBotApi, type WorkspaceBot } from "../../api/modules/octopBot";
import type { AppearanceChoice } from "./AppearancePicker";
import BotQuickCreate from "./BotQuickCreate";
import { GoalForm, GroupForm } from "./GroupForms";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("Octop Bot creation dialogs", () => {
  const getComputedStyle = window.getComputedStyle;
  beforeAll(() => {
    vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
      getComputedStyle(element),
    );
  });
  afterAll(() => {
    vi.restoreAllMocks();
  });

  it("preserves custom text and a manually chosen avatar when trying a role example", async () => {
    const create = vi
      .spyOn(octopAgentsApi, "createTeammate")
      .mockResolvedValue({ agent_id: "NEW123" });
    const done = vi.fn().mockResolvedValue(undefined);
    const choose = vi.fn();
    function Dialog() {
      const [choice, setChoice] = useState<AppearanceChoice | null>(null);
      return (
        <BotQuickCreate
          choice={choice}
          onChoose={(value) => {
            choose(value);
            setChoice(value);
          }}
          onCreated={done}
          onClose={() => {}}
        />
      );
    }
    render(<Dialog />);
    const name = screen.getByRole("textbox", { name: "octopBot.name" });
    fireEvent.change(name, { target: { value: "My note taker" } });
    const notes = screen.getByRole("button", { name: /botForms.notes.name/ });
    fireEvent.click(notes);
    expect(name).toHaveValue("My note taker");
    expect(choose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "botForms.keepDraft" }));
    expect(name).toHaveValue("My note taker");
    fireEvent.click(notes);
    fireEvent.click(
      screen.getByRole("button", { name: "botForms.applyExample" }),
    );
    expect(name).toHaveValue("botForms.notes.name");
    expect(choose).toHaveBeenLastCalledWith({
      kind: "character",
      shape: "acorn",
      color: "green",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "botClient.chooseAppearance" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "octopBot.avatar.shapes.heart" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /botForms.editor.name/ }),
    );
    expect(choose).toHaveBeenLastCalledWith({
      kind: "character",
      shape: "heart",
      color: "green",
    });
    fireEvent.click(screen.getByRole("button", { name: "common.create" }));
    await waitFor(() => expect(done).toHaveBeenCalledWith("NEW123"));
    expect(create).toHaveBeenCalledExactlyOnceWith(
      "botForms.editor.name",
      "botForms.editor.role",
    );
  });

  it("prepares a room with only the chosen section's eligible bots and waits for confirmation", async () => {
    const bots: WorkspaceBot[] = [
      { agent_id: "MAIN", name: "Chief", is_main: true, is_private: false },
      { agent_id: "WRITER", name: "Writer", is_main: false, is_private: false },
      { agent_id: "EDITOR", name: "Editor", is_main: false, is_private: false },
      {
        agent_id: "SHARED",
        name: "Shared",
        is_main: false,
        is_private: false,
        can_join_group: false,
      },
      {
        agent_id: "PRIVATE",
        name: "Private",
        is_main: false,
        is_private: true,
      },
    ];
    const body = {
      name: "Studio",
      admin_id: "EDITOR",
      member_ids: ["EDITOR", "WRITER"],
      reply_mode: "admin_first" as const,
    };
    const create = vi
      .spyOn(octopBotApi, "createGroup")
      .mockResolvedValue({ ...body, group_id: "ROOM" });
    const saved = vi.fn();
    render(
      <GroupForm
        bots={bots}
        chiefId="MAIN"
        seed={{
          name: "Studio",
          memberIds: [
            "PRIVATE",
            "SHARED",
            "REMOVED",
            "EDITOR",
            "WRITER",
            "EDITOR",
          ],
        }}
        onSaved={saved}
        onClose={() => {}}
      />,
    );
    expect(screen.getByRole("textbox", { name: "octopBot.name" })).toHaveValue(
      "Studio",
    );
    expect(screen.getByRole("checkbox", { name: /Chief/ })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Editor/ })).toBeChecked();
    expect(create).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "common.create" }));
    await waitFor(() => expect(saved).toHaveBeenCalled());
    expect(create).toHaveBeenCalledWith(body);
  });

  it("creates a separate group with the source configuration after naming it", async () => {
    const bots = ["ADMIN", "EXPERT"].map((id) => ({
      agent_id: id,
      name: id,
      is_main: false,
      is_private: false,
    }));
    const body = {
      name: "Second topic",
      admin_id: "ADMIN",
      member_ids: ["ADMIN", "EXPERT"],
      reply_mode: "all_members" as const,
    };
    const create = vi
      .spyOn(octopBotApi, "createGroup")
      .mockClear()
      .mockResolvedValue({ ...body, group_id: "G2" });
    render(
      <GroupForm
        bots={bots}
        chiefId="EXPERT"
        seed={{ memberIds: ["ADMIN", "EXPERT"], replyMode: "all_members" }}
        onSaved={() => {}}
        onClose={() => {}}
      />,
    );
    expect(create).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", { name: "octopBot.name" }), {
      target: { value: body.name },
    });
    fireEvent.click(screen.getByRole("button", { name: "common.create" }));
    await waitFor(() => expect(create).toHaveBeenCalledExactlyOnceWith(body));
  });

  it("finds same-named members by role or ID, and keeps the current administrator selected", async () => {
    const bots: WorkspaceBot[] = [
      { agent_id: "MAIN", name: "Chief", is_main: true, is_private: false },
      {
        agent_id: "NOTES1",
        name: "Alex",
        description: "Meeting notes",
        is_main: false,
        is_private: false,
      },
      {
        agent_id: "TEXT02",
        name: "Alex",
        description: "Article editing",
        is_main: false,
        is_private: false,
      },
      { agent_id: "SECRET", name: "Private", is_main: false, is_private: true },
    ];
    const result = {
      group_id: "G",
      name: "Team",
      admin_id: "TEXT02",
      member_ids: ["TEXT02", "NOTES1"],
      reply_mode: "admin_first" as const,
    };
    const create = vi
      .spyOn(octopBotApi, "createGroup")
      .mockResolvedValue(result);
    const saved = vi.fn();
    render(
      <GroupForm
        chiefId="MAIN"
        bots={bots}
        onClose={() => {}}
        onSaved={saved}
      />,
    );
    expect(screen.queryByText("Private")).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "octopBot.name" }), {
      target: { value: "Team" },
    });
    const search = screen.getByRole("textbox", {
      name: "botForms.searchMembers",
    });
    fireEvent.change(search, { target: { value: "notes" } });
    expect(screen.getByRole("checkbox", { name: /Chief/ })).toBeDisabled();
    fireEvent.click(
      screen.getByRole("checkbox", { name: /Alex.*NOTES1.*Meeting notes/ }),
    );
    expect(screen.queryByRole("checkbox", { name: /TEXT02/ })).toBeNull();
    const admin = screen.getByRole("combobox", { name: "octopBot.admin" });
    fireEvent.mouseDown(admin);
    fireEvent.change(admin, { target: { value: "TEXT02" } });
    fireEvent.click(
      await screen.findByText("Article editing", {
        selector: ".ant-select-dropdown small",
      }),
    );
    expect(
      screen.getByRole("checkbox", { name: /Alex.*TEXT02/ }),
    ).toBeDisabled();
    fireEvent.change(search, { target: { value: "MAIN" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Chief/ }));
    fireEvent.click(screen.getByRole("button", { name: "common.create" }));
    await waitFor(() => expect(saved).toHaveBeenCalledWith(result));
    expect(create).toHaveBeenCalledExactlyOnceWith({
      name: "Team",
      admin_id: "TEXT02",
      member_ids: ["TEXT02", "NOTES1"],
      reply_mode: "admin_first",
    });
  });
  it("saves a goal once and locks the dialog while the save is in flight", async () => {
    let finish!: (value: never) => void;
    const saveGoal = vi.spyOn(octopBotApi, "saveGoal").mockImplementation(
      () =>
        new Promise((done) => {
          finish = done;
        }),
    );
    const close = vi.fn();
    const saved = vi.fn();
    render(
      <GoalForm
        group={{
          group_id: "room",
          name: "Room",
          admin_id: "chief",
          member_ids: ["chief"],
          reply_mode: "admin_first",
        }}
        bots={[]}
        goal={null}
        onClose={close}
        onSaved={saved}
      />,
    );
    const title = screen.getByRole("textbox", { name: "octopBot.goalTitle" });
    fireEvent.change(title, { target: { value: "Launch" } });
    fireEvent.change(
      screen.getByRole("textbox", { name: "octopBot.criteria" }),
      { target: { value: "Shipped" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "octopBot.save" }));
    await waitFor(() => expect(saveGoal).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(title).toBeDisabled());
    fireEvent.submit(title.closest("form")!);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(close).not.toHaveBeenCalled();
    await new Promise((done) => setTimeout(done, 0));
    expect(saveGoal).toHaveBeenCalledTimes(1);
    finish({ title: "Launch" } as never);
    await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
  });
});
