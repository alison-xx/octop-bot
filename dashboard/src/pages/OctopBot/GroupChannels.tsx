import { useEffect, useState } from "react";
import { Alert, List, Spin, Switch, Typography } from "antd";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { botGroupIm, type BotImSession } from "../../api/modules/octopBot";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { apiErrorMessage } from "../../utils/apiError";
import { canAccessPath } from "../../utils/permissions";

export function GroupChannels({ groupId }: { groupId: string }) {
  const user = useCurrentUser();
  const allowed = canAccessPath(user, "/personalization/channels");
  const { t } = useTranslation();
  const [rows, setRows] = useState<BotImSession[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!allowed) return;
    let current = true;
    setRows(null);
    setError("");
    botGroupIm
      .list(groupId)
      .then((data) => {
        if (current) setRows(data);
      })
      .catch((e) => {
        if (current) setError(apiErrorMessage(e, t("octopBot.failed"), t));
      });
    return () => {
      current = false;
    };
  }, [allowed, groupId, t]);
  async function toggle(row: BotImSession, checked: boolean) {
    setSaving(true);
    setError("");
    try {
      setRows(await botGroupIm.update(groupId, row, checked));
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setSaving(false);
    }
  }
  if (!allowed) return null;
  return (
    <section>
      <Typography.Title level={5}>{t("octopBot.imChats")}</Typography.Title>
      {error && <Alert type="error" message={error} />}
      {!rows && !error && <Spin size="small" />}
      {rows?.length === 0 && (
        <Typography.Paragraph type="secondary">
          {t("octopBot.imEmpty")}{" "}
          <Link to="/personalization/channels">{t("octopBot.imSetup")}</Link>
        </Typography.Paragraph>
      )}
      {rows && rows.length > 0 && (
        <>
          <Typography.Text type="secondary">
            {t("octopBot.imAudience")}
          </Typography.Text>
          <List
            dataSource={rows}
            renderItem={(row) => (
              <List.Item
                key={row.channel_id + ":" + row.session_key}
                actions={[
                  <Switch
                    key="link"
                    checked={row.linked}
                    disabled={saving || row.linked_elsewhere}
                    aria-label={t("octopBot.imLink", { name: row.subject })}
                    onChange={(checked) => void toggle(row, checked)}
                  />,
                ]}
              >
                <List.Item.Meta
                  title={row.subject}
                  description={[
                    row.channel_name,
                    row.platform,
                    row.linked_elsewhere ? t("octopBot.imInUse") : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                />
              </List.Item>
            )}
          />
        </>
      )}
    </section>
  );
}
