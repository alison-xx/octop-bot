import { useEffect, useState } from "react";
import { Alert, Button, Drawer, List } from "antd";
import { ArrowLeft, Download, Folder, Paperclip } from "lucide-react";
import { useTranslation } from "react-i18next";
import { octopBotApi, type GroupFile } from "../../api/modules/octopBot";
import { apiErrorMessage } from "../../utils/apiError";
import { saveBlobAsFile } from "../../utils/saveBlobAsFile";

export default function GroupFiles({
  id,
  onClose,
  onAttach,
}: {
  id: string;
  onClose: () => void;
  onAttach?: (path: string) => void;
}) {
  const { t } = useTranslation();
  const [dirs, setDirs] = useState(["."]);
  const [files, setFiles] = useState<GroupFile[]>([]);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState("");
  const path = dirs[dirs.length - 1];
  useEffect(() => {
    let live = true;
    setPending(true);
    setError("");
    setFiles([]);
    void octopBotApi
      .files(id, path)
      .then((next) => {
        if (live) setFiles(next);
      })
      .catch((e) => {
        if (live) setError(apiErrorMessage(e, t("octopBot.failed"), t));
      })
      .finally(() => {
        if (live) setPending(false);
      });
    return () => {
      live = false;
    };
  }, [id, path, t]);
  const open = async (file: GroupFile) => {
    if (file.is_dir) {
      setDirs((prev) => [...prev, file.path]);
      return;
    }
    try {
      await saveBlobAsFile(
        await octopBotApi.download(id, file.path),
        file.name,
      );
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    }
  };
  return (
    <Drawer open title={t("octopBot.groupFiles")} onClose={onClose}>
      {dirs.length > 1 && (
        <Button
          type="text"
          icon={<ArrowLeft size={15} />}
          onClick={() => setDirs((prev) => prev.slice(0, -1))}
        >
          {path}
        </Button>
      )}
      {error && <Alert type="error" message={error} />}
      <List
        loading={pending}
        dataSource={files}
        renderItem={(file) => (
          <List.Item
            key={file.path}
            actions={
              onAttach && !file.is_dir
                ? [
                    <Button
                      key="attach"
                      type="text"
                      icon={<Paperclip size={15} />}
                      aria-label={t("octopBot.attach", { name: file.name })}
                      onClick={() => onAttach(file.path)}
                    />,
                  ]
                : undefined
            }
          >
            <Button
              type="text"
              icon={file.is_dir ? <Folder size={16} /> : <Download size={16} />}
              onClick={() => void open(file)}
            >
              {file.name}
            </Button>
          </List.Item>
        )}
      />
    </Drawer>
  );
}
