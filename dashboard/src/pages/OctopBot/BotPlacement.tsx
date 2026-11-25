import { useEffect, useState, useSyncExternalStore } from "react";
import { Select } from "antd";
import { useTranslation } from "react-i18next";
import {
  botPlacement,
  type ComputerLocations,
  type Placement,
} from "../../api/modules/botPlacement";
import {
  choosePlacement,
  clearPlacement,
  readPlacement,
  subscribePlacement,
} from "../Chat/placementDraft";
import { useBotServerInfo } from "./useBotServerInfo";

export default function BotPlacement({
  bot,
  defaults = false,
}: {
  bot: string;
  defaults?: boolean;
}) {
  const { t } = useTranslation();
  const cloud = useBotServerInfo()?.edition === "cloud";
  const [locations, setLocations] = useState<ComputerLocations | null>(null);
  const [error, setError] = useState(false);
  const [saving, setSaving] = useState(false);
  const selected = useSyncExternalStore(subscribePlacement, () =>
    readPlacement(bot),
  );
  useEffect(() => {
    if (!cloud) return;
    let alive = true;
    let busy = false;
    const refresh = async () => {
      if (document.hidden || busy) return;
      busy = true;
      try {
        const state = await botPlacement.get(bot);
        if (alive) setLocations(state);
      } catch {
        if (alive) setLocations(null);
      } finally {
        busy = false;
      }
    };
    void refresh();
    const timer = setInterval(refresh, 15000);
    window.addEventListener("focus", refresh);
    return () => {
      alive = false;
      window.removeEventListener("focus", refresh);
      clearInterval(timer);
      if (!defaults) clearPlacement(readPlacement(bot));
    };
  }, [bot, cloud, defaults]);
  if (
    !locations ||
    (!Object.keys(locations.devices).length &&
      locations.default !== "local" &&
      !selected)
  )
    return null;

  const save = async (value: Placement) => {
    if (!defaults) {
      choosePlacement(bot, value);
      return;
    }
    setError(false);
    setSaving(true);
    try {
      const result = await botPlacement.save(bot, value);
      setLocations({ ...locations, default: result.default });
    } catch {
      setError(true);
    } finally {
      setSaving(false);
    }
  };
  const label = t(
    defaults ? "computerPlacement.default" : "computerPlacement.turn",
  );
  return (
    <label>
      {label}{" "}
      <Select<Placement>
        size="small"
        aria-label={label}
        loading={saving}
        disabled={saving}
        value={(!defaults && selected?.value) || locations.default}
        options={(["auto", "cloud", "local"] as const).map((value) => ({
          value,
          label: t("computerPlacement." + value),
        }))}
        onChange={save}
      />
      {error && <span role="alert">{t("computerPlacement.failed")}</span>}
    </label>
  );
}
