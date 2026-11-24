import { ConfigProvider, theme } from "antd";
import { useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import CloudComputerScreen from "./CloudComputerScreen";
import styles from "./cloudComputerScreen.module.less";

/**
 * `/octop-bot/screen/:agentId?ticket=…&session=…`: the phone apps open a Bot's cloud computer
 * here in their in-app browser. The one-time ticket and the screen session are the only
 * credentials; no sign-in needed.
 */
export default function CloudComputerScreenPage() {
  const { t } = useTranslation();
  const { agentId = "" } = useParams<{ agentId: string }>();
  const [query] = useSearchParams();
  const ticket = query.get("ticket") ?? "";
  const interactive = query.get("control") === "1";
  const session = query.get("session") ?? "";
  const wsPath = `/api/octop-bot/computers/${encodeURIComponent(
    agentId,
  )}/screen/ws?ticket=${encodeURIComponent(ticket)}`;
  const typing = interactive && session !== "";
  return (
    <main className={typing ? `${styles.page} ${styles.typing}` : styles.page}>
      {/* The page is dark; so are the input bar's controls under the screen. */}
      <ConfigProvider theme={{ algorithm: theme.darkAlgorithm }}>
        <CloudComputerScreen
          wsPath={wsPath}
          interactive={interactive}
          session={session}
        />
      </ConfigProvider>
      <p>
        {t(
          interactive ? "cloudComputer.controlHint" : "cloudComputer.viewHint",
        )}
      </p>
    </main>
  );
}
