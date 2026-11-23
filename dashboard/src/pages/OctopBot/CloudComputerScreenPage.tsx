import { useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import CloudComputerScreen from "./CloudComputerScreen";
import styles from "./cloudComputerScreen.module.less";

/**
 * `/octop-bot/screen/:agentId?ticket=…`: the phone apps open a Bot's cloud computer here in
 * their in-app browser. The one-time ticket is the only credential; no sign-in needed.
 */
export default function CloudComputerScreenPage() {
  const { t } = useTranslation();
  const { agentId = "" } = useParams<{ agentId: string }>();
  const [query] = useSearchParams();
  const ticket = query.get("ticket") ?? "";
  const interactive = query.get("control") === "1";
  const wsPath = `/api/octop-bot/computers/${encodeURIComponent(
    agentId,
  )}/screen/ws?ticket=${encodeURIComponent(ticket)}`;
  return (
    <main className={styles.page}>
      <CloudComputerScreen wsPath={wsPath} interactive={interactive} />
      <p>
        {t(
          interactive ? "cloudComputer.controlHint" : "cloudComputer.viewHint",
        )}
      </p>
    </main>
  );
}
