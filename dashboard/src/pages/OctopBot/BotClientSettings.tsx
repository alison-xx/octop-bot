import { useEffect, useState } from "react";
import { Alert, Button, Radio, Select, Spin } from "antd";
import {
  ArrowLeft,
  ArrowRight,
  Blocks,
  BookOpen,
  Cloud,
  Cpu,
  Link2,
  LogOut,
  Plus,
  UserRound,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { lynxceBotApi } from "../../api/modules/lynxceBot";
import { refreshBotModels, useLynxceStatus } from "../../hooks/useLynxceStatus";
import LynxceAccount from "./LynxceAccount";
import RetainedFolders from "./RetainedFolders";
import { authApi } from "../../api/modules/auth";
import { providerApi } from "../../api/modules/provider";
import type { ResolvedModel } from "../../api/types";
import { clearAuthToken } from "../../api/request";
import { holdDesktopLocalAutoLogin } from "../../api/desktopSession";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import ThemeSwitcher from "../../components/ThemeSwitcher";
import { applyGuestLocale } from "../../utils/locale";
import { getDesktopBridge, isBotWebClient } from "../../utils/desktopBridge";
import { userCan } from "../../utils/permissions";
import {
  BOT_HOME,
  BOT_CAPABILITIES,
  BOT_GUIDE,
  BOT_SETTINGS,
  botClientDestination,
} from "../../utils/botClientRoute";
import { apiErrorMessage } from "../../utils/apiError";
import ModelsPage from "../Settings/Models";
import {
  isEmbeddingProvider,
  useProviders,
} from "../Settings/Models/useProviders";
import {
  CustomProviderModal,
  LocalServiceCard,
  PresetProviderModal,
  ProviderConfigModal,
} from "../Settings/Models/components";
import {
  findConfiguredProvider,
  isLocalPreset,
} from "../Settings/Models/presetUtils";
import { BotCharacter, octopCharacter } from "./BotCharacter";
import styles from "./index.module.less";
import settings from "./BotClientSettings.module.less";

type ModelSource = "lynxce" | "cloud" | "custom" | "local";

function ConnectionForm({
  mode,
  noModels,
  onSaved,
}: {
  mode: Exclude<ModelSource, "lynxce">;
  noModels: boolean;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const { presets, providers, fetchAll, error, loading } = useProviders();
  const [choice, setChoice] = useState("");
  const [edit, setEdit] = useState(false);
  const refresh = async () => {
    await fetchAll();
    onSaved();
  };
  const options = presets.filter(
    (p) =>
      p.purpose !== "embedding" &&
      p.provider_variant !== "embedding" &&
      !isLocalPreset(p),
  );
  const selected =
    options.find((p) => p.id === choice) ??
    options.find((p) => findConfiguredProvider(p, providers));
  const existing = selected
    ? findConfiguredProvider(selected, providers)
    : null;
  const ollama = presets.find((p) => p.id === "ollama");
  return (
    <div className={settings.form}>
      {noModels && providers.some((p) => !isEmbeddingProvider(p)) && !error && (
        <Alert type="info" showIcon message={t("botClient.noEnabledModels")} />
      )}
      {error && (
        <Alert
          type="error"
          message={error}
          action={
            <Button onClick={() => void fetchAll()}>
              {t("octopBot.retry")}
            </Button>
          }
        />
      )}
      {loading ? (
        <Spin />
      ) : (
        !error && (
          <>
            {mode === "cloud" && options.length === 0 && (
              <Alert
                type="info"
                message={t("botClient.presetsUnavailable")}
                action={
                  <Button onClick={() => void fetchAll()}>
                    {t("octopBot.retry")}
                  </Button>
                }
              />
            )}
            {mode === "cloud" && options.length > 0 && (
              <>
                <label htmlFor="bot-provider">{t("botClient.provider")}</label>
                <Select
                  id="bot-provider"
                  showSearch
                  optionFilterProp="label"
                  placeholder={t("botClient.chooseProvider")}
                  value={selected?.id}
                  onChange={setChoice}
                  options={options.map((p) => ({ label: p.name, value: p.id }))}
                />
                <Button
                  block
                  type="primary"
                  disabled={!selected}
                  onClick={() => setEdit(true)}
                >
                  {t("botClient.credentials")}
                  <ArrowRight size={15} />
                </Button>
              </>
            )}
            {mode === "custom" && (
              <>
                <p>{t("botClient.customHint")}</p>
                <Button block type="primary" onClick={() => setEdit(true)}>
                  {t("botClient.customAction")}
                  <ArrowRight size={15} />
                </Button>
              </>
            )}
            {mode === "local" &&
              (ollama ? (
                <LocalServiceCard
                  preset={ollama}
                  provider={findConfiguredProvider(ollama, providers) ?? null}
                  onSaved={refresh}
                  isHover={false}
                  onMouseEnter={() => {}}
                  onMouseLeave={() => {}}
                />
              ) : (
                <p>{t("botClient.localUnavailable")}</p>
              ))}
          </>
        )
      )}
      {edit &&
        mode === "cloud" &&
        selected &&
        (existing ? (
          <ProviderConfigModal
            open
            provider={existing}
            apiPrefix="/admin/providers"
            onClose={() => setEdit(false)}
            onSaved={refresh}
          />
        ) : (
          <PresetProviderModal
            open
            preset={selected}
            onClose={() => setEdit(false)}
            onSaved={refresh}
          />
        ))}
      {edit && mode === "custom" && (
        <CustomProviderModal
          open
          apiPrefix="/admin/providers"
          onClose={() => setEdit(false)}
          onSaved={refresh}
        />
      )}
    </div>
  );
}

export default function BotClientSettings() {
  const { t } = useTranslation();
  const user = useCurrentUser();
  const navigate = useNavigate();
  const location = useLocation();
  const from = botClientDestination(location.state?.from ?? BOT_HOME);
  const back = from.replace(/\/$/, "") === BOT_SETTINGS ? BOT_HOME : from;
  const prefillInput = location.state?.prefillInput;
  const cloud = userCan(user, "providers");
  const local = userCan(user, "ollama_models");
  const [models, setModels] = useState<ResolvedModel[] | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [foldersOpen, setFoldersOpen] = useState(false);
  const web = isBotWebClient();
  const account = useLynxceStatus(!web);
  const [source, setSource] = useState<ModelSource>(
    location.state?.source === "other"
      ? cloud
        ? "cloud"
        : local
        ? "local"
        : "lynxce"
      : "lynxce",
  );
  const [adding, setAdding] = useState(Boolean(location.state?.source));
  const [switchError, setSwitchError] = useState("");
  const [switching, setSwitching] = useState(false);
  const refreshSource = () => {
    refreshBotModels();
    refresh();
  };
  const activateOtherSource = async () => {
    if (switching) return;
    setSwitching(true);
    try {
      if ((await providerApi.listResolvedModels()).length > 0)
        await lynxceBotApi.clearModel();
      setSwitchError("");
      refreshSource();
    } catch (e) {
      setSwitchError(apiErrorMessage(e, t("octopBot.failed"), t));
    } finally {
      setSwitching(false);
    }
  };
  const [full, setFull] = useState(false);
  const refresh = () => setRevision((value) => value + 1);
  useEffect(() => {
    let active = true;
    setError("");
    providerApi.listResolvedModels().then(
      (items) => {
        if (active) setModels(items);
      },
      (err) => {
        if (active)
          setError(apiErrorMessage(err, t("models.loadProvidersFailed"), t));
      },
    );
    return () => {
      active = false;
    };
  }, [revision, t]);
  const personalModel =
    account.status?.connected && account.status.selected_model;
  const ready = Boolean(personalModel || models?.length);
  const showConnections = adding || !ready;
  const sources = [
    ["lynxce", "botClient.lynxce.source", UserRound],
    ...(cloud
      ? ([
          ["cloud", "botClient.cloud", Cloud],
          ["custom", "botClient.custom", Link2],
        ] as const)
      : []),
    ...(local ? ([["local", "botClient.local", Cpu]] as const) : []),
  ] as const;
  const returnToChat = () =>
    navigate(back, {
      replace: true,
      state:
        back === BOT_GUIDE
          ? { step: "team", returnTo: location.state?.guideReturnTo }
          : prefillInput
          ? { prefillInput }
          : null,
    });
  return (
    <section className={styles.clientSettings}>
      <header
        className={`${styles.header} ${settings.header} octop-desktop-drag`}
        data-octop-chrome-end-pad
      >
        <Button
          type="text"
          icon={<ArrowLeft size={17} />}
          onClick={returnToChat}
        >
          {t(back === BOT_GUIDE ? "botGuide.resume" : "common.backToChat")}
        </Button>
        <div className={styles.account}>
          {back !== BOT_GUIDE && !prefillInput && (
            <Button
              type="text"
              icon={<Blocks size={16} />}
              onClick={() =>
                navigate(BOT_CAPABILITIES, { state: { from: back } })
              }
            >
              {t("botCapabilities.title")}
            </Button>
          )}
          {!web && back !== BOT_GUIDE && !prefillInput && (
            <Button
              type="text"
              icon={<BookOpen size={16} />}
              onClick={() => navigate(BOT_GUIDE, { state: { returnTo: back } })}
            >
              {t("botGuide.title")}
            </Button>
          )}
          {getDesktopBridge()?.showBotOrb && (
            <Button
              type="text"
              size="small"
              onClick={() => getDesktopBridge()?.showBotOrb?.()}
            >
              {t("botClient.showOrb")}
            </Button>
          )}
          <Button type="text" size="small" onClick={() => setFoldersOpen(true)}>
            {t("octopBot.retainedFolders")}
          </Button>
          <ThemeSwitcher compact />
          <span>{user?.display_name || user?.username}</span>
          <Button
            type="text"
            title={t("auth.logout")}
            aria-label={t("auth.logout")}
            icon={<LogOut size={16} />}
            onClick={async () => {
              if (user?.username === "local") holdDesktopLocalAutoLogin();
              await authApi.logout();
              clearAuthToken();
              await applyGuestLocale();
              navigate("/login", { replace: true });
            }}
          />
        </div>
      </header>
      {web && (cloud || local) ? (
        <ModelsPage chatOnly onConnectionSaved={refreshBotModels} />
      ) : full ? (
        <>
          <div className={styles.catalogBack}>
            <Button
              type="text"
              icon={<ArrowLeft size={15} />}
              onClick={() => {
                setFull(false);
                refresh();
              }}
            >
              {t("botClient.settings")}
            </Button>
          </div>
          {switchError && (
            <Alert
              type="error"
              message={switchError}
              action={
                <Button onClick={() => void activateOtherSource()}>
                  {t("octopBot.retry")}
                </Button>
              }
            />
          )}
          <ModelsPage chatOnly onConnectionSaved={activateOtherSource} />
        </>
      ) : (
        <div className={styles.connectScroll}>
          <section className={styles.connectPanel} data-bot-connect>
            <BotCharacter
              look={{ ...octopCharacter, source: "character" }}
              badges={false}
              size={48}
            />
            <h1>
              {t(
                models === null && !personalModel
                  ? "botClient.settings"
                  : ready
                  ? "botClient.availableModels"
                  : "botClient.connectModel",
              )}
            </h1>
            {error && (
              <Alert
                type="error"
                showIcon
                message={error}
                action={
                  <Button onClick={refresh}>{t("octopBot.retry")}</Button>
                }
              />
            )}
            {models === null && !error && !personalModel && <Spin />}
            {ready && (
              <>
                <ul
                  className={settings.models}
                  tabIndex={
                    !personalModel && (models?.length ?? 0) > 3 ? 0 : undefined
                  }
                  aria-label={t("botClient.availableModels")}
                >
                  {personalModel ? (
                    <li>
                      <span>{personalModel}</span>
                      <small>{t("botClient.lynxce.source")}</small>
                    </li>
                  ) : (
                    models?.map((m) => (
                      <li key={JSON.stringify([m.provider_id, m.model])}>
                        <span>{m.name || m.model}</span>
                        <small>{m.provider_name}</small>
                      </li>
                    ))
                  )}
                </ul>
                {prefillInput && <p>{t("botClient.draftKept")}</p>}
                <Button type="primary" block onClick={returnToChat}>
                  {t(
                    back === BOT_GUIDE
                      ? "botGuide.resume"
                      : location.state?.from
                      ? "common.backToChat"
                      : "botClient.startChat",
                  )}
                </Button>
                {!web && (
                  <Button
                    block
                    icon={<Plus size={15} />}
                    aria-expanded={adding}
                    aria-controls="bot-connection-form"
                    onClick={() => setAdding(!adding)}
                  >
                    {t(
                      adding
                        ? "common.cancel"
                        : account.status?.connected
                        ? "botClient.lynxce.manage"
                        : "botClient.addConnection",
                    )}
                  </Button>
                )}
              </>
            )}
            {models && !ready && !error && (
              <p>
                {t(
                  web
                    ? "modelConfig.promptMessageNoPermission"
                    : "botClient.connectHint",
                )}
              </p>
            )}
            {!web && showConnections && (
              <div className={settings.form} id="bot-connection-form">
                {sources.length > 1 && (
                  <Radio.Group
                    aria-label={t("botClient.connectModel")}
                    className={settings.sources}
                    value={source}
                    onChange={(e) => setSource(e.target.value)}
                  >
                    {sources.map(([value, label, Icon]) => (
                      <Radio.Button key={value} value={value}>
                        <Icon size={15} />
                        {t(label)}
                      </Radio.Button>
                    ))}
                  </Radio.Group>
                )}
                {switchError && (
                  <Alert
                    type="error"
                    message={switchError}
                    action={
                      <Button onClick={() => void activateOtherSource()}>
                        {t("octopBot.retry")}
                      </Button>
                    }
                  />
                )}
                {source !== "lynxce" && (
                  <>
                    {Boolean(models?.length) && (
                      <Button
                        loading={switching}
                        onClick={() => void activateOtherSource()}
                      >
                        {t("botClient.lynxce.useOther")}
                      </Button>
                    )}
                    <ConnectionForm
                      key={source}
                      mode={source}
                      noModels={!ready}
                      onSaved={() => void activateOtherSource()}
                    />
                  </>
                )}
              </div>
            )}
            {!web &&
              (showConnections
                ? source === "lynxce"
                : account.status?.connected) && (
                <LynxceAccount
                  key={user?.username}
                  owner={user?.username ?? ""}
                  compact={!showConnections}
                  status={account.status}
                  statusError={account.error}
                  onReload={account.reload}
                  onSaved={refreshSource}
                  onSwitch={models?.length ? activateOtherSource : undefined}
                />
              )}
            {(cloud || local) && (
              <Button type="link" size="small" onClick={() => setFull(true)}>
                {t("botClient.manage")}
              </Button>
            )}
          </section>
        </div>
      )}
      {foldersOpen && <RetainedFolders onClose={() => setFoldersOpen(false)} />}
    </section>
  );
}
