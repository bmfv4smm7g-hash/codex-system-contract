"""Declarative, source-bound links from user configuration to canonical surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ConfigEffectSpec:
    id: str
    config_paths: tuple[str, ...]
    target_id: str
    relation: str
    behavior: str
    proof_tier: str = "canonical_source_link"
    condition: str | None = None
    legacy_setting: str | None = None
    source_checks: tuple[tuple[str, str], ...] = ()


# Frozen v10 compatibility settings. The v10 implementation remains immutable;
# this tuple is only a parity oracle proving that the canonical graph no longer
# needs to consume its wire_affecting_settings output.
_FROZEN_V10_SETTINGS = (
    "model",
    "model_provider",
    "model_reasoning_effort",
    "model_reasoning_summary",
    "model_verbosity",
    "service_tier",
    "web_search",
    "responses_api_metadata",
    "mcp_servers",
    "mcp_oauth_credentials_store",
    "mcp_oauth_callback_port",
    "mcp_oauth_callback_url",
    "mcp_optional_startup_grace_ms",
    "apps_mcp_product_sku",
    "chatgpt_base_url",
    "openai_base_url",
    "orchestrator",
)


def _s(
    id: str,
    paths: tuple[str, ...],
    target: str,
    relation: str,
    behavior: str,
    *,
    legacy: str | None = None,
    condition: str | None = None,
    checks: tuple[tuple[str, str], ...] = (),
) -> ConfigEffectSpec:
    return ConfigEffectSpec(
        id=id,
        config_paths=paths,
        target_id=target,
        relation=relation,
        behavior=behavior,
        condition=condition,
        legacy_setting=legacy,
        source_checks=checks,
    )


_SPECS = (
    _s("effect.model", ("model",), "surface.responses.body.model", "selects", "Selects the model slug serialized into Responses requests.", legacy="model"),
    _s("effect.model.routing_hint", ("model",), "surface.routing.hint.model", "projects_to", "Projects model identity into first-party Codex routing hints.", legacy="model"),
    _s("effect.model.prompt_cache", ("model",), "surface.responses.prompt_cache_key", "participates_in", "Participates indirectly in request/cache identity.", legacy="model"),
    _s("effect.model_provider", ("model_provider",), "surface.provider.selection", "selects", "Selects the model provider and endpoint/API plane.", legacy="model_provider"),
    _s("effect.model_provider.headers", ("model_provider",), "surface.provider.headers", "selects", "Selects provider authentication and default header layers.", legacy="model_provider"),
    _s("effect.model_provider.capabilities", ("model_provider",), "surface.provider.capabilities", "bounds", "Provider capabilities bound tools, WebSockets, hosted search/image behavior, and remote compaction.", legacy="model_provider"),
    _s("effect.reasoning_effort", ("model_reasoning_effort",), "surface.responses.body.reasoning.effort", "projects_to", "Controls normalized reasoning effort.", legacy="model_reasoning_effort"),
    _s("effect.reasoning_summary", ("model_reasoning_summary",), "surface.responses.body.reasoning.summary", "projects_to", "Controls reasoning-summary request policy.", legacy="model_reasoning_summary"),
    _s("effect.reasoning_summary.delivery", ("model_reasoning_summary",), "surface.responses.body.stream_options.reasoning_summary_delivery", "projects_to", "Can request sequential cutoff delivery.", legacy="model_reasoning_summary", condition="ConcurrentReasoningSummaries enabled"),
    _s("effect.verbosity", ("model_verbosity",), "surface.responses.body.text.verbosity", "projects_to", "Controls Responses text verbosity when supported by the model.", legacy="model_verbosity"),
    _s("effect.service_tier", ("service_tier",), "surface.responses.body.service_tier", "projects_to", "Selects the requested service tier after support/default filtering.", legacy="service_tier"),
    _s("effect.service_tier.routing_hint", ("service_tier",), "surface.routing.hint.tier", "projects_to", "Projects service tier into first-party Codex routing hints.", legacy="service_tier"),
    _s("effect.web_search", ("web_search",), "surface.tool.web_search", "controls_exposure", "Controls hosted web-search exposure in full Responses.", legacy="web_search"),
    _s("effect.web_search.responses_lite", ("web_search",), "surface.responses_lite.hosted_tools", "suppressed_by", "Hosted model tools are omitted under Responses Lite.", legacy="web_search", condition="model uses Responses Lite"),
    _s("effect.responses_metadata", ("responses_api_metadata", "responses_api_metadata.*"), "surface.turn_metadata.extra", "merges_into", "Validated product metadata is flattened into canonical nested turn metadata.", legacy="responses_api_metadata"),
    _s("effect.responses_metadata.precedence", ("responses_api_metadata", "responses_api_metadata.*"), "surface.turn_metadata.extra_precedence", "overrides", "Configured metadata overrides duplicate app-server responsesapiClientMetadata keys at merge time.", legacy="responses_api_metadata"),
    _s("effect.mcp_servers", ("mcp_servers", "mcp_servers.*"), "surface.mcp.registry", "defines", "Defines MCP server registrations and runtime lifecycle inputs.", legacy="mcp_servers"),
    _s("effect.mcp_servers.transport", ("mcp_servers", "mcp_servers.*"), "surface.mcp.transport", "configures", "Defines stdio or Streamable HTTP MCP transport.", legacy="mcp_servers"),
    _s("effect.mcp_servers.model_tools", ("mcp_servers", "mcp_servers.*"), "surface.mcp.model_tools", "controls_exposure", "Server filters and runtime state control which MCP tools become model-visible.", legacy="mcp_servers"),
    _s("effect.mcp_servers.turn_metadata", ("mcp_servers", "mcp_servers.*"), "surface.turn_metadata.tool_namespaces_info", "contributes_to", "Effective MCP namespaces/functions can be recorded in turn metadata.", legacy="mcp_servers", condition="Responses Lite plus turn_metadata_includes_tool_info"),
    _s("effect.mcp_oauth.credentials_store", ("mcp_oauth_credentials_store",), "surface.mcp.oauth.credentials_store", "selects", "Selects the resolved MCP OAuth credential-store mode.", legacy="mcp_oauth_credentials_store", checks=(("config_toml", "pub mcp_oauth_credentials_store:"), ("core_config", "resolve_mcp_oauth_credentials_store_mode("))),
    _s("effect.mcp_oauth.callback_port", ("mcp_oauth_callback_port",), "surface.mcp.oauth.callback_port", "configures", "Configures the local OAuth callback listener port; otherwise the OS chooses an ephemeral port.", legacy="mcp_oauth_callback_port", checks=(("config_toml", "pub mcp_oauth_callback_port:"), ("core_config", "mcp_oauth_callback_port: cfg.mcp_oauth_callback_port"))),
    _s("effect.mcp_oauth.callback_url", ("mcp_oauth_callback_url",), "surface.mcp.oauth.callback_url", "configures", "Selects the OAuth authorization redirect URI while the local callback listener remains loopback-bound.", legacy="mcp_oauth_callback_url", checks=(("config_toml", "pub mcp_oauth_callback_url:"), ("core_config", "mcp_oauth_callback_url: cfg.mcp_oauth_callback_url.clone()"))),
    _s("effect.mcp.startup_grace", ("mcp_optional_startup_grace_ms",), "surface.mcp.startup.optional_grace", "bounds", "Sets shared optional-server startup grace, falling back to the compiled default.", legacy="mcp_optional_startup_grace_ms", checks=(("config_toml", "pub mcp_optional_startup_grace_ms:"), ("core_config", "DEFAULT_OPTIONAL_MCP_STARTUP_GRACE"))),
    _s("effect.mcp.apps_product_sku", ("apps_mcp_product_sku",), "surface.mcp.apps.product_sku", "projects_to", "Forwards the configured product SKU into the host-owned Codex Apps MCP runtime.", legacy="apps_mcp_product_sku", checks=(("config_toml", "pub apps_mcp_product_sku:"), ("core_config", "apps_mcp_product_sku: cfg.apps_mcp_product_sku.clone()"))),
    _s("effect.chatgpt_base", ("chatgpt_base_url",), "surface.routing.chatgpt_auxiliary", "routes", "Selects the ChatGPT auxiliary backend authority.", legacy="chatgpt_base_url"),
    _s("effect.chatgpt_base.apps_mcp", ("chatgpt_base_url",), "surface.mcp.apps.ps_route", "routes", "Forms the host-owned Codex Apps MCP backend route.", legacy="chatgpt_base_url"),
    _s("effect.openai_base", ("openai_base_url",), "surface.routing.model_provider", "routes", "Overrides the built-in OpenAI-compatible provider authority.", legacy="openai_base_url"),
    _s("effect.orchestrator.skills", ("orchestrator.skills.enabled",), "surface.orchestrator.skills_enabled", "controls_exposure", "Controls whether orchestrator-owned skills are exposed to the model; missing enabled defaults true.", legacy="orchestrator", checks=(("config_toml", "pub orchestrator: Option<OrchestratorToml>"), ("core_config", "orchestrator_skills_enabled"), ("core_config", "resolve_orchestrator_feature_enabled"))),
    _s("effect.orchestrator.mcp", ("orchestrator.mcp.enabled",), "surface.orchestrator.mcp_enabled", "controls_exposure", "Controls whether orchestrator-owned MCP tools are exposed to the model; missing enabled defaults true.", legacy="orchestrator", checks=(("core_config", "orchestrator_mcp_enabled"),)),
    _s("effect.provider_base", ("model_providers.*.base_url",), "surface.routing.model_provider", "routes", "Defines a configured provider's API authority."),
    _s("effect.provider_auth", ("model_providers.*.env_key", "model_providers.*.experimental_bearer_token", "model_providers.*.auth", "model_providers.*.aws"), "surface.provider.credentials", "configures", "Configures provider-owned credentials and disables official experimental-context activation."),
    _s("effect.provider_openai_auth", ("model_providers.*.requires_openai_auth",), "surface.provider.openai_auth_requirement", "configures", "Controls whether the provider consumes Codex-managed OpenAI/ChatGPT authentication."),
    _s("effect.context_management", ("features.context_management", "features.context_management.experimental_mode"), "surface.context_management.activation", "requests_enablement", "Requests experimental no-summary context management; account/provider/model gates still apply."),
    _s("effect.token_budget", ("features.token_budget", "features.token_budget.enabled"), "surface.context_management.rollover", "enables", "Enables token-budget context metadata and fresh-window rollover mechanics."),
    _s("effect.history_notes", ("features.token_budget.use_history_notes_extension",), "surface.context_management.history_notes", "enables", "Exposes remote History/Notes tools and the thread-hint contributor."),
    _s("effect.tool_metadata", ("features.tool_registry.turn_metadata_includes_tool_info",), "surface.turn_metadata.tool_namespaces_info", "enables", "Includes authoritative tool namespace/function information in per-turn metadata when applicable."),
)


def effect_specs() -> tuple[ConfigEffectSpec, ...]:
    return _SPECS


def legacy_compatibility_settings() -> tuple[str, ...]:
    return _FROZEN_V10_SETTINGS


def expanded_config_paths(spec: ConfigEffectSpec, available_paths: Iterable[str]) -> tuple[str, ...]:
    available = set(available_paths)
    result: set[str] = set()
    for path in spec.config_paths:
        if path in available:
            result.add(path)
        profile = f"profiles.*.{path}"
        if profile in available:
            result.add(profile)
    return tuple(sorted(result))
