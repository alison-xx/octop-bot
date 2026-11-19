import { createContext, useCallback, useContext } from "react";
import { useNavigate, type NavigateOptions } from "react-router-dom";

export const ChatRouteContext = createContext<{
  basePath: string;
  recipient?: { id: string; name: string };
  isChief?: boolean;
  openSide: (question: string) => void;
  openReference: (insert: (text: string) => void) => void;
  renderAvatar?: (
    agentId: string | null | undefined,
    size: number,
    working: boolean,
  ) => React.ReactNode;
} | null>(null);

export const useEmbeddedChat = () => useContext(ChatRouteContext);
export const QuoteMessageContext = createContext<
  ((quote: string) => void) | null
>(null);

/** Keep existing thread actions inside the workspace that mounted the chat. */
export function useChatNavigate() {
  const navigate = useNavigate();
  const basePath = useEmbeddedChat()?.basePath ?? "/chat";
  return useCallback(
    (to: string, options?: NavigateOptions) =>
      navigate(to.startsWith("/chat/") ? basePath + to.slice(5) : to, options),
    [navigate, basePath],
  );
}
