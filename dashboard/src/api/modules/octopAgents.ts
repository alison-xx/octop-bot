import { request, requestUpload } from "../request";

export const octopAgentsApi = {
  createTeammate: (name: string, role: string) =>
    request<{ agent_id: string }>("/agents", {
      method: "POST",
      body: JSON.stringify({ name, description: role, system_prompt: role }),
    }),
  setDefaultModel: (agentId: string, model: string | null) =>
    request<void>(`/agents/${encodeURIComponent(agentId)}`, {
      method: "PATCH",
      body: JSON.stringify({ default_model: model }),
    }),
  start: (agentId: string) =>
    request("/agents/" + encodeURIComponent(agentId) + "/start", {
      method: "POST",
    }),
  markRead: (agentId: string) =>
    request<void>(`/agents/${encodeURIComponent(agentId)}/read`, {
      method: "POST",
    }),

  uploadAvatar: (agentId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return requestUpload<{ icon_url: string }>(
      `/agents/${encodeURIComponent(agentId)}/avatar`,
      body,
    );
  },

  deleteAvatar: (agentId: string) =>
    request<void>(`/agents/${encodeURIComponent(agentId)}/avatar`, {
      method: "DELETE",
    }),
};
