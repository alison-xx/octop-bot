import { lazy, Suspense, useEffect } from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import BrandLoading from "../../components/BrandLoading";
import {
  BOT_HOME,
  BOT_CLOUD,
  BOT_GUIDE,
  BOT_SETTINGS,
  botClientDestination,
} from "../../utils/botClientRoute";
import { getDesktopBridge, isBotWebClient } from "../../utils/desktopBridge";
import styles from "./index.module.less";

const Workspace = lazy(() => import("./index"));
const CloudWorkspace = lazy(() => import("./CloudWorkspace"));
const Settings = lazy(() => import("./BotClientSettings"));
const Setup = lazy(() => import("./BotClientSetup"));
const Guide = lazy(() => import("./BotGettingStarted"));

export function BotClientSetupRoute() {
  return (
    <Suspense fallback={<BrandLoading viewport />}>
      <Setup />
    </Suspense>
  );
}

function LegacyChat() {
  const location = useLocation();
  return (
    <Navigate
      replace
      to={botClientDestination(location.pathname)}
      state={location.state}
    />
  );
}

export default function BotClientRoutes() {
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(
    () =>
      getDesktopBridge()?.onBotShortcut?.((action) => {
        if (action === "cloud") {
          if (location.pathname !== BOT_CLOUD)
            navigate(BOT_CLOUD, { state: { from: location.pathname } });
          return;
        }
        const inDirectory = /^\/octop-bot\/(bots|groups)\//.test(
          location.pathname,
        );
        navigate(inDirectory ? location.pathname : BOT_HOME, {
          state: { botShortcut: action },
          replace: inDirectory,
        });
      }),
    [location.pathname, navigate],
  );
  useEffect(
    () =>
      getDesktopBridge()?.onOpenBotSettings?.(() => {
        if (location.pathname !== BOT_SETTINGS)
          navigate(BOT_SETTINGS, { state: { from: location.pathname } });
      }),
    [location.pathname, navigate],
  );
  return (
    <div className={styles.client} data-bot-client>
      <Suspense fallback={<BrandLoading viewport />}>
        <Routes>
          <Route path={BOT_HOME} element={<Workspace />} />
          {!isBotWebClient() && (
            <>
              <Route path={BOT_CLOUD} element={<CloudWorkspace />} />
              <Route path={BOT_GUIDE} element={<Guide />} />
            </>
          )}
          <Route
            path="/octop-bot/bots/:agentId/:threadId?"
            element={<Workspace />}
          />
          <Route path="/octop-bot/groups/:groupId" element={<Workspace />} />
          <Route path={BOT_SETTINGS} element={<Settings />} />
          <Route
            path="/admin/models"
            element={<Navigate replace to={BOT_SETTINGS} />}
          />
          <Route path="/chat/:agentId?/:threadId?" element={<LegacyChat />} />
          <Route path="*" element={<Navigate replace to={BOT_HOME} />} />
        </Routes>
      </Suspense>
    </div>
  );
}
