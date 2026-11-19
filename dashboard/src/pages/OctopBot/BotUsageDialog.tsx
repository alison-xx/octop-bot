import { useEffect, useState } from "react";
import { Alert, Button, Empty, Modal, Segmented, Spin } from "antd";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  getBotUsage,
  type BotUsageSummary,
  type UsageWindow,
} from "../../api/modules/botUsage";
import { apiErrorMessage } from "../../utils/apiError";
import { UsageStats } from "../Control/TokenUsage/UsageStats";
import {
  formatExactCount,
  usageCountDisplay,
} from "../Control/TokenUsage/formatUsageCount";
import styles from "./BotActivity.module.less";

export default function BotUsageDialog({
  agentId,
  name,
  onClose,
}: {
  agentId: string;
  name: string;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [period, setPeriod] = useState<UsageWindow>("last_7d");
  const [revision, setRevision] = useState(0);
  const [summary, setSummary] = useState<BotUsageSummary | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    setSummary(null);
    setError("");
    getBotUsage(agentId, period)
      .then((data) => {
        if (current) setSummary(data);
      })
      .catch((err) => {
        if (current) setError(apiErrorMessage(err, t("octopBot.failed"), t));
      });
    return () => {
      current = false;
    };
  }, [agentId, period, revision, t]);
  const periods = {
    today: "today",
    last_7d: "last7d",
    last_30d: "last30d",
    all: "allTime",
  } as const;
  const stats = [
    ["total_tokens", "tokenUsage.totalTokens"],
    ["model_calls", "tokenUsage.modelCalls"],
    ["input_tokens", "tokenUsage.input"],
    ["output_tokens", "tokenUsage.output"],
  ] as const;
  return (
    <Modal
      open
      centered
      title={t("botClient.activity.usageTitle", { name })}
      onCancel={onClose}
      footer={null}
      width={510}
    >
      <div className={styles.body}>
        <p className={styles.hint}>{t("botClient.activity.usageScope")}</p>
        <div className={styles.toolbar}>
          <Segmented
            aria-label={t("botClient.activity.period")}
            value={period}
            options={Object.entries(periods).map(([value, key]) => ({
              value,
              label: t("tokenUsage." + key),
            }))}
            onChange={(value) => setPeriod(value as UsageWindow)}
          />
          <Button
            aria-label={t("common.refresh")}
            title={t("common.refresh")}
            icon={<RefreshCw size={14} />}
            disabled={summary === null}
            onClick={() => setRevision((n) => n + 1)}
          />
        </div>
        {error ? (
          <Alert
            type="error"
            showIcon
            message={error}
            action={
              <Button onClick={() => setRevision((r) => r + 1)}>
                {t("common.retry")}
              </Button>
            }
          />
        ) : !summary ? (
          <Spin />
        ) : summary.turns === 0 &&
          summary.model_calls === 0 &&
          summary.total_tokens === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("botClient.activity.noUsage")}
          />
        ) : (
          <>
            <UsageStats
              overflowEnabled={false}
              items={stats.map(([key, label]) => ({
                key,
                label: t(label),
                ...usageCountDisplay(summary[key], i18n.language),
              }))}
            />
            {summary.buckets.length > 0 && (
              <section>
                <h3>{t("tokenUsage.byModel")}</h3>
                <ul className={styles.rows}>
                  {summary.buckets.map((m) => (
                    <li key={m.key}>
                      <span>{m.label || m.key}</span>
                      <b>{formatExactCount(m.total_tokens, i18n.language)}</b>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
