import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { octopBotApi, type ChatReference } from "../../api/modules/octopBot";
import DirectorySearch from "./DirectorySearch";

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("opens the chosen historical thread and ignores older searches that finish later", async () => {
  const hit: ChatReference = {
    agent_id: "chief",
    thread_id: "original",
    part: 1,
    title: "Content calendar",
    excerpt: "Weekly calendar",
  };
  let finishFirst!: (result: {
    matches: ChatReference[];
    indexing: boolean;
  }) => void;
  const search = vi
    .spyOn(octopBotApi, "search")
    .mockImplementationOnce(
      () =>
        new Promise((done) => {
          finishFirst = done;
        }),
    )
    .mockResolvedValue({
      matches: [hit, { ...hit, part: 2 }],
      indexing: false,
    });
  const onThread = vi.fn();
  render(
    <DirectorySearch
      items={[
        {
          key: "bot:chief",
          name: "Chief",
          preview: "Coordinator",
          portrait: null,
        },
      ]}
      onClose={vi.fn()}
      onPick={vi.fn()}
      onThread={onThread}
    />,
  );
  const input = screen.getByRole("combobox");
  fireEvent.change(input, { target: { value: "first" } });
  expect(search).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("radio", { name: "botDirectory.historyTab" }),
  );
  await waitFor(() => expect(search).toHaveBeenCalledWith("first"));
  fireEvent.change(input, { target: { value: "calendar" } });
  await screen.findByRole("option", { name: /Weekly calendar/i });
  await act(async () => finishFirst({ matches: [], indexing: false }));
  expect(screen.getAllByRole("option")).toHaveLength(1);
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onThread).toHaveBeenCalledWith(hit);
});
