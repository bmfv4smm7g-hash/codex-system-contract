"""Version-aware source extraction for the Responses model-catalog refresh flow."""
from __future__ import annotations

from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile

EXTRACTOR_ID = "extractor.responses_server_response"
CATALOG_VARIANT_IDENTITY_AWARE = "identity_aware"
CATALOG_VARIANT_ETAG_ONLY = "etag_only"
CATALOG_VARIANT_UNKNOWN = "unknown"
CAPABILITY_VARIANT_ACCESS_PROGRAMS = "access_programs_metadata"
CAPABILITY_VARIANT_LEGACY = "legacy_without_access_programs_metadata"
CAPABILITY_VARIANT_UNKNOWN = "unknown"


def _missing(
    diagnostics: DiagnosticCollector,
    *,
    code: str,
    token: str,
    source: SourceFile,
    entity: str,
) -> None:
    diagnostics.emit(
        code=code,
        severity="error",
        category="responses_server_response",
        message=f"Required server-response source token is missing: {token}",
        extractor_id=EXTRACTOR_ID,
        entity_id=entity,
        source_refs=[source.spec_id],
        details={"path": source.selected_path, "token": token},
        recoverable=False,
        strict_failure=True,
    )


def _require(
    diagnostics: DiagnosticCollector,
    source: SourceFile,
    entity: str,
    tokens: tuple[tuple[str, str], ...],
) -> bool:
    complete = True
    for code, token in tokens:
        if token not in source.text:
            complete = False
            _missing(
                diagnostics,
                code=code,
                token=token,
                source=source,
                entity=entity,
            )
    return complete


def catalog_variant(manager: SourceFile, provider_models: SourceFile) -> str:
    """Classify the catalog implementation from source-owned return/apply shapes."""

    identity_markers = (
        "ModelsEndpointResponse {" in manager.text,
        "self.apply_remote_models(entry).await" in manager.text,
        "Ok(ModelsEndpointResponse {" in provider_models.text,
    )
    etag_only_markers = (
        "CoreResult<(Vec<ModelInfo>, Option<String>)>" in provider_models.text,
        "self.apply_remote_models(models.clone()).await" in manager.text,
        ".refresh_ttl(&crate::client_version_to_whole()).await" in manager.text,
    )
    if all(identity_markers):
        return CATALOG_VARIANT_IDENTITY_AWARE
    if all(etag_only_markers):
        return CATALOG_VARIANT_ETAG_ONLY
    return CATALOG_VARIANT_UNKNOWN


def capability_variant(model_protocol: SourceFile, app_model_protocol: SourceFile) -> str:
    """Classify whether model discovery advertises access-program capability metadata."""

    core_has = "pub available_access_programs: Option<ModelAccessPrograms>" in model_protocol.text
    app_has = (
        "pub struct ModelAccessPrograms" in app_model_protocol.text
        and "pub cyber: Vec<CyberAccessProgram>" in app_model_protocol.text
        and "pub available_access_programs: Option<ModelAccessPrograms>" in app_model_protocol.text
    )
    if core_has and app_has:
        return CAPABILITY_VARIANT_ACCESS_PROGRAMS
    if not core_has and not app_has:
        return CAPABILITY_VARIANT_LEGACY
    return CAPABILITY_VARIANT_UNKNOWN


def validate_capability_fingerprint_sources(
    model_protocol: SourceFile,
    app_model_protocol: SourceFile,
    core_client: SourceFile,
    startup: SourceFile,
    turn: SourceFile,
    prewarm_turn_context: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[bool, str]:
    """Validate catalog capability metadata and startup-prewarm projection boundaries."""

    variant = capability_variant(model_protocol, app_model_protocol)
    complete = True
    if variant == CAPABILITY_VARIANT_ACCESS_PROGRAMS:
        complete &= _require(
            diagnostics,
            model_protocol,
            "responses_server_response.model_capability_fingerprint.catalog",
            (
                (
                    "RESPONSES_MODEL_ACCESS_PROGRAMS_METADATA_MISSING",
                    "pub available_access_programs: Option<ModelAccessPrograms>",
                ),
                ("RESPONSES_MODEL_COMP_HASH_MISSING", "pub comp_hash: Option<String>"),
            ),
        )
        complete &= _require(
            diagnostics,
            app_model_protocol,
            "responses_server_response.model_capability_fingerprint.app_server",
            (
                ("RESPONSES_APP_MODEL_ACCESS_PROGRAMS_TYPE_MISSING", "pub struct ModelAccessPrograms"),
                ("RESPONSES_APP_MODEL_ACCESS_PROGRAMS_CYBER_MISSING", "pub cyber: Vec<CyberAccessProgram>"),
                (
                    "RESPONSES_APP_MODEL_AVAILABLE_ACCESS_PROGRAMS_MISSING",
                    "pub available_access_programs: Option<ModelAccessPrograms>",
                ),
            ),
        )
    elif variant == CAPABILITY_VARIANT_UNKNOWN:
        complete = False
        _missing(
            diagnostics,
            code="RESPONSES_MODEL_ACCESS_PROGRAMS_METADATA_PARTIAL_DRIFT",
            token="matching core/app-server available_access_programs capability metadata",
            source=model_protocol,
            entity="responses_server_response.model_capability_fingerprint.catalog",
        )

    complete &= _require(
        diagnostics,
        core_client,
        "responses_server_response.model_capability_fingerprint.request_projection",
        (
            (
                "RESPONSES_ACCESS_PROGRAMS_REQUEST_PROJECTION_MISSING",
                "request.access_programs = cyber_access_program::for_auth(",
            ),
            ("RESPONSES_ACCESS_PROGRAMS_DEFAULT_NONE_MISSING", "access_programs: None"),
        ),
    )
    complete &= _require(
        diagnostics,
        turn,
        "responses_server_response.model_capability_fingerprint.prompt_projection",
        (("RESPONSES_PROMPT_CYBER_ACCESS_PROGRAM_MISSING", "cyber_access_program: turn_context.cyber_access_program"),),
    )
    complete &= _require(
        diagnostics,
        startup,
        "responses_server_response.model_capability_fingerprint.prewarm",
        (
            ("RESPONSES_PREWARM_REQUEST_KIND_MISSING", "CodexResponsesRequestKind::Prewarm"),
            ("RESPONSES_PREWARM_WEBSOCKET_CALL_MISSING", ".prewarm_websocket("),
            ("RESPONSES_PREWARM_PROMPT_MISSING", "let startup_prompt = build_prompt("),
        ),
    )
    complete &= _require(
        diagnostics,
        prewarm_turn_context,
        "responses_server_response.model_capability_fingerprint.prewarm_context",
        (
            (
                "RESPONSES_PREWARM_DEFAULT_OPTIONS_MISSING",
                "NewTurnContextOptions::default()",
            ),
            (
                "RESPONSES_PREWARM_CYBER_OPTION_MISSING",
                "pub(crate) cyber_access_program: Option<CyberAccessProgram>",
            ),
        ),
    )
    return complete, variant


def capability_fingerprint_contract(variant: str) -> dict[str, Any]:
    """Describe source-proven model-generation fingerprint semantics."""

    current = variant == CAPABILITY_VARIANT_ACCESS_PROGRAMS
    legacy = variant == CAPABILITY_VARIANT_LEGACY
    return {
        "catalog_schema_variant": variant,
        "catalog_capability_path": "models[].available_access_programs.cyber",
        "catalog_capability_present": current,
        "legacy_catalog_metadata_absent": legacy,
        "slug_is_stable_identity": False,
        "capability_fingerprint_use": (
            "field presence and values can distinguish catalog/model generations or aliases, "
            "but do not uniquely prove one model family by themselves"
        ),
        "gpt6_interpretation": (
            "current Codex source contains GPT-6 family models, but access-program capability "
            "metadata is not source-proven to be exclusive to GPT-6"
        ),
        "comp_hash": {
            "path": "models[].comp_hash",
            "meaning": "opaque compaction-compatibility identifier; useful as an additional capability fingerprint",
            "unique_model_identity": False,
        },
        "request_projection": {
            "field": "access_programs.cyber",
            "source": "turn/start cyberAccessProgram -> Prompt.cyber_access_program -> Responses request",
            "auth_gate": "ChatGPT auth; omitted when no explicit program is selected",
            "is_catalog_capability": False,
        },
        "startup_prewarm": {
            "request_kind": "CodexResponsesRequestKind::Prewarm",
            "turn_options": "NewTurnContextOptions::default()",
            "cyber_access_program": None,
            "access_programs_serialized": False,
            "identity_implication": (
                "the current startup prewarm request itself does not expose the access-program "
                "capability; use the model catalog capability vector (and its x-models-etag invalidation signal)"
            ),
        },
    }


def validate_catalog_sources(
    turn: SourceFile,
    manager: SourceFile,
    endpoint: SourceFile,
    provider_models: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[bool, str]:
    """Validate shared flow invariants and the detected version-specific shape."""

    variant = catalog_variant(manager, provider_models)
    complete = _require(
        diagnostics,
        turn,
        "responses_server_response.models_catalog.dispatch",
        (
            ("RESPONSES_MODELS_ETAG_DISPATCH_MISSING", "ResponseEvent::ModelsEtag(etag)"),
            (
                "RESPONSES_MODELS_ETAG_MANAGER_CALL_MISSING",
                ".refresh_if_new_etag(etag, turn_context.config.http_client_factory())",
            ),
        ),
    )
    complete &= _require(
        diagnostics,
        manager,
        "responses_server_response.models_catalog.manager",
        (
            ("RESPONSES_MODELS_ETAG_MANAGER_IMPL_MISSING", "async fn refresh_if_new_etag"),
            (
                "RESPONSES_MODELS_ETAG_COMPARE_MISSING",
                "current_etag.as_deref() == Some(etag.as_str())",
            ),
            (
                "RESPONSES_MODELS_ETAG_ONLINE_REFRESH_MISSING",
                ".refresh_available_models(RefreshStrategy::Online, &http_client_factory)",
            ),
            ("RESPONSES_MODELS_ETAG_ONLINE_ARM_MISSING", "RefreshStrategy::Online =>"),
            (
                "RESPONSES_MODELS_ETAG_ONLINE_FETCH_MISSING",
                "self.fetch_and_update_models(http_client_factory).await",
            ),
            ("RESPONSES_MODELS_CATALOG_FETCH_MISSING", "async fn fetch_and_update_models"),
            (
                "RESPONSES_MODELS_CATALOG_ENDPOINT_CALL_MISSING",
                ".list_models(&client_version, http_client_factory.clone())",
            ),
            ("RESPONSES_MODELS_CACHE_ENTRY_MISSING", "let entry = ModelsCacheEntry {"),
            ("RESPONSES_MODELS_CACHE_STORE_MISSING", "cache.store(&entry)"),
        ),
    )
    complete &= _require(
        diagnostics,
        provider_models,
        "responses_server_response.models_catalog.provider_bridge",
        (
            ("RESPONSES_MODELS_PROVIDER_ENDPOINT_MISSING", 'const MODELS_ENDPOINT: &str = "/models"'),
            (
                "RESPONSES_MODELS_PROVIDER_REQUEST_URL_MISSING",
                "ModelsClient::<ReqwestTransport>::request_url(&api_provider, client_version)",
            ),
            (
                "RESPONSES_MODELS_PROVIDER_LIST_CALL_MISSING",
                ".list_models(request_url, HeaderMap::new())",
            ),
        ),
    )
    complete &= _require(
        diagnostics,
        endpoint,
        "responses_server_response.models_catalog.http",
        (
            ("RESPONSES_MODELS_HTTP_PATH_MISSING", 'fn path() -> &\'static str {\n        "models"'),
            (
                "RESPONSES_MODELS_HTTP_GET_MISSING",
                "provider.build_request(Method::GET, Self::path())",
            ),
            ("RESPONSES_MODELS_CLIENT_VERSION_QUERY_MISSING", "client_version={client_version}"),
            ("RESPONSES_MODELS_HTTP_ETAG_MISSING", ".get(ETAG)"),
            (
                "RESPONSES_MODELS_BODY_DECODE_MISSING",
                "let ModelsResponse { models } = serde_json::from_slice::<ModelsResponse>(&resp.body)",
            ),
            ("RESPONSES_MODELS_HTTP_RESULT_MISSING", "Ok((models, header_etag))"),
        ),
    )

    if variant == CATALOG_VARIANT_IDENTITY_AWARE:
        complete &= _require(
            diagnostics,
            manager,
            "responses_server_response.models_catalog.manager.identity_aware",
            (
                (
                    "RESPONSES_MODELS_ETAG_IDENTITY_COMPARE_MISSING",
                    "Some(&identity) == self.endpoint_client.identity().as_ref()",
                ),
                (
                    "RESPONSES_MODELS_ETAG_TTL_RENEW_MISSING",
                    ".refresh_ttl(&crate::client_version_to_whole(), &identity, &etag)",
                ),
                (
                    "RESPONSES_MODELS_IN_MEMORY_APPLY_MISSING",
                    "self.apply_remote_models(entry).await",
                ),
            ),
        )
        complete &= _require(
            diagnostics,
            provider_models,
            "responses_server_response.models_catalog.provider_bridge.identity_aware",
            (("RESPONSES_MODELS_PROVIDER_RESULT_MISSING", "Ok(ModelsEndpointResponse {"),),
        )
    elif variant == CATALOG_VARIANT_ETAG_ONLY:
        complete &= _require(
            diagnostics,
            manager,
            "responses_server_response.models_catalog.manager.etag_only",
            (
                (
                    "RESPONSES_MODELS_ETAG_TTL_RENEW_MISSING",
                    ".refresh_ttl(&crate::client_version_to_whole()).await",
                ),
                (
                    "RESPONSES_MODELS_IN_MEMORY_APPLY_MISSING",
                    "self.apply_remote_models(models.clone()).await",
                ),
            ),
        )
        complete &= _require(
            diagnostics,
            provider_models,
            "responses_server_response.models_catalog.provider_bridge.etag_only",
            (
                (
                    "RESPONSES_MODELS_PROVIDER_RESULT_MISSING",
                    "CoreResult<(Vec<ModelInfo>, Option<String>)>",
                ),
            ),
        )
    else:
        complete = False
        _missing(
            diagnostics,
            code="RESPONSES_MODELS_CATALOG_VARIANT_UNKNOWN",
            token="recognized identity_aware or etag_only models-catalog implementation",
            source=manager,
            entity="responses_server_response.models_catalog.variant",
        )

    return complete, variant


def models_catalog_contract(variant: str) -> dict[str, Any]:
    """Describe only semantics proven by the detected source implementation."""

    if variant == CATALOG_VARIANT_IDENTITY_AWARE:
        state = "current in-memory ModelsCacheEntry identity + etag"
        match_condition = "same endpoint identity and current_etag == received etag"
        on_match = (
            "do not refetch /models; renew persistent cache TTL using client version, "
            "endpoint identity, and etag when a cache is present, then return"
        )
        on_mismatch = (
            "refresh_available_models with RefreshStrategy::Online when etag mismatches "
            "or endpoint identity changes"
        )
        returns_to_manager = "ModelsEndpointResponse { models, etag, identity }"
        cache_entry = (
            "ModelsCacheEntry { fetched_at, etag, client_version, identity, models }"
        )
        in_memory_catalog = "apply_remote_models(entry) after identity validation"
    elif variant == CATALOG_VARIANT_ETAG_ONLY:
        state = "current in-memory etag"
        match_condition = "current_etag == received etag"
        on_match = (
            "do not refetch /models; renew persistent cache TTL using the current "
            "client version when a cache is present, then return"
        )
        on_mismatch = (
            "refresh_available_models with RefreshStrategy::Online when etag mismatches"
        )
        returns_to_manager = "(Vec<ModelInfo>, Option<String>)"
        cache_entry = "ModelsCacheEntry { fetched_at, etag, client_version, models }"
        in_memory_catalog = (
            "apply_remote_models(models.clone()) before persisting the cache entry"
        )
    else:
        state = "unknown models-catalog state representation"
        match_condition = "unknown"
        on_match = "unknown"
        on_mismatch = "unknown"
        returns_to_manager = "unknown"
        cache_entry = "ModelsCacheEntry variant unknown"
        in_memory_catalog = "unknown"

    return {
        "implementation_variant": variant,
        "signal": {
            "meaning": "opaque catalog-generation/invalidation signal; it is not a model identifier and does not carry the catalog body",
            "normalized_event": "ResponseEvent::ModelsEtag(String)",
            "http_sse": {"location": "outer HTTP response header", "header": "X-Models-Etag"},
            "websocket": {
                "location": "codex.response.metadata top-level headers",
                "header": "x-models-etag",
            },
            "catalog_body_embedded": False,
        },
        "dispatch": "core turn handling forwards ModelsEtag(etag) to models_manager.refresh_if_new_etag(etag, http_client_factory)",
        "comparison": {
            "state": state,
            "match_condition": match_condition,
            "on_match": on_match,
            "on_mismatch_or_identity_change": on_mismatch,
        },
        "catalog_fetch": {
            "separate_request": True,
            "method": "GET",
            "path": "/models",
            "query": "client_version=<current Codex client version>",
            "provider_bridge": "OpenAiModelsEndpoint builds ModelsClient request_url and calls ModelsClient.list_models",
            "response_body": "ModelsResponse JSON; Codex extracts models[]",
            "response_version_header": "ETag",
            "returns_to_manager": returns_to_manager,
        },
        "catalog_update": {
            "cache_entry": cache_entry,
            "persistent_cache": "store entry when cache is configured",
            "in_memory_catalog": in_memory_catalog,
        },
        "wire_version_relation": {
            "responses_signal": "X-Models-Etag / x-models-etag",
            "models_response_version": "ETag",
            "relationship": "the Responses signal is compared against the cached etag that originated from the /models response",
        },
    }
