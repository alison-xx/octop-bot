import { useRef, useState } from "react";
import { Alert, Button, Form, Input, Modal } from "antd";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useTranslation } from "react-i18next";
import { octopAgentsApi } from "../../api/modules/octopAgents";
import { apiErrorMessage } from "../../utils/apiError";
import { AppearancePicker, type AppearanceChoice } from "./AppearancePicker";
import { BotCharacter } from "./BotCharacter";
import styles from "./createForms.module.less";

interface Fields {
  name: string;
  role: string;
}

const examples = [
  { id: "notes", shape: "acorn", color: "green" },
  { id: "research", shape: "saucer", color: "sky" },
  { id: "editor", shape: "moon", color: "violet" },
] as const;
type Example = (typeof examples)[number];

export default function BotQuickCreate({
  choice,
  onChoose,
  onClose,
  onCreated,
}: {
  choice: AppearanceChoice | null;
  onChoose: (choice: AppearanceChoice) => void;
  onClose: () => void;
  onCreated: (id: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [form] = Form.useForm<Fields>();
  const [showLook, setShowLook] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [lastExample, setLastExample] = useState<Fields | null>(null);
  const [pending, setPending] = useState<Example | null>(null);
  const customLook = useRef(Boolean(choice));
  const submitting = useRef(false);
  const applyExample = (example: Example, replace = false) => {
    const fields = form.getFieldsValue();
    const next = {
      name: t(`botForms.${example.id}.name`),
      role: t(`botForms.${example.id}.role`),
    };
    const edited = (["name", "role"] as const).some(
      (key) =>
        fields[key]?.trim() &&
        fields[key] !== lastExample?.[key] &&
        fields[key] !== next[key],
    );
    if (edited && !replace) {
      setPending(example);
      return;
    }
    setPending(null);
    setLastExample(next);
    form.setFieldsValue(next);
    if (!customLook.current)
      onChoose({
        kind: "character",
        shape: example.shape,
        color: example.color,
      });
  };
  const save = async ({ name, role }: Fields) => {
    if (submitting.current) return;
    submitting.current = true;
    setSaving(true);
    setError("");
    try {
      const created = await octopAgentsApi.createTeammate(
        name.trim(),
        role.trim(),
      );
      await onCreated(created.agent_id);
    } catch (e) {
      setError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  };
  return (
    <Modal
      open
      centered
      title={t("octopBot.newBot")}
      width={560}
      className={styles.dialog}
      onOk={() => form.submit()}
      okText={t("common.create")}
      confirmLoading={saving}
      onCancel={saving ? undefined : onClose}
      closable={!saving}
      maskClosable={!saving}
      cancelButtonProps={{ disabled: saving }}
    >
      <div className={styles.exampleLabel} id="bot-example-title">
        {t("botForms.examples")}
      </div>
      <div
        className={styles.examples}
        role="group"
        aria-labelledby="bot-example-title"
      >
        {examples.map((example) => (
          <button
            key={example.id}
            type="button"
            disabled={saving}
            className={styles.example}
            onClick={() => applyExample(example)}
          >
            <BotCharacter
              size={31}
              badges={false}
              look={{
                shape: example.shape,
                color: example.color,
                source: "character",
              }}
            />
            <strong>{t(`botForms.${example.id}.name`)}</strong>
            <span>{t(`botForms.${example.id}.summary`)}</span>
          </button>
        ))}
      </div>
      {pending && (
        <div className={styles.replace} role="status">
          <span>
            {t("botForms.replaceDraft", {
              name: t(`botForms.${pending.id}.name`),
            })}
          </span>
          <div>
            <Button size="small" onClick={() => setPending(null)}>
              {t("botForms.keepDraft")}
            </Button>
            <Button size="small" onClick={() => applyExample(pending, true)}>
              {t("botForms.applyExample")}
            </Button>
          </div>
        </div>
      )}
      <Form
        form={form}
        layout="vertical"
        onFinish={save}
        disabled={saving}
        onValuesChange={() => setPending(null)}
      >
        <Form.Item
          label={t("octopBot.name")}
          name="name"
          rules={[{ required: true, whitespace: true }]}
        >
          <Input autoFocus autoComplete="off" maxLength={80} />
        </Form.Item>
        <Form.Item
          label={t("botClient.createRole")}
          name="role"
          rules={[{ required: true, whitespace: true }]}
        >
          <Input.TextArea
            autoSize={{ minRows: 3, maxRows: 6 }}
            placeholder={t("botClient.createRoleHint")}
            maxLength={2000}
          />
        </Form.Item>
      </Form>
      <Button
        type="text"
        aria-expanded={showLook}
        disabled={saving}
        onClick={() => setShowLook(!showLook)}
        icon={showLook ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
      >
        {t("botClient.chooseAppearance")}
      </Button>
      {showLook && (
        <fieldset
          className={styles.look}
          disabled={saving}
          aria-label={t("botClient.chooseAppearance")}
        >
          <AppearancePicker
            value={choice}
            onChange={(look) => {
              customLook.current = true;
              onChoose(look);
            }}
          />
        </fieldset>
      )}
      {error && <Alert showIcon type="error" message={error} />}
    </Modal>
  );
}
