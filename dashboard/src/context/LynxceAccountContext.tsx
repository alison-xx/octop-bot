import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { botCloudApi, type CloudAccount } from "../api/modules/botCloud";
import { isBotOnlyDesktop } from "../utils/desktopBridge";
import { useBotServerInfo } from "../pages/OctopBot/useBotServerInfo";
import { AUTH_TOKEN_KEY, getAuthToken } from "../api/request";
import { subjectOf } from "../api/desktopSession";

const Account = createContext<CloudAccount | null>(null);

function sessionOwner() {
  const token = getAuthToken();
  return subjectOf(token) ?? token;
}

export function useLynxceAccount() {
  return useContext(Account);
}

/** A single identity for every view belonging to this authenticated session. */
export function LynxceAccountProvider({ children }: { children: ReactNode }) {
  const [owner] = useState(sessionOwner);
  const [account, setAccount] = useState<CloudAccount | null>(null);
  const edition = useBotServerInfo()?.edition;
  const enabled = isBotOnlyDesktop() || edition === "cloud";
  useEffect(() => {
    if (!enabled) return;
    let request = 0;
    const refresh = () => {
      const current = ++request;
      if (owner !== sessionOwner()) {
        setAccount(null);
        return;
      }
      void botCloudApi.account().then(
        (value) => {
          if (current === request) {
            setAccount(
              owner === sessionOwner() && value.connected ? value : null,
            );
          }
        },
        () => {
          if (current === request) setAccount(null);
        },
      );
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key !== AUTH_TOKEN_KEY && event.key !== null) return;
      if (
        event.key === AUTH_TOKEN_KEY &&
        getAuthToken() !== (event.newValue ?? "")
      )
        return;
      const previous = subjectOf(event.oldValue ?? "");
      if (previous && previous === subjectOf(event.newValue ?? "")) return;
      ++request;
      setAccount(null);
      window.location.reload();
    };
    refresh();
    window.addEventListener("storage", onStorage);
    window.addEventListener("focus", refresh);
    return () => {
      ++request;
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("focus", refresh);
    };
  }, [enabled, owner]);
  return (
    <Account.Provider value={enabled ? account : null}>
      {children}
    </Account.Provider>
  );
}
