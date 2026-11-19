import { useEffect, useState } from "react";
import { Alert, Button, Drawer, List, Popconfirm } from "antd";
import { useTranslation } from "react-i18next";
import { octopBotApi, type RetainedFolder } from "../../api/modules/octopBot";
import { apiErrorMessage } from "../../utils/apiError";

export default function RetainedFolders({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const [folders, setFolders] = useState<RetainedFolder[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    void octopBotApi
      .retainedFolders()
      .then((rows) => {
        if (live) setFolders(rows);
      })
      .catch((e) => {
        if (live) setError(apiErrorMessage(e, t("octopBot.failed"), t));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [t]);
  const release = async (id: string) => {
    setWorking(id);
    setError("");
    try {
      await octopBotApi.releaseFolder(id);
      setFolders((prev) => prev.filter((row) => row.agent_id !== id));
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setWorking("");
    }
  };
  return (
    <Drawer open title={t("octopBot.retainedFolders")} onClose={onClose}>
      {error && <Alert type="error" message={error} />}
      <List
        loading={loading}
        dataSource={folders}
        renderItem={(folder) => (
          <List.Item
            key={folder.agent_id}
            actions={[
              <Popconfirm
                key="release"
                title={t("octopBot.releaseFolderConfirm")}
                onConfirm={() => release(folder.agent_id)}
              >
                <Button
                  type="link"
                  loading={working === folder.agent_id}
                  disabled={!!working}
                >
                  {t("octopBot.releaseFolder")}
                </Button>
              </Popconfirm>,
            ]}
          >
            <List.Item.Meta title={folder.name} description={folder.path} />
          </List.Item>
        )}
      />
    </Drawer>
  );
}
