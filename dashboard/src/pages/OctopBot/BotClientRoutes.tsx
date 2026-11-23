import {
  lazy,
  Suspense,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { ConfigProvider, type ThemeConfig } from "antd";
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

// Neutral black-and-white accents for the Bot client, also inside portals.
// antd derives selection fills, focus borders and outlines from colorPrimary;
// from near-black or near-white that gives heavy dark blocks, so the soft
// grey derivatives are set explicitly.
function neutralTheme(isDark: boolean): ThemeConfig {
  const c = isDark
    ? {
        primary: "#ededed",
        selected: "rgba(255,255,255,0.10)",
        selectedHover: "rgba(255,255,255,0.14)",
        hover: "rgba(255,255,255,0.06)",
        border: "rgba(255,255,255,0.32)",
        outline: "rgba(255,255,255,0.08)",
      }
    : {
        primary: "#191919",
        selected: "#f0f0f0",
        selectedHover: "#ebebeb",
        hover: "#f5f5f5",
        border: "#bfbfbf",
        outline: "rgba(0,0,0,0.06)",
      };
  return {
    token: {
      colorPrimary: c.primary,
      colorLink: c.primary,
      ...(isDark ? { colorTextLightSolid: "#161616" } : {}),
      controlItemBgActive: c.selected,
      controlItemBgActiveHover: c.selectedHover,
      controlItemBgHover: c.hover,
      colorPrimaryBg: c.selected,
      colorPrimaryBgHover: c.selectedHover,
      colorPrimaryBorder: c.border,
      colorPrimaryBorderHover: c.border,
      controlOutline: c.outline,
    },
    components: {
      Select: {
        optionSelectedBg: c.selected,
        optionSelectedFontWeight: 500,
        optionActiveBg: c.hover,
        activeBorderColor: c.border,
        hoverBorderColor: c.border,
        activeOutlineColor: c.outline,
      },
      Input: {
        activeBorderColor: c.border,
        hoverBorderColor: c.border,
        activeShadow: `0 0 0 3px ${c.outline}`,
      },
      InputNumber: {
        activeBorderColor: c.border,
        hoverBorderColor: c.border,
        activeShadow: `0 0 0 3px ${c.outline}`,
      },
      DatePicker: {
        activeBorderColor: c.border,
        hoverBorderColor: c.border,
        activeShadow: `0 0 0 3px ${c.outline}`,
      },
      Menu: {
        itemSelectedBg: c.selected,
        itemSelectedColor: isDark ? "#ededed" : "#191919",
        itemActiveBg: c.selectedHover,
        itemHoverBg: c.hover,
      },
    },
  };
}
/** Neutral accents and the html marker the Bot client styles key off. */
function BotClientTheme({ children }: { children: ReactNode }) {
  const { isDark } = useTheme();
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-bot-client", "");
    return () => root.removeAttribute("data-bot-client");
  }, []);
  const theme = useMemo(() => neutralTheme(isDark), [isDark]);
  // Dropdowns grow to fit their options instead of clipping to the field width.
  return (
    <ConfigProvider theme={theme} popupMatchSelectWidth={false}>
      {children}
    </ConfigProvider>
  );
}

export function BotClientSetupRoute() {
  return (
    <BotClientTheme>
      <Suspense fallback={<BrandLoading viewport />}>
        <Setup />
      </Suspense>
    </BotClientTheme>
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

export default function BotClientRoutes() {
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
    <BotClientTheme>
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
    </BotClientTheme>
  );
}
