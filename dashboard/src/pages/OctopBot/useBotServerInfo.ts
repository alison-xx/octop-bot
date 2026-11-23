import { useEffect, useState } from "react";
import {
  botCloudComputerApi,
  type BotServerInfo,
} from "../../api/modules/botCloudComputer";

let cached: Promise<BotServerInfo | null> | null = null;

/** This server's edition and capabilities, read once per page load. */
export function useBotServerInfo(): BotServerInfo | null {
  const [info, setInfo] = useState<BotServerInfo | null>(null);
  useEffect(() => {
    let mounted = true;
    cached ??= Promise.resolve()
      .then(() => botCloudComputerApi.serverInfo())
      .then((value) => value ?? null)
      .catch(() => null);
    void cached.then((value) => mounted && setInfo(value));
    return () => {
      mounted = false;
    };
  }, []);
  return info;
}
