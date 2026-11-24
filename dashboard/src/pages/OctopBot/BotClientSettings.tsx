import { useEffect, useState } from "react";
import { Alert, Button, Select, Spin } from "antd";
import {
  ArrowLeft,
  Blocks,
  Check,
  Cpu,
  FolderLock,
  Info,
  LogOut,
  SlidersHorizontal,
  UserRound,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { lynxceBotApi } from "../../api/modules/lynxceBot";
import { refreshBotModels, useLynxceStatus } from "../../hooks/useLynxceStatus";
import LynxceAccount from "./LynxceAccount";
import BotNotifySettings from "./BotNotifySettings";
import RetainedFolders from "./RetainedFolders";
import { providerApi } from "../../api/modules/provider";
import type { ResolvedModel } from "../../api/types";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import ThemeSwitcher from "../../components/ThemeSwitcher";
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
import { useProviders } from "../Settings/Models/useProviders";
import { LocalServiceCard } from "../Settings/Models/components";
import { findConfiguredProvider } from "../Settings/Models/presetUtils";
import {
  botAccountName,
  LANGUAGES,
  signOutBotClient,
  useLanguage,
} from "./AccountMenu";
import { CreditsPanel, LYNXCE_ACCOUNT_SITE } from "./CreditsWidgets";
import BotAboutPanel from "./BotAboutPanel";
import { useLynxceCredits } from "./useLynxceCredits";
import { useBotServerInfo } from "./useBotServerInfo";
import { accountInitials } from "../Chat/utils/accountDisplayName";
import styles from "./index.module.less";
import settings from "./BotClientSettings.module.less";
import ModelName from "./ModelName";
import OwnKeysSection from "./OwnKeysSection";
import type { OwnKeyList } from "../../api/modules/ownModelKeys";
import sourcesUi from "./modelSources.module.less";

type SettingsTab = "account" | "models" | "general" | "about";

/** This computer's Ollama, through the existing service card (install, start, models). */
function LocalModels({ onSaved }: { onSaved: () => void }) {
  const { t } = useTranslation();
  const { presets, providers, fetchAll, error, loading } = useProviders();
  const refresh = async () => {
    await fetchAll();
    onSaved();
  };
  const ollama = presets.find((p) => p.id === "ollama");
  if (loading) return <Spin />;
  if (error)
    return (
      <Alert
        type="error"
        message={error}
        action={
          <Button onClick={() => void fetchAll()}>{t("octopBot.retry")}</Button>
        }
      />
    );
  return ollama ? (
    <LocalServiceCard
      preset={ollama}
      provider={findConfiguredProvider(ollama, providers) ?? null}
      onSaved={refresh}
      isHover={false}
      onMouseEnter={() => {}}
      onMouseLeave={() => {}}
    />
  ) : (
    <p className={sourcesUi.note}>{t("botClient.localUnavailable")}</p>
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
  const credits = useLynxceCredits();
  const cloudEdition = useBotServerInfo()?.edition === "cloud";
  const displayName = botAccountName(user, t("botClient.account.lynxceUser"));
  const lynxceSignedIn = credits.status !== "none" && credits.status !== "idle";
  const [ownKeys, setOwnKeys] = useState<OwnKeyList | null>(null);
  const [localOpen, setLocalOpen] = useState(false);
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
  const [language, setLanguage] = useLanguage();
  const [tab, setTab] = useState<SettingsTab>(
    location.state?.tab === "general" ||
      location.state?.tab === "account" ||
      location.state?.tab === "about"
      ? location.state.tab
      : "models",
  );
  // Capabilities is its own page; it sits between Models and General in the list.
  const showCapabilities = back !== BOT_GUIDE && !prefillInput;
  const navItem = (value: SettingsTab, label: string, Icon: typeof Cpu) => (
    <button
      key={value}
      type="button"
      aria-current={tab === value ? "page" : undefined}
      onClick={() => setTab(value)}
    >
      <Icon size={16} />
      {t(label)}
    </button>
  );
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
  const ownModel = ownKeys?.in_use ? ownKeys.selected_model : null;
  // A model chosen on the account (Lynxce or one of my keys) wins over this
  // computer's configured services until "use local models" clears it.
  const accountModel = ownModel || personalModel || null;
  const currentModel =
    accountModel || (cloudEdition ? null : models?.[0]?.model ?? null);
  const ready = cloudEdition || Boolean(accountModel || models?.length);
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
      </header>
      <div className={settings.layout}>
        <nav className={settings.nav} aria-label={t("botClient.menu.settings")}>
          <h1>{t("botClient.menu.settings")}</h1>
          {navItem("account", "botClient.nav.account", UserRound)}
          {navItem("models", "botClient.nav.models", Cpu)}
          {showCapabilities && (
            <button
              type="button"
              onClick={() =>
                navigate(BOT_CAPABILITIES, { state: { from: back } })
              }
            >
              <Blocks size={16} />
              {t("botCapabilities.title")}
            </button>
          )}
          {navItem("general", "botClient.nav.general", SlidersHorizontal)}
          {navItem("about", "botAbout.title", Info)}
        </nav>
        <div className={settings.content}>
          {tab === "general" ? (
            <div className={settings.page}>
              <h2>{t("botClient.nav.general")}</h2>
              <h3>{t("botClient.nav.lookAndLanguage")}</h3>
              <div className={settings.group}>
                <div className={settings.row}>
                  <span>{t("botClient.nav.appearance")}</span>
                  <ThemeSwitcher compact />
                </div>
                <div className={settings.row}>
                  <span>{t("botClient.nav.language")}</span>
                  <Select
                    className={settings.select}
                    value={language}
                    onChange={(lang) => void setLanguage(lang)}
                    options={LANGUAGES.map(([value, label]) => ({
                      value,
                      label,
                    }))}
                  />
                </div>
              </div>
              <BotNotifySettings />
              <h3>{t("botClient.nav.desktopAndPrivacy")}</h3>
              <div className={settings.group}>
                {getDesktopBridge()?.showBotOrb && (
                  <div className={settings.row}>
                    <span>
                      {t("botClient.nav.floatingButton")}
                      <small>{t("botClient.nav.floatingButtonHint")}</small>
                    </span>
                    <Button onClick={() => getDesktopBridge()?.showBotOrb?.()}>
                      {t("botClient.showOrb")}
                    </Button>
                  </div>
                )}
                <div className={settings.row}>
                  <span>
                    {t("octopBot.retainedFolders")}
                    <small>{t("botClient.nav.retainedFoldersHint")}</small>
                  </span>
                  <Button
                    icon={<FolderLock size={15} />}
                    onClick={() => setFoldersOpen(true)}
                  >
                    {t("botClient.nav.manage")}
                  </Button>
                </div>
              </div>
            </div>
          ) : tab === "about" ? (
            <BotAboutPanel />
          ) : tab === "account" ? (
            <div className={`${settings.page} ${settings.wide}`}>
              <h2>{t("botClient.nav.account")}</h2>
              <div className={settings.group}>
                <div className={settings.row}>
                  <span className={settings.who}>
                    <span className={settings.initials}>
                      {accountInitials(displayName)}
                    </span>
                    <span>
                      {displayName}
                      <small>
                        {lynxceSignedIn || cloudEdition
                          ? t("botClient.account.lynxce")
                          : t("botClient.account.localHint")}
                      </small>
                    </span>
                  </span>
                  <span className={settings.rowActions}>
                    {(lynxceSignedIn || cloudEdition) && (
                      <a
                        href={LYNXCE_ACCOUNT_SITE}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {t("botClient.account.centre")}
                      </a>
                    )}
                    <Button
                      icon={<LogOut size={15} />}
                      onClick={() =>
                        void signOutBotClient(user?.username, navigate)
                      }
                    >
                      {t("auth.logout")}
                    </Button>
                  </span>
                </div>
              </div>
              <CreditsPanel />
              {!web && credits.status === "none" && (
                <section
                  className={settings.promo}
                  aria-labelledby="bot-lynxce-promo"
                >
                  <div>
                    <h3 id="bot-lynxce-promo">
                      {t("botClient.account.promoTitle")}
                    </h3>
                    <ul>
                      {(
                        [
                          "promoComputer",
                          "promoModels",
                          "promoDevices",
                        ] as const
                      ).map((key) => (
                        <li key={key}>
                          <Check size={16} aria-hidden="true" />
                          {t(`botClient.account.${key}`)}
                        </li>
                      ))}
                    </ul>
                    <small>{t("botClient.account.promoMove")}</small>
                  </div>
                  <div>
                    <Button
                      type="primary"
                      size="large"
                      block
                      onClick={() =>
                        void signOutBotClient(user?.username, navigate)
                      }
                    >
                      {t("botClient.account.signIn")}
                    </Button>
                    <small>{t("botClient.account.promoRegister")}</small>
                  </div>
                </section>
              )}
            </div>
          ) : web && !cloudEdition && (cloud || local) ? (
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
              <div className={sourcesUi.page} data-bot-connect>
                <header className={sourcesUi.head}>
                  <div>
                    <h1>
                      {t(ready ? "botModels.title" : "botModels.setupTitle")}
                    </h1>
                    <p>{t(ready ? "botModels.body" : "botModels.setupBody")}</p>
                  </div>
                  {currentModel && (
                    <p className={sourcesUi.current} aria-live="polite">
                      <span>{t("botModels.current")}</span>
                      <ModelName id={currentModel} />
                    </p>
                  )}
                </header>
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
                {models && !ready && !error && !cloudEdition && (
                  <p className={sourcesUi.note}>
                    {t(
                      web
                        ? "modelConfig.promptMessageNoPermission"
                        : "botClient.connectHint",
                    )}
                  </p>
                )}
                {(cloudEdition || !web) && (
                  <section
                    className={sourcesUi.section}
                    aria-labelledby="lynxce-models-title"
                  >
                    <div className={sourcesUi.sectionHead}>
                      <h2 id="lynxce-models-title">
                        {t("botModels.lynxce.title")}
                        <span className={sourcesUi.tag}>
                          {t("botModels.lynxce.billing")}
                        </span>
                      </h2>
                    </div>
                    <div className={sourcesUi.card}>
                      {cloudEdition ? (
                        <p className={sourcesUi.note}>
                          {t("botClient.account.cloudModels")}
                        </p>
                      ) : (
                        <LynxceAccount
                          key={user?.username}
                          owner={user?.username ?? ""}
                          status={account.status}
                          statusError={account.error}
                          onReload={account.reload}
                          onSaved={refreshSource}
                        />
                      )}
                    </div>
                  </section>
                )}
                <OwnKeysSection
                  cloud={cloudEdition}
                  revision={revision}
                  onState={setOwnKeys}
                  onChanged={refreshSource}
                />
                {!web && (local || cloud || Boolean(models?.length)) && (
                  <section
                    className={sourcesUi.section}
                    aria-labelledby="local-models-title"
                  >
                    <div className={sourcesUi.sectionHead}>
                      <h2 id="local-models-title">
                        {t("botModels.local.title")}
                        <span className={sourcesUi.tag}>
                          {t("botModels.local.billing")}
                        </span>
                      </h2>
                      {cloud && (
                        <Button type="link" onClick={() => setFull(true)}>
                          {t("botClient.manage")}
                        </Button>
                      )}
                    </div>
                    {local &&
                      (localOpen ? (
                        <LocalModels
                          onSaved={() => void activateOtherSource()}
                        />
                      ) : (
                        <button
                          type="button"
                          className={sourcesUi.emptyRow}
                          onClick={() => setLocalOpen(true)}
                        >
                          <strong>{t("botModels.local.ollama")}</strong>
                          <span>{t("botModels.local.ollamaHint")}</span>
                        </button>
                      ))}
                    {Boolean(models?.length) && (
                      <div className={sourcesUi.card}>
                        <ul
                          className={settings.models}
                          tabIndex={(models?.length ?? 0) > 3 ? 0 : undefined}
                          aria-label={t("botClient.availableModels")}
                        >
                          {models?.map((m) => (
                            <li key={JSON.stringify([m.provider_id, m.model])}>
                              <ModelName id={m.model} name={m.name} />
                            </li>
                          ))}
                        </ul>
                        {accountModel ? (
                          <Button
                            loading={switching}
                            onClick={() => void activateOtherSource()}
                          >
                            {t("botModels.local.use")}
                          </Button>
                        ) : (
                          <span className={sourcesUi.inUse}>
                            <span
                              aria-hidden="true"
                              className={sourcesUi.dot}
                            />
                            {t("botModels.local.inUse")}
                          </span>
                        )}
                      </div>
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
                  </section>
                )}
                <footer className={sourcesUi.footer}>
                  {prefillInput && (
                    <p className={sourcesUi.note}>{t("botClient.draftKept")}</p>
                  )}
                  <Button
                    type="primary"
                    size="large"
                    disabled={!ready}
                    onClick={returnToChat}
                  >
                    {t(
                      back === BOT_GUIDE
                        ? "botGuide.resume"
                        : location.state?.from
                        ? "common.backToChat"
                        : "botClient.startChat",
                    )}
                  </Button>
                </footer>
              </div>
            </div>
          )}
        </div>
      </div>
      {foldersOpen && <RetainedFolders onClose={() => setFoldersOpen(false)} />}
    </section>
  );
}
