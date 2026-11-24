import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ModelSelect, { type ModelItem } from "./ModelSelect";
import { groupModelItems } from "./modelLines";

vi.mock("react-i18next", () => {
  const t = (key: string, o?: { n?: number }) =>
    o?.n === undefined ? key : `${key}:${o.n}`;
  return { useTranslation: () => ({ t, i18n: { language: "en" } }) };
});

const flash = (value: string): ModelItem => ({
  value,
  id: value,
  name: "DeepSeek V4.1 Flash",
});
const items: ModelItem[] = [
  flash("yunxin::deepseek-flash"),
  {
    value: "qianwen::qwen3.8-flash",
    id: "qianwen::qwen3.8-flash",
    name: "Qwen3.8 Flash",
  },
  flash("deepseek::deepseek-flash"),
  flash("deepseek::deepseek-ai/DeepSeek-V4-Flash"),
];

describe("groupModelItems", () => {
  it("lists a model once, its routes in catalog order", () => {
    const choices = groupModelItems(items);
    expect(choices.map((c) => c.name)).toEqual([
      "DeepSeek V4.1 Flash",
      "Qwen3.8 Flash",
    ]);
    expect(choices[0].routes.map((r) => r.value)).toEqual([
      "yunxin::deepseek-flash",
      "deepseek::deepseek-flash",
      "deepseek::deepseek-ai/DeepSeek-V4-Flash",
    ]);
  });

  it("keeps the same model from different groups apart", () => {
    const choices = groupModelItems([
      { value: "lynxce/deepseek-chat", id: "deepseek-chat", group: "lynxce" },
      { value: "mine/deepseek-chat", id: "deepseek-chat", group: "mine" },
    ]);
    expect(choices).toHaveLength(2);
  });
});

describe("ModelSelect routes", () => {
  it("switches between the routes of the current model", () => {
    const onChange = vi.fn();
    render(
      <ModelSelect
        aria-label="model"
        items={items}
        value="deepseek::deepseek-flash"
        onChange={onChange}
      />,
    );
    const routes = screen.getAllByRole("button", { pressed: false });
    expect(screen.getByRole("button", { pressed: true }).textContent).toBe(
      "octopBot.modelRouteN:2",
    );
    fireEvent.click(routes[0]);
    expect(onChange).toHaveBeenCalledWith("yunxin::deepseek-flash");
  });

  it("shows no routes for a model with one", () => {
    render(
      <ModelSelect
        aria-label="model"
        items={items}
        value="qianwen::qwen3.8-flash"
        onChange={() => {}}
      />,
    );
    expect(screen.queryByRole("group")).toBeNull();
  });
});
