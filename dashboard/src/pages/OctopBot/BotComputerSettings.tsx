import { useEffect, useState } from "react";
import { Alert, Button, Drawer, Form, Select, Space, Spin, Tag } from "antd";
import { Monitor } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  botComputerApi as api,
  type ComputerApp,
  type ComputerLevel,
  type ComputerState,
} from "../../api/modules/botComputer";
import { apiErrorMessage } from "../../utils/apiError";

export default function BotComputerSettings({ botId }: { botId: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<ComputerState | null>(null);
  const [apps, setApps] = useState<ComputerApp[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [level, setLevel] = useState<ComputerLevel>("off");
  const [ids, setIds] = useState<string[]>([]);
  const monitor = state != null && state.level !== "off";
  useEffect(() => {
    let current = true;
    const read = () =>
      api
        .state(botId)
        .then((next) => {
          if (current) setState(next);
        })
        .catch((e) => {
          if (current) setError(apiErrorMessage(e, t("octopBot.failed"), t));
        });
    void read();
    const timer = monitor
      ? window.setInterval(() => {
          if (document.visibilityState === "visible") void read();
        }, 2000)
      : undefined;
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, [botId, monitor, t]);
  useEffect(() => {
    if (!open) return;
    let current = true;
    Promise.all([api.state(botId), api.apps(botId)])
      .then(([now, candidates]) => {
        if (!current) return;
        setState(now);
        setLevel(now.level);
        setIds(now.apps.map((a) => a.id));
        setApps([
          ...new Map(
            [...now.apps, ...candidates].map((a) => [a.id, a]),
          ).values(),
        ]);
      })
      .catch((e) => {
        if (current) setError(apiErrorMessage(e, t("octopBot.failed"), t));
      });
    return () => {
      current = false;
    };
  }, [botId, open, t]);
  async function update(operation: Promise<ComputerState>) {
    setBusy(true);
    setError("");
    try {
      setState(await operation);
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setBusy(false);
    }
  }
  const label = t("octopBot.computer.title");
  return (
    <>
      {state?.active_app && <Tag color="processing">{state.active_app}</Tag>}
      <Button
        type="text"
        title={label}
        aria-label={label}
        icon={<Monitor size={17} />}
        onClick={() => {
          setError("");
          setOpen(true);
        }}
      />
      {state && state.level !== "off" && (
        <Button
          size="small"
          loading={busy}
          onClick={() => void update(api.pause(botId, !state.paused))}
        >
          {t(
            state.paused
              ? "octopBot.computer.resume"
              : "octopBot.computer.takeover",
          )}
        </Button>
      )}
      <Drawer open={open} title={label} onClose={() => setOpen(false)}>
        {error && <Alert type="error" message={error} />}
        {!state && !error && <Spin />}
        {state && !state.available && (
          <Alert type="info" message={t("octopBot.computer.unavailable")} />
        )}
        {state?.available && (
          <Form layout="vertical">
            <Form.Item label={t("octopBot.computer.level")}>
              <Select
                value={level}
                onChange={setLevel}
                options={["off", "view", "background", "foreground"].map(
                  (v) => ({ value: v, label: t("octopBot.computer." + v) }),
                )}
              />
            </Form.Item>
            <Form.Item label={t("octopBot.computer.apps")}>
              <Select
                mode="multiple"
                showSearch
                optionFilterProp="label"
                value={ids}
                onChange={setIds}
                options={apps.map((a) => ({ value: a.id, label: a.name }))}
              />
            </Form.Item>
            <Space>
              <Button
                type="primary"
                loading={busy}
                onClick={() => void update(api.save(botId, level, ids))}
              >
                {t("common.save")}
              </Button>
            </Space>
          </Form>
        )}
      </Drawer>
    </>
  );
}
