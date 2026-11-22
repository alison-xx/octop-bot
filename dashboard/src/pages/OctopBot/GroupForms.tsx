import { useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Form,
  Input,
  Modal,
  Select,
  Space,
} from "antd";
import { Plus, Search, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  octopBotApi,
  type BotGroup,
  type GroupGoal,
  type WorkspaceBot,
} from "../../api/modules/octopBot";
import { apiErrorMessage } from "../../utils/apiError";
import { isBotClient } from "../../utils/desktopBridge";
import { GroupChannels } from "./GroupChannels";
import { BotCharacter } from "./BotCharacter";
import createStyles from "./createForms.module.less";
import styles from "./index.module.less";

type GroupFields = Omit<BotGroup, "group_id">;

export interface GroupSeed {
  name?: string;
  memberIds: string[];
  replyMode?: BotGroup["reply_mode"];
}

export function canInviteBot(bot: WorkspaceBot) {
  return bot.can_join_group ?? !bot.is_private;
}

interface MemberOption {
  value: string;
  label: string;
  role: string;
  bot: WorkspaceBot;
  duplicate: boolean;
}

function MemberIdentity({
  option,
  admin,
}: {
  option: MemberOption;
  admin?: boolean;
}) {
  return (
    <span className={createStyles.identity}>
      <BotCharacter bot={option.bot} size={28} admin={admin} />
      <span className={createStyles.memberText}>
        <span>
          {option.label}
          {option.duplicate && <small> · {option.value}</small>}
        </span>
        <small title={option.role}>{option.role}</small>
      </span>
    </span>
  );
}

function matchesMember(query: string, option: MemberOption) {
  const needle = query.trim().toLocaleLowerCase();
  return [option.label, option.role, option.value].some((text) =>
    text.toLocaleLowerCase().includes(needle),
  );
}

function MemberList({
  value = [],
  onChange,
  options,
  admin,
  disabled,
  id,
}: {
  value?: string[];
  onChange?: (value: string[]) => void;
  options: MemberOption[];
  admin?: string;
  disabled: boolean;
  id?: string;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const adminOption = options.find((option) => option.value === admin);
  const matches = options.filter((option) => matchesMember(search, option));
  const results = adminOption
    ? [adminOption, ...matches.filter((option) => option !== adminOption)]
    : matches;
  const selected = new Set(value);
  if (admin) selected.add(admin);
  return (
    <div className={createStyles.members}>
      <div className={createStyles.searchRow}>
        <Input
          allowClear
          id={id}
          prefix={<Search size={15} />}
          value={search}
          disabled={disabled}
          placeholder={t("botForms.searchMembers")}
          aria-label={t("botForms.searchMembers")}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span>{t("botForms.selected", { count: selected.size })}</span>
      </div>
      <div
        className={createStyles.roster}
        role="group"
        aria-label={t("octopBot.members")}
      >
        {results.map((option) => {
          const isAdmin = option.value === admin;
          return (
            <Checkbox
              key={option.value}
              checked={selected.has(option.value)}
              disabled={disabled || isAdmin}
              onChange={(e) =>
                onChange?.(
                  e.target.checked
                    ? [...selected, option.value]
                    : [...selected].filter((id) => id !== option.value),
                )
              }
            >
              <MemberIdentity option={option} admin={isAdmin} />
              {isAdmin && (
                <span className={createStyles.admin}>
                  {t("octopBot.admin")}
                </span>
              )}
            </Checkbox>
          );
        })}
        {!matches.length && (
          <div role="status" className={createStyles.empty}>
            {t("botForms.noMembers")}
          </div>
        )}
      </div>
    </div>
  );
}

export function GroupForm({
  bots,
  group,
  chiefId,
  seed,
  onClose,
  onSaved,
}: {
  bots: WorkspaceBot[];
  group?: BotGroup;
  chiefId: string;
  seed?: GroupSeed;
  onClose: () => void;
  onSaved: (group: BotGroup) => void;
}) {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [form] = Form.useForm<GroupFields>();
  const submitting = useRef(false);
  const admin = Form.useWatch("admin_id", form);
  const eligible = bots.filter(canInviteBot);
  const eligibleIds = new Set(eligible.map((bot) => bot.agent_id));
  const invited = [...new Set(seed?.memberIds)].filter((id) =>
    eligibleIds.has(id),
  );
  const firstAdmin = seed ? invited[0] : chiefId;
  const counts = new Map<string, number>();
  const nameKey = (name: string) => name.trim().toLocaleLowerCase();
  for (const { name } of eligible)
    counts.set(nameKey(name), (counts.get(nameKey(name)) ?? 0) + 1);
  const options: MemberOption[] = eligible.map((bot) => ({
    label: bot.name,
    value: bot.agent_id,
    bot,
    role:
      bot.description?.trim() ||
      t(bot.is_main ? "botDirectory.coordinator" : "botDirectory.teammate"),
    duplicate: (counts.get(nameKey(bot.name)) ?? 0) > 1,
  }));
  const save = async (values: GroupFields) => {
    if (submitting.current) return;
    submitting.current = true;
    setSaving(true);
    setError("");
    const body = {
      ...values,
      name: values.name.trim(),
      member_ids: [...new Set([values.admin_id, ...(values.member_ids ?? [])])],
    };
    try {
      onSaved(
        group
          ? await octopBotApi.updateGroup(group.group_id, body)
          : await octopBotApi.createGroup(body),
      );
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
      width={540}
      className={createStyles.dialog}
      title={t(group ? "octopBot.groupSettings" : "octopBot.newGroup")}
      okText={t(group ? "octopBot.save" : "common.create")}
      onOk={() => form.submit()}
      confirmLoading={saving}
      onCancel={saving ? undefined : onClose}
      closable={!saving}
      maskClosable={!saving}
      cancelButtonProps={{ disabled: saving }}
    >
      <Form
        form={form}
        layout="vertical"
        disabled={saving}
        onFinish={(values) => void save(values)}
        initialValues={
          group
            ? {
                ...group,
                member_ids: [...new Set([group.admin_id, ...group.member_ids])],
              }
            : {
                name: seed?.name?.slice(0, 120),
                admin_id: firstAdmin,
                member_ids: seed ? invited : chiefId ? [chiefId] : [],
                reply_mode: seed?.replyMode ?? "admin_first",
              }
        }
      >
        <Form.Item
          name="name"
          label={t("octopBot.name")}
          rules={[{ required: true, whitespace: true }]}
        >
          <Input maxLength={120} autoFocus />
        </Form.Item>
        <Form.Item
          name="admin_id"
          label={t("octopBot.admin")}
          rules={[{ required: true }]}
        >
          <Select
            showSearch
            options={options}
            filterOption={(q, opt) => !!opt && matchesMember(q, opt)}
            optionRender={(opt) => <MemberIdentity option={opt.data} />}
            labelRender={(opt) => {
              const member = options.find((item) => item.value === opt.value);
              return member?.duplicate
                ? `${member.label} · ${member.value}`
                : opt.label;
            }}
            onChange={(id: string) => {
              const members: string[] = form.getFieldValue("member_ids") ?? [];
              if (!members.includes(id))
                form.setFieldValue("member_ids", [...members, id]);
            }}
          />
        </Form.Item>
        <Form.Item
          name="member_ids"
          label={t("octopBot.members")}
          rules={[
            { type: "array", max: 64, message: t("botForms.memberLimit") },
          ]}
        >
          <MemberList options={options} admin={admin} disabled={saving} />
        </Form.Item>
        <Form.Item name="reply_mode" label={t("octopBot.replyMode")}>
          <Select
            options={["admin_first", "all_members"].map((value) => ({
              value,
              label: t("octopBot." + value),
            }))}
          />
        </Form.Item>
        {error && <Alert type="error" showIcon message={error} />}
      </Form>
      {group && !isBotClient() && (
        <GroupChannels key={group.group_id} groupId={group.group_id} />
      )}
    </Modal>
  );
}

export function GoalForm({
  group,
  bots,
  goal,
  onClose,
  onSaved,
}: {
  group: BotGroup;
  bots: WorkspaceBot[];
  goal: GroupGoal | null;
  onClose: () => void;
  onSaved: (value: GroupGoal) => void;
}) {
  const { t } = useTranslation();
  const [form] = Form.useForm<GroupGoal>();
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const submitting = useRef(false);
  const options = bots
    .filter((bot) => group.member_ids.includes(bot.agent_id))
    .map((bot) => ({ label: bot.name, value: bot.agent_id }));
  const statusOptions = (statuses: string[]) =>
    statuses.map((value) => ({ value, label: t("octopBot." + value) }));
  const save = async (values: GroupGoal) => {
    // Enter in a field can resubmit while the first save is still in flight.
    if (submitting.current) return;
    submitting.current = true;
    setSaving(true);
    setError("");
    try {
      onSaved(
        await octopBotApi.saveGoal(group.group_id, {
          ...values,
          stages: (values.stages ?? []).map((stage) => ({
            ...stage,
            assignee_id: stage.assignee_id ?? null,
            evidence: stage.evidence ?? "",
          })),
        }),
      );
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
      width={560}
      title={t("octopBot.goal")}
      onCancel={saving ? undefined : onClose}
      closable={!saving}
      maskClosable={!saving}
      cancelButtonProps={{ disabled: saving }}
      onOk={() => form.submit()}
      okText={t("octopBot.save")}
      confirmLoading={saving}
    >
      <Form
        layout="vertical"
        form={form}
        disabled={saving}
        onFinish={(values) => void save(values)}
        initialValues={
          goal ?? { title: "", criteria: "", status: "draft", stages: [] }
        }
      >
        <Form.Item
          name="title"
          label={t("octopBot.goalTitle")}
          rules={[{ required: true, whitespace: true }]}
        >
          <Input autoFocus />
        </Form.Item>
        <Form.Item
          name="criteria"
          label={t("octopBot.criteria")}
          rules={[{ required: true, whitespace: true }]}
        >
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} />
        </Form.Item>
        <Form.Item name="status" label={t("octopBot.status")}>
          <Select options={statusOptions(["draft", "active", "done"])} />
        </Form.Item>
        <Form.List name="stages">
          {(fields, { add, remove }) => (
            <>
              {fields.map(({ key, name }) => (
                <div className={styles.stage} key={key}>
                  <Form.Item
                    name={[name, "title"]}
                    label={t("octopBot.stage", { number: name + 1 })}
                    rules={[{ required: true, whitespace: true }]}
                  >
                    <Input />
                  </Form.Item>
                  <Space wrap>
                    <Form.Item
                      name={[name, "assignee_id"]}
                      label={t("octopBot.assignee")}
                    >
                      <Select
                        allowClear
                        options={options}
                        style={{ minWidth: 140 }}
                      />
                    </Form.Item>
                    <Form.Item
                      name={[name, "status"]}
                      label={t("octopBot.status")}
                    >
                      <Select
                        options={statusOptions(["pending", "active", "done"])}
                        style={{ minWidth: 115 }}
                      />
                    </Form.Item>
                    <Button
                      type="text"
                      icon={<Trash2 size={16} />}
                      aria-label={t("octopBot.deleteStage")}
                      onClick={() => remove(name)}
                    />
                  </Space>
                  <Form.Item
                    name={[name, "evidence"]}
                    label={t("octopBot.evidence")}
                  >
                    <Input.TextArea autoSize />
                  </Form.Item>
                </div>
              ))}
              <Button
                icon={<Plus size={15} />}
                onClick={() =>
                  add({
                    title: "",
                    status: "pending",
                    assignee_id: null,
                    evidence: "",
                  })
                }
              >
                {t("octopBot.addStage")}
              </Button>
            </>
          )}
        </Form.List>
        {error && <Alert type="error" showIcon message={error} />}
      </Form>
    </Modal>
  );
}
