"""Octop Bot cloud: what a tenant's agent config may hold.

On a cloud server every Lynxce account is a tenant, and a tenant's agents share the server
with everyone else's. Layout, storage, runtime and guard settings are the server's to choose;
a tenant's agent config holds only the Bot's own preferences.

Two layers:

- :func:`strip_tenant_input` on every config a tenant writes (create, update, import): only
  ``TENANT_KEYS`` survive;
- :func:`enforce_tenant_config` when the harness config is built: whatever the stored config
  says (an older row, another write path), a tenant's agent runs on its object-store backend,
  in the server's own folder for it, with only ``TENANT_KEYS`` besides.
"""

from __future__ import annotations

from typing import Any

# Top-level keys a tenant's config may hold: how the Bot talks, thinks and which of the
# server's own tools, skills and plugins it uses. Anything else is dropped. Server-owned layout keys are set again by
# ``enforce_tenant_config`` and by the agent manager, never taken from a tenant.
TENANT_KEYS = frozenset(
    {
        # Persona, profile and appearance.
        "persona",
        "octop_bot",
        "color",
        "icon_name",
        "icon_url",
        "welcome_message",
        "published_expert_id",
        # The server's catalog, chosen per Bot.
        "tools_disabled",
        "skills_disabled",
        "skills_enabled",
        "skill_package_ids",
        "plugins",
        "knowledge_base_ids",
        "web_search_tools",
        # Model and turn settings.
        "default_model",
        "model",
        "temperature",
        "top_p",
        "max_tokens",
        "max_iters",
        "max_input_length",
        "tool_call_limit_enabled",
        "tool_call_run_limit",
        "response_mode",
        "conversation_mode",
        "peer_invoke_mode",
        "compaction",
        "summarization",
        "summarization_enabled",
        "summarization_keep",
        "summarization_trigger",
        "summarization_trim_tokens",
        "locale",
        # Memory switches only (see MEMORY_HOST_KEYS).
        "memory",
    }
)
# Inside ``memory``: storage settings, chosen by the server. The rest (on/off switches) stays.
MEMORY_HOST_KEYS = frozenset(
    {
        "backend",
        "db_path",
        "dedup_db_path",
        "dsn",
        "database",
        "path",
        "use_control_plane_dsn",
    }
)


# Inside ``octop_bot`` (written by the server, e.g. a private Bot): the keys it may hold.
OCTOP_BOT_KEYS = frozenset({"private"})


def _switches(value: Any) -> dict[str, bool]:
    return (
        {str(k): v for k, v in value.items() if isinstance(v, bool)}
        if isinstance(value, dict)
        else {}
    )


def _plugins(value: Any) -> dict[str, Any]:
    """Per plugin: only on/off switches (the plugin and its tools), no tool settings."""
    out: dict[str, Any] = {}
    for plugin_id, entry in value.items() if isinstance(value, dict) else ():
        if isinstance(entry, bool):
            out[str(plugin_id)] = entry
        elif isinstance(entry, dict):
            kept: dict[str, Any] = {}
            if isinstance(entry.get("enabled"), bool):
                kept["enabled"] = entry["enabled"]
            if isinstance(entry.get("tools"), dict):
                kept["tools"] = _switches(entry["tools"])
            out[str(plugin_id)] = kept
    return out


def strip_tenant_input(config: dict[str, Any]) -> dict[str, Any]:
    """``config`` with only what a tenant may set (a new dict)."""
    out = {key: value for key, value in config.items() if key in TENANT_KEYS}
    memory = out.get("memory")
    if isinstance(memory, dict):
        out["memory"] = {k: v for k, v in memory.items() if k not in MEMORY_HOST_KEYS}
    elif "memory" in out:
        out.pop("memory")
    if "octop_bot" in out:
        section = out["octop_bot"]
        out["octop_bot"] = (
            {k: v for k, v in section.items() if k in OCTOP_BOT_KEYS}
            if isinstance(section, dict)
            else {}
        )
    if "plugins" in out:
        out["plugins"] = _plugins(out["plugins"])
    return out


def enforce_tenant_config(
    config: dict[str, Any],
    *,
    user_id: int,
    agent_id: str,
    workspace_dir: str,
    system_files_path: str,
) -> dict[str, Any]:
    """The config a tenant's agent actually runs with: stripped, on its object-store backend,
    in ``workspace_dir`` (the server's folder for this agent)."""
    from octop.infra.cloud.bot_cloud.files import agent_backend  # noqa: PLC0415

    out = strip_tenant_input(config)
    out["backend"] = agent_backend(user_id, agent_id)
    out["workspace_dir"] = workspace_dir
    out["system_files_path"] = system_files_path
    return out
