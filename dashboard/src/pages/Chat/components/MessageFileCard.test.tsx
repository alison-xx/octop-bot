import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetAttachmentCache } from "../../../components/FileCard/attachmentData";
import { ChatFilePreviewProvider } from "../ChatFilePreviewContext";
import { MessageFileCard } from "./MessageFileCard";

const requestHead = vi.fn();
const requestBlob = vi.fn();

vi.mock("../../../api/request", () => ({
  requestHead: (path: string) => requestHead(path),
  requestBlob: (path: string) => requestBlob(path),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.name ? `${key}:${String(opts.name)}` : key,
  }),
}));

const AGENT = "01AGENT";
const url = (path: string) =>
  `/api/agents/${AGENT}/workspace/download?path=${encodeURIComponent(path)}`;

function headers(size: number): Headers {
  return new Headers({ "content-length": String(size) });
}

beforeEach(() => {
  resetAttachmentCache();
  requestHead.mockReset();
  requestBlob.mockReset();
  // jsdom has no object URLs.
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
});

describe("MessageFileCard", () => {
  it("shows a middle-ellipsized name that keeps the extension, and the size", async () => {
    requestHead.mockResolvedValue(headers(2 * 1024 * 1024));
    const name = "Octop-quarterly-business-review-2026-final-version.pdf";
    render(
      <MessageFileCard
        url={url(`outbound/${name}`)}
        filename={name}
        agentId={AGENT}
      />,
    );

    const button = screen.getByRole("button", {
      name: `chat.fileCardOpen:${name}`,
    });
    expect(button).toHaveAttribute("title", name);
    const shown = button.textContent ?? "";
    expect(shown).toContain("…");
    expect(shown).toContain(".pdf");
    expect(shown).not.toContain(name);
    expect(await screen.findByText("2 MB")).toBeInTheDocument();
    expect(requestHead).toHaveBeenCalledWith(
      `/agents/${AGENT}/workspace/download?path=${encodeURIComponent(
        `outbound/${name}`,
      )}`,
    );
  });

  it("colors the icon by type and shows the type when the size is unknown", async () => {
    requestHead.mockRejectedValue(new Error("Request failed: 405"));
    const { container } = render(
      <MessageFileCard
        url={url("outbound/dec2026.csv")}
        filename="dec2026.csv"
        agentId={AGENT}
      />,
    );
    await waitFor(() => expect(requestHead).toHaveBeenCalled());
    // The band label and the meta line both say CSV.
    expect(await screen.findAllByText("CSV")).toHaveLength(2);
    const icon = container.querySelector("svg[data-kind]");
    expect(icon).toHaveAttribute("data-kind", "excel");
    expect(container.querySelector('rect[fill="#1F9D55"]')).not.toBeNull();
  });

  it("opens the preview panel on click and downloads from the button", async () => {
    requestHead.mockResolvedValue(headers(300));
    requestBlob.mockResolvedValue(new Blob(["x"]));
    const openFilePreview = vi.fn();
    render(
      <ChatFilePreviewProvider
        openFilePreview={openFilePreview}
        openKnowledgeCitation={vi.fn()}
      >
        <MessageFileCard
          url={url("outbound/memo.docx")}
          filename="memo.docx"
          agentId={AGENT}
        />
      </ChatFilePreviewProvider>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "chat.fileCardOpen:memo.docx" }),
    );
    expect(openFilePreview).toHaveBeenCalledWith("outbound/memo.docx", AGENT);
    expect(await screen.findByText("300 B")).toBeInTheDocument();
  });

  it("renders a small image as the card itself in rich mode", async () => {
    requestHead.mockResolvedValue(headers(40_000));
    requestBlob.mockResolvedValue(new Blob(["png"], { type: "image/png" }));
    const { container } = render(
      <MessageFileCard
        url={url("outbound/chart.png")}
        filename="chart.png"
        agentId={AGENT}
        rich
      />,
    );
    const img = await screen.findByRole("img", { name: "chart.png" });
    expect(img).toHaveAttribute("src", "blob:x");
    // No document glyph or file row: the picture is the card.
    expect(container.querySelector("svg[data-kind]")).toBeNull();
    expect(
      screen.getByRole("button", { name: "chat.fileCardDownload:chart.png" }),
    ).toBeInTheDocument();
  });

  it("keeps the plain file card for previewable files without rich mode", async () => {
    requestHead.mockResolvedValue(headers(40_000));
    const { container } = render(
      <MessageFileCard
        url={url("outbound/chart.png")}
        filename="chart.png"
        agentId={AGENT}
      />,
    );
    expect(await screen.findByText("39 KB")).toBeInTheDocument();
    expect(container.querySelector("svg[data-kind='image']")).not.toBeNull();
    expect(requestBlob).not.toHaveBeenCalled();
  });

  // The preview is a decorative (aria-hidden) twin of the labelled file row.
  it("shows a CSV excerpt in rich mode", async () => {
    requestHead.mockResolvedValue(headers(30));
    requestBlob.mockResolvedValue(new Blob(["month,total\nJan,12\nFeb,15\n"]));
    render(
      <MessageFileCard
        url={url("outbound/dec2026.csv")}
        filename="dec2026.csv"
        agentId={AGENT}
        rich
      />,
    );
    expect(
      await screen.findByRole("columnheader", { name: "month", hidden: true }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("cell", { name: "15", hidden: true }),
    ).toBeInTheDocument();
    expect(screen.getByText("30 B")).toBeInTheDocument();
  });

  it("skips the preview for files too large to thumbnail", async () => {
    requestHead.mockResolvedValue(headers(50 * 1024 * 1024));
    render(
      <MessageFileCard
        url={url("outbound/big.pdf")}
        filename="big.pdf"
        agentId={AGENT}
        rich
      />,
    );
    expect(await screen.findByText("50 MB")).toBeInTheDocument();
    expect(requestBlob).not.toHaveBeenCalled();
  });
});
