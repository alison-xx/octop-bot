import { describe, expect, it } from "vitest";
import {
  csvExcerpt,
  FILE_TYPE_COLORS,
  fileExtension,
  filePreviewKind,
  fileTypeLabel,
  fileTypeOf,
  formatFileSize,
  middleEllipsis,
} from "./fileCardMeta";

describe("middleEllipsis", () => {
  it("leaves short names alone", () => {
    expect(middleEllipsis("dec2026.csv")).toBe("dec2026.csv");
  });

  it("cuts the middle and keeps the extension", () => {
    const out = middleEllipsis("Octop-quarterly-business-review-final.pdf", 24);
    expect(Array.from(out)).toHaveLength(24);
    expect(out.endsWith(".pdf")).toBe(true);
    expect(out.startsWith("Octop-quart")).toBe(true);
    expect(out).toContain("…");
    expect(out).toContain("inal.pdf");
  });

  it("counts CJK characters as one and keeps them whole", () => {
    const out = middleEllipsis(
      "二〇二六年度经营分析报告最终版本修订稿第三版.docx",
      16,
    );
    expect(Array.from(out)).toHaveLength(16);
    expect(out.endsWith(".docx")).toBe(true);
  });

  it("handles names without an extension", () => {
    const out = middleEllipsis("a".repeat(40), 10);
    expect(out).toHaveLength(10);
    expect(out).toContain("…");
  });
});

describe("formatFileSize", () => {
  it.each([
    [0, "0 B"],
    [512, "512 B"],
    [1536, "1.5 KB"],
    [10 * 1024, "10 KB"],
    [2 * 1024 * 1024, "2 MB"],
    [2.44 * 1024 * 1024, "2.4 MB"],
    [12.6 * 1024 * 1024, "13 MB"],
    [1023.8 * 1024, "1 MB"],
    [3 * 1024 ** 3, "3 GB"],
  ])("%d bytes → %s", (bytes, text) => {
    expect(formatFileSize(bytes)).toBe(text);
  });

  it("returns empty text for invalid sizes", () => {
    expect(formatFileSize(-1)).toBe("");
    expect(formatFileSize(Number.NaN)).toBe("");
  });
});

describe("file types", () => {
  it.each([
    ["report.PDF", "pdf"],
    ["memo.docx", "word"],
    ["dec2026.csv", "excel"],
    ["sheet.xlsx", "excel"],
    ["deck.pptx", "ppt"],
    ["bundle.tar.gz", "archive"],
    ["photo.jpeg", "image"],
    ["notes.md", "other"],
    ["Makefile", "other"],
  ])("%s → %s", (name, kind) => {
    expect(fileTypeOf(name)).toBe(kind);
  });

  it("falls back to the MIME type", () => {
    expect(fileTypeOf("download", "application/pdf")).toBe("pdf");
    expect(
      fileTypeOf(
        "x",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      ),
    ).toBe("excel");
  });

  it("maps families to the Grok colors and others to gray", () => {
    expect(FILE_TYPE_COLORS.pdf).toBe("#E5484D");
    expect(FILE_TYPE_COLORS.word).toBe("#2F6FEB");
    expect(FILE_TYPE_COLORS.excel).toBe("#1F9D55");
    expect(FILE_TYPE_COLORS.ppt).toBe("#F2711C");
    expect(FILE_TYPE_COLORS.archive).toBe("#8E4EC6");
    expect(FILE_TYPE_COLORS.other).toBe(FILE_TYPE_COLORS.image);
  });

  it("labels the icon band with a short extension", () => {
    expect(fileTypeLabel("a.pdf")).toBe("PDF");
    expect(fileTypeLabel("a.xlsx")).toBe("XLSX");
    expect(fileTypeLabel("a.markdown")).toBe("");
    expect(fileExtension(".env")).toBe("");
  });

  it("knows what the browser can preview", () => {
    expect(filePreviewKind("a.png")).toBe("image");
    expect(filePreviewKind("a.heic")).toBeNull();
    expect(filePreviewKind("a.pdf")).toBe("pdf");
    expect(filePreviewKind("a.csv")).toBe("csv");
    expect(filePreviewKind("a.md")).toBe("text");
    expect(filePreviewKind("a.docx")).toBeNull();
  });
});

describe("csvExcerpt", () => {
  it("reads quoted cells and limits rows and columns", () => {
    const rows = csvExcerpt(
      'name,note,a,b,c\n"Smith, J","say ""hi""",1,2,3\n\nx,y\n4,5\n6,7\n8,9',
      ",",
      4,
      4,
    );
    expect(rows).toEqual([
      ["name", "note", "a", "b"],
      ["Smith, J", 'say "hi"', "1", "2"],
      ["x", "y"],
      ["4", "5"],
    ]);
  });
});
