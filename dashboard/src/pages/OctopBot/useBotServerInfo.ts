import { useEffect, useState } from "react";
import {
  botCloudComputerApi,
  type BotServerInfo,
} from "../../api/modules/botCloudComputer";

let pending: Promise<BotServerInfo | null> | null = null;

/** Share concurrent reads. Desktop capabilities depend on the current Lynxce session. */
export function useBotServerInfo(): BotServerInfo | null {
  const [info, setInfo] = useState<BotServerInfo | null>(null);
  useEffect(() => {
    let version = 0;
    function refresh() {
      const request = ++version;
      pending ??= Promise.resolve()
        .then(() => botCloudComputerApi.serverInfo())
        .catch(() => null)
        .finally(() => {
          pending = null;
        });
      void pending.then((value) => {
        if (request === version) setInfo(value);
      });
    }
    refresh();
    window.addEventListener("focus", refresh);
    window.addEventListener("octop-bot-account-changed", refresh);
    return () => {
      version++;
      window.removeEventListener("focus", refresh);
      window.removeEventListener("octop-bot-account-changed", refresh);
    };
  }, []);
  return info;
}
