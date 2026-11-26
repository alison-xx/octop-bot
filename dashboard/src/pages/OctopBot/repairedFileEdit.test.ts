import { describe, expect, it } from "vitest";
import { classifyChatStreamError } from "../../utils/chatStreamError";
import { repairedFileEdit } from "./repairedFileEdit";

describe("ambiguous edits", () => {
  const err =
    "Error: String '<b>38%</b>' appears 2 times in file. Use replace_all=True to replace all instances, or provide a more specific string with surrounding context.";
  function message(
    old_string: string,
    new_string: string,
    file_path = "/index.html",
  ) {
    return {
      id: "m",
      role: "assistant" as const,
      content: "",
      status: "done" as const,
      toolData: {
        name: "edit_file",
        output: "Edited",
        arguments: JSON.stringify({ old_string, new_string, file_path }),
      },
    };
  }
  it("recognizes the real diagnostic and only clears it for the corrected change", () => {
    expect(classifyChatStreamError(err)).toBe("stream_errors.ambiguous_edit");
    const failed = message("38%", "39%");
    expect(repairedFileEdit(failed, message("price: 38%", "price: 39%"))).toBe(
      true,
    );
    expect(repairedFileEdit(failed, message("price: 38%", "price: 40%"))).toBe(
      false,
    );
    expect(repairedFileEdit(failed, message("38%", "39%", "/other.html"))).toBe(
      false,
    );
    expect(repairedFileEdit(failed, { ...failed, status: "error" })).toBe(
      false,
    );
  });
});
