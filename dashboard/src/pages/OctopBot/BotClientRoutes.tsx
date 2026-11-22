import { lazy, Suspense, useEffect, useRef } from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { ConfigProvider } from "antd";
import BrandLoading from "../../components/BrandLoading";
import { useTheme } from "../../context/ThemeContext";
import {
  BOT_HOME,
  BOT_CAPABILITIES,
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
const Capabilities = lazy(() => import("./BotCapabilities"));

export function BotClientSetupRoute() {
  return (
    <Suspense fallback={<BrandLoading viewport />}>
      <Setup />
    </Suspense>
  );
}

/** Legacy chat links and upstream dashboard paths land on their Bot page. */
function BotRedirect() {
  const location = useLocation();
  const mapped = botClientDestination(location.pathname);
  // A Bot path without a route here (e.g. cloud on the web build) goes home.
  const to = mapped === location.pathname ? BOT_HOME : mapped;
  return (
    <Navigate
      replace
      to={to.startsWith(BOT_CAPABILITIES) ? to + location.search : to}
      state={location.state}
    />
  );
}

// Neutral black-and-white accents for the Bot client, also inside portals.
const lightAccent = { colorPrimary: "#191919", colorLink: "#191919" };
const darkAccent = {
  colorPrimary: "#ededed",
  colorLink: "#ededed",
  colorTextLightSolid: "#161616",
};

export default function BotClientRoutes() {
  const { isDark } = useTheme();
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-bot-client", "");
    return () => root.removeAttribute("data-bot-client");
  }, []);
  const navigate = useNavigate();
  const location = useLocation();
  // IPC callbacks subscribe once and read the route through this ref.
  const current = useRef({ navigate, path: location.pathname });
  useEffect(() => {
    current.current = { navigate, path: location.pathname };
  }, [navigate, location.pathname]);
  useEffect(
    () =>
      getDesktopBridge()?.onBotShortcut?.((action) => {
        const { navigate, path } = current.current;
        if (action === "cloud") {
          if (path !== BOT_CLOUD)
            navigate(BOT_CLOUD, { state: { from: path } });
          return;
        }
        const inDirectory = /^\/octop-bot\/(bots|groups)\//.test(path);
        navigate(inDirectory ? path : BOT_HOME, {
          state: { botShortcut: action },
          replace: inDirectory,
        });
      }),
    [],
  );
  useEffect(
    () =>
      getDesktopBridge()?.onOpenBotSettings?.(() => {
        const { navigate, path } = current.current;
        if (path !== BOT_SETTINGS)
          navigate(BOT_SETTINGS, { state: { from: path } });
      }),
    [],
  );
  return (
    <ConfigProvider theme={{ token: isDark ? darkAccent : lightAccent }}>
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
              path={BOT_CAPABILITIES + "/:section?"}
              element={<Capabilities />}
            />
            <Route
              path="/admin/models"
              element={<Navigate replace to={BOT_SETTINGS} />}
            />
            <Route
              path="/chat/:agentId?/:threadId?"
              element={<BotRedirect />}
            />
            <Route path="*" element={<BotRedirect />} />
          </Routes>
        </Suspense>
      </div>
    </ConfigProvider>
  );
}
