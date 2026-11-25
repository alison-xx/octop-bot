import { render, screen } from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { expect, it, vi } from "vitest";

import en from "../../locales/en.json";
import zh from "../../locales/zh.json";
import { BotTaskReport } from "./BotTaskCard";
import type { BotTask } from "./botTasks";

vi.unmock("react-i18next");

it.each([
  {
    lang: "zh",
    older: "暂无检查记录",
    nameOnly: "仅文件名",
    opened: "LibreOffice 已打开",
    failed: "无法打开 broken.pdf，本次未交付。",
  },
  {
    lang: "en",
    older: "No check recorded",
    nameOnly: "filename only",
    opened: "opened in LibreOffice",
    failed: "Could not open broken.pdf. This version was not delivered.",
  },
])(
  "shows the recorded level of verification in $lang",
  async ({ lang, older, nameOnly, opened, failed }) => {
    const i18n = createInstance();
    await i18n.init({
      lng: lang,
      resources: { en: { translation: en }, zh: { translation: zh } },
    });
    const file = { path: "report", size: 250, version: 1, at: 1 };
    const task: BotTask = {
      id: "test",
      goal: "Quarterly reports",
      tier: "standard",
      status: "partial",
      criteria: [],
      assumptions: [],
      open_issues: [],
      summary: "",
      budget: { steps: 6, minutes: 2 },
      started_at: 1,
      updated_at: 2,
      finished_at: 2,
      deliverables: [
        { ...file, name: "old-empty.pdf", facts: [] },
        { ...file, name: "old-missing.pdf" },
        {
          ...file,
          name: "large.docx",
          size: 51 * 1024 * 1024,
          facts: [{ k: "filenameOnly", n: 1 }],
        },
        {
          ...file,
          name: "opened.docx",
          facts: [
            { k: "opened", n: 1 },
            { k: "pages", n: 2 },
          ],
        },
      ],
      delivery_failures: { "broken.pdf": "open" },
    };
    render(
      <I18nextProvider i18n={i18n}>
        <BotTaskReport task={task} />
      </I18nextProvider>,
    );
    const receipt = (name: string) => screen.getByTitle(name).closest("li");
    expect(receipt("old-empty.pdf")).toHaveTextContent(older);
    expect(receipt("old-missing.pdf")).toHaveTextContent(older);
    expect(receipt("large.docx")).toHaveTextContent(nameOnly);
    expect(receipt("large.docx")).not.toHaveTextContent(opened);
    expect(receipt("opened.docx")).toHaveTextContent(opened);
    expect(screen.getByText(failed)).toBeInTheDocument();
    expect(screen.queryByTitle("broken.pdf")).toBeNull();
  },
);
