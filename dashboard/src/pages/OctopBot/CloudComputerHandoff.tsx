import { useState } from "react";
import { Button, Modal } from "antd";
import { Monitor } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  botCloudComputerApi,
  viewOnlyScreen,
  type ScreenSession,
} from "../../api/modules/botCloudComputer";
import { apiErrorMessage } from "../../utils/apiError";
import { expandForHandoff } from "./CloudComputerFloat";
import CloudComputerScreen from "./CloudComputerScreen";

/**
 * The Bot asked for a takeover (`request_takeover`): one button takes the computer over and
 * opens its screen. Answering the question card hands it back and lets the Bot continue.
 */
export default function CloudComputerHandoff({ botId }: { botId: string }) {
  const { t } = useTranslation();
  const [screen, setScreen] = useState<{
    ws: string;
    session: ScreenSession;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const open = async () => {
    setBusy(true);
    setError("");
    try {
      const ticket = await botCloudComputerApi.openScreen(botId);
      const status = viewOnlyScreen(ticket.session)
        ? null
        : await botCloudComputerApi.takeover(botId, true);
      if (expandForHandoff(botId, status, ticket)) return;
      setScreen({ ws: ticket.ws_path, session: ticket.session });
    } catch (e) {
      setError(apiErrorMessage(e, t("cloudComputer.unavailable"), t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Button
        type="primary"
        icon={<Monitor size={15} />}
        loading={busy}
        onClick={() => void open()}
      >
        {t("cloudComputer.handoffOpen")}
      </Button>
      {error && <span role="alert">{error}</span>}
      <Modal
        open={screen !== null}
        title={t("cloudComputer.section")}
        width={960}
        footer={
          <span>
            {t(
              viewOnlyScreen(screen?.session)
                ? "cloudComputer.legacyViewOnly"
                : "cloudComputer.handoffHint",
            )}
          </span>
        }
        onCancel={() => setScreen(null)}
        destroyOnClose
      >
        {screen && (
          <CloudComputerScreen
            botId={botId}
            wsPath={screen.ws}
            interactive={!viewOnlyScreen(screen.session)}
            session={screen.session}
          />
        )}
      </Modal>
    </>
  );
}
