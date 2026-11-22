import { describe, expect, it } from "vitest";
import { resolveMentions } from "./groupMentions";

const members = [
  { agent_id: "editor", name: "Editor" },
  { agent_id: "writer", name: "Content Writer" },
  { agent_id: "content", name: "Content" },
  { agent_id: "designer", name: "设计师" },
  { agent_id: "designer-lead", name: "设计师 主管" },
];

describe("resolveMentions", () => {
  it("keeps names that contain spaces, longest name first", () => {
    expect(resolveMentions("@Editor @Content Writer please", members)).toEqual([
      "editor",
      "writer",
    ]);
    expect(resolveMentions("@Content, check this", members)).toEqual([
      "content",
    ]);
  });

  it("resolves CJK names, including ones directly followed by text", () => {
    expect(resolveMentions("@设计师 看一下", members)).toEqual(["designer"]);
    expect(resolveMentions("@设计师 主管 看一下", members)).toEqual([
      "designer-lead",
    ]);
    expect(resolveMentions("请@设计师确认", members)).toEqual(["designer"]);
  });

  it("matches the backend boundary rules", () => {
    // Preceded by a word character or another @: not a mention.
    expect(resolveMentions("mail me@editor", members)).toEqual([]);
    expect(resolveMentions("@@editor", members)).toEqual([]);
    // Followed by a word character or a hyphen: a different handle.
    expect(resolveMentions("@editors", members)).toEqual([]);
    expect(resolveMentions("@editor-x", members)).toEqual([]);
    // Punctuation and line ends close a mention.
    expect(resolveMentions("(@editor) and\n@writer.", members)).toEqual([
      "editor",
      "writer",
    ]);
  });

  it("dedupes and keeps first-mention order", () => {
    expect(resolveMentions("@writer @Editor @Content Writer", members)).toEqual(
      ["writer", "editor"],
    );
  });

  it("only addresses duplicate names through their agent ID", () => {
    const twins = [
      { agent_id: "a1", name: "Analyst" },
      { agent_id: "a2", name: "Analyst" },
    ];
    expect(resolveMentions("@Analyst go", twins)).toEqual([]);
    expect(resolveMentions("@a2 go", twins)).toEqual(["a2"]);
  });

  it("escapes regular-expression characters in names", () => {
    expect(
      resolveMentions("@C++ (beta) ship it", [
        { agent_id: "cpp", name: "C++ (beta)" },
      ]),
    ).toEqual(["cpp"]);
    expect(resolveMentions("@anything", [])).toEqual([]);
  });
});
