"""Built-in provider template loading (octop-harness bundles)."""

from __future__ import annotations

from typing import Any, Literal


def _reasoning_profile(provider_id: str, model_id: str) -> dict[str, Any] | None:
    """Reasoning metadata for bundled models with documented request semantics."""
    provider = provider_id.lower()
    model = model_id.lower()
    enum_efforts = ["low", "medium", "high"]

    if provider in {"openai", "openai-codex"} and (
        model.startswith("gpt-5") or model in {"o3", "o4-mini"}
    ):
        efforts = enum_efforts if model in {"o3", "o4-mini"} else ["minimal", *enum_efforts]
        if model.startswith(("gpt-5.4", "gpt-5.5")):
            efforts.append("xhigh")
        can_disable = model.startswith(("gpt-5.2", "gpt-5.4", "gpt-5.5"))
        return {
            "supported": True,
            "adapter": "openai_reasoning_effort",
            "toggle": can_disable,
            "default_mode": "auto" if can_disable else "enabled",
            "efforts": efforts,
            "default_effort": "medium",
        }

    if provider == "anthropic" and model.startswith(("claude-sonnet-4", "claude-opus-4")):
        return {
            "supported": True,
            "adapter": "anthropic_budget",
            "toggle": True,
            "default_mode": "auto",
            "effort_type": "token_budget",
            "efforts": ["1024", "4096", "8192", "16384"],
            "default_effort": "4096",
        }

    if provider == "gemini" and model.startswith("gemini-") and not model.startswith("gemini-2.0"):
        mandatory = model.startswith("gemini-3") or model == "gemini-2.5-pro"
        return {
            "supported": True,
            "adapter": "openai_reasoning_effort",
            "toggle": not mandatory,
            "default_mode": "enabled" if mandatory else "auto",
            "efforts": enum_efforts,
            "default_effort": "high" if mandatory else "medium",
        }

    if provider == "groq" and "gpt-oss" in model:
        return {
            "supported": True,
            "adapter": "openai_reasoning_effort",
            "toggle": False,
            "default_mode": "enabled",
            "efforts": enum_efforts,
            "default_effort": "medium",
        }

    if provider.startswith("tencent-"):
        if model == "hy4" and provider in {
            "tencent-tokenhub",
            "tencent-token-plan",
            "tencent-token-plan-enterprise-cn",
            "tencent-hy-token-plan",
        }:
            return {
                "supported": True,
                "adapter": "thinking",
                "toggle": True,
                "default_mode": "enabled",
            }
        if model.startswith("minimax-"):
            return {
                "supported": True,
                "adapter": "status_only",
                "toggle": False,
                "default_mode": "enabled",
            }
        if (
            model.startswith("deepseek-v4-")
            or model.startswith("deepseek-v3")
            or model == "deepseek-flash"
        ):
            return {
                "supported": True,
                "adapter": "thinking_nested_effort"
                if provider
                in {
                    "tencent-token-plan",
                    "tencent-token-plan-enterprise-cn",
                    "tencent-coding-plan",
                }
                else "thinking",
                "toggle": True,
                "default_mode": "enabled",
                "efforts": ["high", "max"],
                "default_effort": "high",
            }
        if model.startswith(("glm-", "kimi-")) or model == "tc-code-latest":
            return {
                "supported": True,
                "adapter": "thinking",
                "toggle": True,
                "default_mode": "enabled",
            }
        if model.startswith("hy3") or model.startswith("hy4"):
            return {
                "supported": True,
                "adapter": "status_only",
                "toggle": False,
                "default_mode": "enabled",
            }

    if provider == "deepseek":
        if model == "deepseek-reasoner":
            return {
                "supported": True,
                "adapter": "status_only",
                "toggle": False,
                "default_mode": "enabled",
            }
        if model.startswith("deepseek-v4-") or model == "deepseek-flash":
            return {
                "supported": True,
                "adapter": "thinking",
                "toggle": True,
                "default_mode": "auto",
                "efforts": ["high", "max"],
                "default_effort": "high",
            }

    if provider.startswith("zhipu-") and model.startswith(("glm-4.7", "glm-5")):
        return {
            "supported": True,
            "adapter": "thinking",
            "toggle": True,
            "default_mode": "auto",
        }

    if provider.startswith(("dashscope", "aliyun-")):
        if model.startswith("minimax-") or "-thinking-" in model:
            return {
                "supported": True,
                "adapter": "status_only",
                "toggle": False,
                "default_mode": "enabled",
            }
        if model.startswith(("qwen3", "glm-", "kimi-", "deepseek-")):
            return {
                "supported": True,
                "adapter": "dashscope",
                "toggle": True,
                "default_mode": "auto",
            }

    if provider.startswith("kimi-") and (
        model in {"kimi-k2.5", "kimi-k2.6"} or "thinking" in model
    ):
        dedicated = "thinking" in model
        return {
            "supported": True,
            "adapter": "status_only" if dedicated else "thinking",
            "toggle": not dedicated,
            "default_mode": "enabled" if dedicated else "auto",
        }

    if provider.startswith("minimax-") and model.startswith("minimax-m2"):
        return {
            "supported": True,
            "adapter": "status_only",
            "toggle": False,
            "default_mode": "enabled",
        }

    if provider == "openrouter" and model.startswith(("anthropic/claude-", "google/gemini-2.5")):
        return {
            "supported": True,
            "adapter": "openrouter",
            "toggle": True,
            "default_mode": "auto",
            "efforts": enum_efforts,
            "default_effort": "medium",
        }

    if provider.startswith("opencode-"):
        if model.startswith("minimax-"):
            return {
                "supported": True,
                "adapter": "status_only",
                "toggle": False,
                "default_mode": "enabled",
            }
        if model.startswith(("claude-opus-4-6", "claude-sonnet-4-6")):
            return {
                "supported": True,
                "adapter": "anthropic_adaptive",
                "toggle": True,
                "default_mode": "auto",
                "efforts": ["low", "medium", "high", "max"],
                "default_effort": "high",
            }
        if model == "grok-4.5" or model == "glm-5.2":
            efforts = (
                ["minimal", "low", "medium", "high", "xhigh", "max"]
                if model == "glm-5.2"
                else enum_efforts
            )
            return {
                "supported": True,
                "adapter": "openai_reasoning_effort",
                "toggle": model != "grok-4.5",
                "default_mode": "enabled" if model == "grok-4.5" else "auto",
                "efforts": efforts,
                "default_effort": "high",
            }
        if model.startswith(("deepseek-v4-", "kimi-k", "glm-5.1")):
            return {
                "supported": True,
                "adapter": "thinking",
                "toggle": True,
                "default_mode": "auto",
            }

    return None


def _embedding_model(model_id: str, name: str) -> dict[str, Any]:
    return {
        "id": model_id,
        "name": name,
        "enabled": True,
        "embedding": True,
        "task": "embedding",
        "input": ["text"],
    }


def _embedding_cloud_presets() -> list[dict[str, Any]]:
    """Cloud embedding-only presets shown on the Models → Embedding tab."""
    return [
        {
            "id": "siliconflow-embedding-cn",
            "name": "SiliconFlow",
            "base_url": "https://api.siliconflow.cn/v1",
            "protocol": "openai",
            "api_key_prefix": "sk-",
            "purpose": "embedding",
            "vendor": "siliconflow",
            "vendor_name": "SiliconFlow",
            "variant": "embedding",
            "provider_group": "siliconflow",
            "provider_group_name": "SiliconFlow",
            "provider_variant": "embedding",
            "logo_id": "silicon",
            "models": [
                _embedding_model("Qwen/Qwen3-Embedding-8B", "Qwen3-Embedding-8B"),
                _embedding_model("Qwen/Qwen3-Embedding-4B", "Qwen3-Embedding-4B"),
                _embedding_model("Qwen/Qwen3-Embedding-0.6B", "Qwen3-Embedding-0.6B"),
                _embedding_model("BAAI/bge-m3", "BGE-M3"),
            ],
        },
        {
            "id": "dashscope-embedding",
            "name": "DashScope",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "protocol": "openai",
            "api_key_prefix": "sk-",
            "purpose": "embedding",
            "vendor": "aliyun",
            "vendor_name": "Aliyun",
            "variant": "embedding",
            "provider_group": "aliyun",
            "provider_group_name": "Aliyun",
            "provider_variant": "embedding",
            "logo_id": "dashscope",
            "models": [
                _embedding_model("qwen3.7-text-embedding", "qwen3.7-text-embedding"),
                _embedding_model(
                    "qwen3.7-text-embedding-flash",
                    "qwen3.7-text-embedding-flash",
                ),
                _embedding_model("text-embedding-v4", "text-embedding-v4"),
            ],
        },
    ]


# Lynxce models that read images (checked 2026-11-24 with a desktop screenshot). Computer use
# needs one: its screenshots are stripped before a text-only model sees them.
LYNXCE_VISION_MODELS = frozenset(
    {
        "qwen3.7-plus",
        "qwen3.8-max",
        "kimi-k3",
        "doubao-seed-2.1-turbo",
        "yunxin/doubao-seed-2-1-pro-260628",
    }
)


def lynxce_model_input(model_id: str) -> list[Literal["text", "image", "audio", "video"]]:
    return ["text", "image"] if model_id in LYNXCE_VISION_MODELS else ["text"]


def _lynxce_model(model_id: str, name: str) -> dict[str, Any]:
    return {"id": model_id, "name": name, "enabled": True, "input": lynxce_model_input(model_id)}


LYNXCE_API_PRESET: dict[str, Any] = {
    "id": "lynxce",
    "name": "灵策智算 (Lynxce)",
    "base_url": "https://api.lynxce.cn/api/v1",
    "protocol": "openai",
    "api_key_prefix": "sk-",
    "logo_id": "lynxce",
    "vendor": "lynxce",
    "vendor_name": "灵策智算",
    "provider_group": "lynxce",
    "provider_group_name": "灵策智算",
    "models": [
        _lynxce_model("deepseek-flash", "DeepSeek Flash"),
        _lynxce_model("deepseek-v4-pro", "DeepSeek V4 Pro"),
        _lynxce_model("qwen3.8-max", "Qwen3.8 Max"),
        _lynxce_model("qwen3.8-flash", "Qwen3.8 Flash"),
        _lynxce_model("glm-5.3", "GLM-5.3"),
        _lynxce_model("glm-5.3-flash", "GLM-5.3 Flash"),
        _lynxce_model("kimi-k3", "Kimi K3"),
        _lynxce_model("doubao-seed-2.1-turbo", "Doubao Seed 2.1 Turbo"),
        _lynxce_model("MiniMax-M3", "MiniMax M3"),
    ],
}


def load_provider_presets() -> list[dict[str, Any]]:
    """Serialize octop-harness provider templates for API / CLI."""
    from importlib import resources

    from octop_harness.providers import load_provider_templates, serialize_provider_preset

    bundled = resources.files("octop_harness.providers").joinpath("provider_template.json")
    out = [serialize_provider_preset(p) for p in load_provider_templates(str(bundled))]
    if not any(p.get("id") == "openai-codex" for p in out):
        out.insert(
            0,
            {
                "id": "openai-codex",
                "name": "OpenAI (ChatGPT)",
                "base_url": "https://chatgpt.com/backend-api/codex",
                "protocol": "openai",
                "api_key_prefix": "",
                "auth_method": "codex_oauth",
                "models": [
                    {"id": "gpt-5.4", "name": "GPT-5.4", "enabled": True, "input": ["text"]},
                    {
                        "id": "gpt-5.4-mini",
                        "name": "GPT-5.4 mini",
                        "enabled": True,
                        "input": ["text"],
                    },
                    {"id": "gpt-5.5", "name": "GPT-5.5", "enabled": True, "input": ["text"]},
                ],
                "logo_id": "openai",
            },
        )
    if not any(p.get("id") == "onnx" for p in out):
        from octop.infra.agents.providers.onnx_catalog import ONNX_PRESET_MODEL_IDS

        onnx_preset = {
            "id": "onnx",
            "name": "ONNX (Local)",
            "base_url": "",
            "protocol": "openai",
            "api_key_prefix": "",
            "purpose": "embedding",
            "models": [
                {
                    "id": mid,
                    "name": mid,
                    "enabled": False,
                    "embedding": True,
                    "task": "embedding",
                    "input": ["text"],
                }
                for mid in ONNX_PRESET_MODEL_IDS
            ],
            "logo_id": "onnx",
        }
        insert_at = next(
            (i + 1 for i, p in enumerate(out) if p.get("id") == "ollama"),
            len(out),
        )
        out.insert(insert_at, onnx_preset)
    if not any(p.get("id") == "magpie" for p in out):
        from octop.infra.agents.providers.magpie import magpie_preset

        out.insert(0, magpie_preset())
    if not any(p.get("id") == LYNXCE_API_PRESET["id"] for p in out):
        # Octop Bot's own model service, listed first: one Lynxce API key reaches
        # the account's models through an OpenAI-compatible endpoint.
        out.insert(
            0, {**LYNXCE_API_PRESET, "models": [dict(m) for m in LYNXCE_API_PRESET["models"]]}
        )
    if not any(p.get("purpose") == "embedding" and p.get("id") != "onnx" for p in out):
        out.extend(_embedding_cloud_presets())
    for preset in out:
        provider_id = str(preset.get("id") or "")
        for model in preset.get("models") or []:
            profile = _reasoning_profile(provider_id, str(model.get("id") or ""))
            if profile is not None:
                model["reasoning"] = True
                model["reasoning_config"] = profile
    return out
