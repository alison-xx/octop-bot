import {
  lazy,
  Suspense,
  useContext,
  useEffect,
  useMemo,
  type ReactNode,
} from "react";
import { Button, Empty, Spin } from "antd";
import {
  ArrowLeft,
  Bot,
  CalendarClock,
  Library,
  Notebook,
  Package,
  Plug,
  Puzzle,
  Sparkles,
  Waypoints,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  Navigate,
  parsePath,
  UNSAFE_NavigationContext,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
  type Navigator,
} from "react-router-dom";
import { octopBotApi } from "../../api/modules/octopBot";
import { useAgent } from "../../context/AgentContext";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { canAccessPath } from "../../utils/permissions";
import {
  BOT_CAPABILITIES,
  BOT_CAPABILITY_SECTIONS,
  BOT_CAPABILITY_UPSTREAM,
  BOT_HOME,
  BOT_SETTINGS,
  botCapabilityLink,
  botCapabilityPath,
  botClientDestination,
  type BotCapabilitySection,
} from "../../utils/botClientRoute";
import styles from "./BotCapabilities.module.less";
import home from "./index.module.less";
import capabilitiesArt from "../../assets/bot/capabilities.webp";

const ConnectorsPage = lazy(() => import("../Agent/Connectors"));
const SkillPackagesPage = lazy(() => import("../SkillPackages"));
const KnowledgeBasesPage = lazy(() => import("../KnowledgeBases"));
const AdminPluginsPage = lazy(() => import("../Admin/Plugins"));
const ACPPage = lazy(() => import("../Agent/ACP"));
const CronJobsPage = lazy(() => import("../Control/CronJobs"));
const AgentPanel = lazy(() => import("./BotCapabilityPanels"));

const GROUPS = [
  ["extend", ["connectors", "skills", "skill-packages"]],
  ["know", ["knowledge", "memory"]],
  ["reach", ["channels", "plugins"]],
  ["automate", ["acp", "tasks"]],
] as const satisfies readonly (readonly [
  string,
  readonly BotCapabilitySection[],
])[];

const ICONS: Record<BotCapabilitySection, LucideIcon> = {
  connectors: Plug,
  skills: Sparkles,
  "skill-packages": Package,
  knowledge: Library,
  memory: Notebook,
  channels: Waypoints,
  plugins: Puzzle,
  acp: Bot,
  tasks: CalendarClock,
};

function page(section: BotCapabilitySection): ReactNode {
  switch (section) {
    case "connectors":
      return <ConnectorsPage />;
    case "skill-packages":
      return <SkillPackagesPage />;
    case "knowledge":
      return <KnowledgeBasesPage />;
    case "plugins":
      return <AdminPluginsPage />;
    case "acp":
      return <ACPPage />;
    case "tasks":
      return <CronJobsPage />;
    default:
      return <AgentPanel section={section} />;
  }
}

/**
 * Upstream pages navigate to dashboard paths (``/chat``, ``/skill-packages``,
 * ``/admin/models``…). Inside the Bot client those land on the Bot equivalent,
 * and ``/chat`` on the Bot the area is scoped to.
 */
function BotLinks({ children }: { children: ReactNode }) {
  const context = useContext(UNSAFE_NavigationContext);
  const { pathname: here } = useLocation();
  const { activeAgentId } = useAgent();
  const value = useMemo(() => {
    const { basename, navigator } = context;
    const prefix = basename === "/" ? "" : basename;
    const mapped =
      (go: Navigator["push"]): Navigator["push"] =>
      (to, state, opts) => {
        const path = typeof to === "string" ? parsePath(to) : to;
        const full = path.pathname ?? "";
        const local =
          prefix && full.startsWith(prefix)
            ? full.slice(prefix.length) || "/"
            : full;
        const target = botCapabilityLink(local, activeAgentId);
        if (target === local) return go(to, state, opts);
        go(
          {
            ...path,
            pathname: prefix + target,
            search: target.startsWith(BOT_CAPABILITIES) ? path.search : "",
          },
          target === BOT_SETTINGS ? { ...state, from: here } : state,
          opts,
        );
      };
    const wrapped: Navigator = Object.assign(Object.create(navigator), {
      push: mapped(navigator.push.bind(navigator)),
      replace: mapped(navigator.replace.bind(navigator)),
    });
    return { ...context, navigator: wrapped };
  }, [context, activeAgentId, here]);
  return (
    <UNSAFE_NavigationContext.Provider value={value}>
      {children}
    </UNSAFE_NavigationContext.Provider>
  );
}

/** Point the agent pickers at the Bot the user came from, else the Chief. */
function useInitialBot(from: string | undefined) {
  const [params] = useSearchParams();
  const { setActiveAgent } = useAgent();
  const visited = /^\/octop-bot\/bots\/([^/]+)/.exec(from ?? "")?.[1];
  const requested =
    params.get("bot") ?? (visited ? decodeURIComponent(visited) : null);
  useEffect(() => {
    if (requested) {
      setActiveAgent(requested);
      return;
    }
    let live = true;
    octopBotApi.workspace().then(
      (workspace) => {
        if (live && workspace.chief_id) setActiveAgent(workspace.chief_id);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
    // Once per visit: switching sections keeps the user's own pick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

export default function BotCapabilities() {
  const { t } = useTranslation();
  const user = useCurrentUser();
  const navigate = useNavigate();
  const location = useLocation();
  const { section } = useParams<{ section?: string }>();
  const from: string | undefined = location.state?.from;
  useInitialBot(from);
  const back =
    !from || from.startsWith(BOT_CAPABILITIES)
      ? BOT_HOME
      : botClientDestination(from);
  const allowed = BOT_CAPABILITY_SECTIONS.filter((s) =>
    canAccessPath(user, BOT_CAPABILITY_UPSTREAM[s]),
  );
  const current = allowed.find((s) => s === section);
  if (user && !current && allowed.length > 0)
    return (
      <Navigate
        replace
        to={botCapabilityPath(allowed[0]) + location.search}
        state={location.state}
      />
    );
  const open = (next: BotCapabilitySection) => {
    if (next !== current)
      navigate(botCapabilityPath(next), { state: { from } });
  };
  return (
    <section className={styles.root} data-bot-capabilities>
      <header
        className={`${styles.header} octop-desktop-drag`}
        data-octop-chrome-end-pad
      >
        <Button
          type="text"
          icon={<ArrowLeft size={17} />}
          onClick={() => navigate(back, { replace: true })}
        >
          {t("common.backToChat")}
        </Button>
        <h1>{t("botCapabilities.title")}</h1>
        {current && (
          <span className={styles.crumb}>
            {t(`botCapabilities.sections.${current}`)}
          </span>
        )}
      </header>
      <div className={styles.body}>
        {allowed.length > 0 && (
          <nav className={styles.nav} aria-label={t("botCapabilities.title")}>
            {GROUPS.map(([group, sections]) => {
              const visible = sections.filter((s) => allowed.includes(s));
              if (!visible.length) return null;
              return (
                <div className={styles.group} key={group}>
                  <h2>{t(`botCapabilities.groups.${group}`)}</h2>
                  {visible.map((s) => {
                    const Icon = ICONS[s];
                    return (
                      <button
                        key={s}
                        type="button"
                        className={styles.item}
                        aria-current={s === current ? "page" : undefined}
                        onClick={() => open(s)}
                      >
                        <Icon size={16} />
                        <span>{t(`botCapabilities.sections.${s}`)}</span>
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </nav>
        )}
        <main className={styles.page}>
          {!user ? (
            <Spin className={styles.center} />
          ) : !current ? (
            <Empty
              className={`${styles.center} ${home.illustratedEmpty}`}
              image={<img src={capabilitiesArt} alt="" />}
              description={t("botCapabilities.empty")}
            />
          ) : (
            <Suspense fallback={<Spin className={styles.center} />}>
              <BotLinks>{page(current)}</BotLinks>
            </Suspense>
          )}
        </main>
      </div>
    </section>
  );
}
