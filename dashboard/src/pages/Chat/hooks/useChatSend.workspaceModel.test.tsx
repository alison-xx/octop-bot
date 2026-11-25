import { act, renderHook } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, vi, expect } from "vitest";
import i18n from "i18next";
import { useChatSend } from "./useChatSend";

describe("workspace model routing", () => {
  it.each(["ask", "plan"] as const)(
    "waits for the deep thread before sending in %s mode",
    (mode) => {
      const sendMessage = vi.fn();
      const { result, rerender } = renderHook(
        ({ ready }) =>
          useChatSend({
            activeThreadReady: ready,
            activeThreadId: "older",
            resolvedAgentId: "agent",
            conversationMode: ready ? mode : "craft",
            selectedModel: null,
            selectedConnectors: ["saved-connector"],
            selectedKnowledgeBaseIds: [],
            reasoningMode: "auto",
            reasoningEffort: null,
            defaultModel: null,
            sendMessage,
            createSession: vi.fn(),
            t: i18n.t,
          }),
        { initialProps: { ready: false }, wrapper: MemoryRouter },
      );
      expect(result.current.handleSend("continue")).toBe(false);
      expect(sendMessage).not.toHaveBeenCalled();
      rerender({ ready: true });
      expect(result.current.handleSend("continue")).toBe(true);
      expect(sendMessage.mock.calls[0][4]).toBe("older");
      expect(sendMessage.mock.calls[0][6]).toEqual([]);
      expect(sendMessage.mock.calls[0][12]).toBe(mode);
    },
  );

  it.each([true, false])(
    "honors the active source for new and previously queued sends (personal account: %s)",
    (personal) => {
      const sendMessage = vi.fn();
      const { result } = renderHook(
        () =>
          useChatSend({
            resolvedAgentId: "chief",
            activeThreadId: "thread-42",
            selectedModel: "studio/shared",
            selectedConnectors: [],
            selectedKnowledgeBaseIds: [],
            reasoningMode: "auto",
            reasoningEffort: null,
            defaultModel: "studio/default",
            useWorkspaceModel: personal,
            sendMessage,
            createSession: vi.fn(),
            t: i18n.t,
          }),
        { wrapper: MemoryRouter },
      );
      act(() => {
        result.current.handleSend("new");
        result.current.handleSend("from queue", undefined, {
          modelRef: "studio/queued",
          selectedModel: "studio/queued",
          composerContext: { model: "studio/queued", skills: ["proofread"] },
        });
      });
      expect(sendMessage.mock.calls[0][5]).toBe(
        personal ? null : "studio/shared",
      );
      expect(sendMessage.mock.calls[0][9]?.model).toBe(
        personal ? undefined : "studio/shared",
      );
      expect(sendMessage.mock.calls[1][5]).toBe(
        personal ? null : "studio/queued",
      );
      expect(sendMessage.mock.calls[1][9]?.model).toBe(
        personal ? undefined : "studio/queued",
      );
      expect(sendMessage.mock.calls[1][9]?.skills).toEqual(["proofread"]);
    },
  );
});
