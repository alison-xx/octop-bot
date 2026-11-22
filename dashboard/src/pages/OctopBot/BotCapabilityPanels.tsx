import { Empty } from "antd";
import { useTranslation } from "react-i18next";
import PageShell, { pageShellStyles } from "../../layouts/PageShell";
import { useAgent } from "../../context/AgentContext";
import { useIsMobile } from "../../hooks/useIsMobile";
import { isTeamAgent } from "../../utils/teamAgent";
import SkillsTabs from "../Agent/Skills/components/SkillsTabs";
import MemoryPanel from "../Agent/Memory/MemoryPanel";
import ChannelsPanel from "../Agent/Channels/ChannelsPanel";

export type AgentCapability = "skills" | "memory" | "channels";

/**
 * The agent-scoped Personalization tabs as standalone pages. Personalization
 * itself routes its tabs under ``/personalization``, so the Bot client mounts
 * the same panels with the same picker rules instead.
 */
export default function BotCapabilityPanel({
  section,
}: {
  section: AgentCapability;
}) {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const { activeAgentId, activeAgent } = useAgent();
  // Memory and channels also belong to team hosts; skills are per expert.
  const teams = section !== "skills";
  const body =
    !teams && isTeamAgent(activeAgent) ? (
      <Empty
        style={{ marginTop: 24 }}
        description={t("agentSelector.teamNeedsExpert", {
          name: activeAgent?.name ?? "",
        })}
      />
    ) : section === "memory" && isMobile ? (
      <MemoryPanel agentId={activeAgentId} fill={false} />
    ) : (
      <div className={pageShellStyles.fillChild}>
        {section === "skills" ? (
          <SkillsTabs agentId={activeAgentId} />
        ) : section === "memory" ? (
          <MemoryPanel agentId={activeAgentId} fill />
        ) : (
          <ChannelsPanel agentId={activeAgentId} />
        )}
      </div>
    );
  return (
    <PageShell
      title={t(`pageShell.${section}.title`)}
      subtitle={t(`pageShell.${section}.subtitle`)}
      agentScoped
      showTeams={teams}
      fill={!isMobile}
    >
      {body}
    </PageShell>
  );
}
