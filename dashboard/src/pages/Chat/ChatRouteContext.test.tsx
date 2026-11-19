import { fireEvent, render, screen } from "@testing-library/react";
import { useLocation, MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { ChatRouteContext, useChatNavigate } from "./ChatRouteContext";

function OpenSession() {
  const navigate = useChatNavigate();
  const location = useLocation();
  return (
    <>
      <button onClick={() => navigate("/chat/botA/threadB")}>open</button>
      <output>{location.pathname}</output>
    </>
  );
}
describe("chat routes inside Octop Bot", () => {
  it.each([false, true])(
    "keeps both existing and newly created threads in their originating entry (%s)",
    (embedded) => {
      render(
        <MemoryRouter>
          <ChatRouteContext.Provider
            value={
              embedded
                ? {
                    basePath: "/octop-bot/bots",
                    openSide: vi.fn(),
                    openReference: vi.fn(),
                  }
                : null
            }
          >
            <OpenSession />
          </ChatRouteContext.Provider>
        </MemoryRouter>,
      );
      fireEvent.click(screen.getByText("open"));
      expect(screen.getByRole("status")).toHaveTextContent(
        embedded ? "/octop-bot/bots/botA/threadB" : "/chat/botA/threadB",
      );
    },
  );
});
