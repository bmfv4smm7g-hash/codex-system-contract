from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXTRACTOR = ROOT / "toolchain/codex_wire_audit/extractors/responses_server_response.py"
SCHEMA = (
    ROOT
    / "toolchain/codex_wire_audit/proof_schema_templates/"
    "responses-server-response-semantics-v1.schema.json"
)
TESTS = ROOT / "toolchain/tests/test_responses_server_response_extractor.py"


def replace_section(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[:start] + replacement.rstrip() + "\n\n" + text[end + 1 :]


def patch_extractor() -> None:
    text = EXTRACTOR.read_text(encoding="utf-8")
    text = text.replace('SCHEMA_VERSION = "1.1.0"', 'SCHEMA_VERSION = "1.2.0"', 1)

    source_specs_tail = ")\n\n\ndef _canonical"
    variant_constants = (
        ')\n\n\nCATALOG_VARIANT_IDENTITY_AWARE = "identity_aware"\n'
        'CATALOG_VARIANT_ETAG_ONLY = "etag_only"\n'
        'CATALOG_VARIANT_UNKNOWN = "unknown"\n\n\n'
        "def _canonical"
    )
    if "CATALOG_VARIANT_IDENTITY_AWARE" not in text:
        if source_specs_tail not in text:
            raise SystemExit("source-spec insertion marker did not match")
        text = text.replace(source_specs_tail, variant_constants, 1)

    helper = r'''
def _catalog_variant(manager: SourceFile, provider_models: SourceFile) -> str:
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
'''
    if "def _catalog_variant(" not in text:
        marker = "\ndef _brace_body"
        if marker not in text:
            raise SystemExit("catalog-variant helper insertion marker did not match")
        text = text.replace(marker, "\n" + helper.rstrip() + "\n\n\ndef _brace_body", 1)

    validation = r'''
def _validate_catalog_sources(
    turn: SourceFile,
    manager: SourceFile,
    endpoint: SourceFile,
    provider_models: SourceFile,
    diagnostics: DiagnosticCollector,
) -> tuple[bool, str]:
    variant = _catalog_variant(manager, provider_models)
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
            (
                (
                    "RESPONSES_MODELS_PROVIDER_RESULT_MISSING",
                    "Ok(ModelsEndpointResponse {",
                ),
            ),
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
'''
    text = replace_section(
        text,
        "def _validate_catalog_sources(",
        "\ndef _check_response_model_authority",
        validation,
    )

    catalog_contract = r'''
def _models_catalog_contract(variant: str) -> dict[str, Any]:
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
'''
    text = replace_section(
        text,
        "def _models_catalog_contract(",
        "\ndef _server_channels_contract",
        catalog_contract,
    )

    old_signature = (
        "def _build_body(sources: dict[str, SourceFile], "
        "payload_model_consulted: bool) -> dict[str, Any]:"
    )
    new_signature = """def _build_body(
    sources: dict[str, SourceFile],
    payload_model_consulted: bool,
    catalog_variant: str,
) -> dict[str, Any]:"""
    if old_signature not in text:
        raise SystemExit("build-body signature marker did not match")
    text = text.replace(old_signature, new_signature, 1)
    text = text.replace(
        '"models_catalog_invalidation": _models_catalog_contract(),',
        '"models_catalog_invalidation": _models_catalog_contract(catalog_variant),',
        1,
    )

    old_call = """        complete &= _validate_catalog_sources(
            sources[TURN],
            sources[MODELS_MANAGER],
            sources[MODELS_ENDPOINT],
            sources[MODEL_PROVIDER_MODELS],
            diagnostics,
        )"""
    new_call = """        catalog_complete, catalog_variant = _validate_catalog_sources(
            sources[TURN],
            sources[MODELS_MANAGER],
            sources[MODELS_ENDPOINT],
            sources[MODEL_PROVIDER_MODELS],
            diagnostics,
        )
        complete &= catalog_complete"""
    if old_call not in text:
        raise SystemExit("catalog validation call marker did not match")
    text = text.replace(old_call, new_call, 1)

    old_return = "        return _result(_build_body(sources, payload_model_consulted), complete)"
    new_return = """        return _result(
            _build_body(sources, payload_model_consulted, catalog_variant),
            complete,
        )"""
    if old_return not in text:
        raise SystemExit("extractor return marker did not match")
    text = text.replace(old_return, new_return, 1)

    EXTRACTOR.write_text(text, encoding="utf-8")


def patch_schema() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    schema["properties"]["schema_version"]["const"] = "1.2.0"
    catalog = schema["properties"]["models_catalog_invalidation"]
    required = catalog["required"]
    if "implementation_variant" not in required:
        required.insert(0, "implementation_variant")
    catalog["properties"]["implementation_variant"] = {
        "enum": ["identity_aware", "etag_only", "unknown"]
    }
    catalog["properties"]["catalog_fetch"]["properties"]["returns_to_manager"] = {
        "enum": [
            "ModelsEndpointResponse { models, etag, identity }",
            "(Vec<ModelInfo>, Option<String>)",
            "unknown",
        ]
    }
    SCHEMA.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")


def patch_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")

    legacy_helper = r'''
def _etag_only_snapshot() -> SourceSnapshot:
    snapshot = _snapshot()
    rows = dict(snapshot.files)
    manager = """
async fn refresh_if_new_etag(&self, etag: String, http_client_factory: HttpClientFactory) {
    let current_etag = self.get_etag().await;
    if current_etag.as_deref() == Some(etag.as_str()) {
        cache.refresh_ttl(&crate::client_version_to_whole()).await;
        return;
    }
    self
        .refresh_available_models(RefreshStrategy::Online, &http_client_factory)
        .await;
}
async fn refresh_available_models(
    &self,
    refresh_strategy: RefreshStrategy,
    http_client_factory: &HttpClientFactory,
) {
    match refresh_strategy {
        RefreshStrategy::Online => {
            self.fetch_and_update_models(http_client_factory).await
        }
        _ => Ok(()),
    }
}
async fn fetch_and_update_models(&self, http_client_factory: &HttpClientFactory) {
    let client_version = crate::client_version_to_whole();
    let (models, etag) = self
        .endpoint_client
        .list_models(&client_version, http_client_factory.clone())
        .await?;
    self.apply_remote_models(models.clone()).await;
    let entry = ModelsCacheEntry {
        fetched_at: Utc::now(),
        etag,
        client_version: Some(client_version),
        models,
    };
    cache.store(&entry).await;
}
"""
    provider_models = """
const MODELS_ENDPOINT: &str = "/models";
async fn list_models(
    &self,
    client_version: &str,
) -> CoreResult<(Vec<ModelInfo>, Option<String>)> {
    let request_url =
        ModelsClient::<ReqwestTransport>::request_url(&api_provider, client_version);
    client
        .list_models(request_url, HeaderMap::new())
        .await
        .map_err(map_api_error)
}
"""
    rows["source_spec.extra.models_manager"] = _file(
        "source_spec.extra.models_manager",
        "models_manager",
        "codex-rs/models-manager/src/manager.rs",
        manager,
    )
    rows["source_spec.surface.model_provider_models"] = _file(
        "source_spec.surface.model_provider_models",
        "model_provider_models",
        "codex-rs/model-provider/src/models_endpoint.rs",
        provider_models,
        SourceGroup.SURFACE,
    )
    revision = SourceRevision(
        "fixture",
        "openai/codex",
        "fixture-etag-only",
        "2" * 40,
        SourceSnapshot.digest_files(rows),
        False,
    )
    return SourceSnapshot(revision, rows)
'''
    if "def _etag_only_snapshot(" not in text:
        marker = "\ndef test_server_response_extractor_is_registered"
        if marker not in text:
            raise SystemExit("legacy snapshot insertion marker did not match")
        text = text.replace(
            marker,
            "\n" + legacy_helper.rstrip() + "\n\n\ndef test_server_response_extractor_is_registered",
            1,
        )

    contract_marker = (
        '    contract = result.data["models_catalog_invalidation"]\n\n'
        '    assert contract["signal"]["http_sse"]["header"] == "X-Models-Etag"'
    )
    if 'assert contract["implementation_variant"] == "identity_aware"' not in text:
        replacement = (
            '    contract = result.data["models_catalog_invalidation"]\n\n'
            '    assert contract["implementation_variant"] == "identity_aware"\n'
            '    assert contract["signal"]["http_sse"]["header"] == "X-Models-Etag"'
        )
        if contract_marker not in text:
            raise SystemExit("identity-aware assertion marker did not match")
        text = text.replace(contract_marker, replacement, 1)

    new_tests = r'''
def test_etag_only_catalog_variant_is_derived_without_identity_claims() -> None:
    diagnostics = DiagnosticCollector()
    result = ResponsesServerResponseExtractor().extract(
        _etag_only_snapshot(),
        diagnostics,
    )

    assert result.semantic_complete
    assert diagnostics.summary()["error"] == 0
    contract = result.data["models_catalog_invalidation"]
    assert contract["implementation_variant"] == "etag_only"
    assert contract["comparison"]["state"] == "current in-memory etag"
    assert "identity" not in contract["comparison"]["match_condition"]
    assert contract["catalog_fetch"]["returns_to_manager"] == (
        "(Vec<ModelInfo>, Option<String>)"
    )
    assert "identity" not in contract["catalog_update"]["cache_entry"]
    assert "models.clone()" in contract["catalog_update"]["in_memory_catalog"]


def test_unknown_catalog_variant_fails_closed() -> None:
    snapshot = _etag_only_snapshot()
    rows = dict(snapshot.files)
    manager = rows["source_spec.extra.models_manager"]
    rows["source_spec.extra.models_manager"] = _file(
        "source_spec.extra.models_manager",
        "models_manager",
        manager.selected_path,
        manager.text.replace(
            ".refresh_ttl(&crate::client_version_to_whole()).await",
            ".touch().await",
        ),
    )
    revision = SourceRevision(
        "fixture",
        "openai/codex",
        "fixture-unknown-catalog",
        "3" * 40,
        SourceSnapshot.digest_files(rows),
        False,
    )
    diagnostics = DiagnosticCollector()
    result = ResponsesServerResponseExtractor().extract(
        SourceSnapshot(revision, rows),
        diagnostics,
    )

    assert result.semantic_complete is False
    assert result.data["models_catalog_invalidation"]["implementation_variant"] == "unknown"
    assert "RESPONSES_MODELS_CATALOG_VARIANT_UNKNOWN" in {
        item.code for item in diagnostics.values()
    }
'''
    if "def test_etag_only_catalog_variant_is_derived_without_identity_claims" not in text:
        marker = "\ndef test_server_response_schema_validates_extractor_output"
        if marker not in text:
            raise SystemExit("catalog variant test insertion marker did not match")
        text = text.replace(
            marker,
            "\n" + new_tests.rstrip() + "\n\n\ndef test_server_response_schema_validates_extractor_output",
            1,
        )

    TESTS.write_text(text, encoding="utf-8")


def main() -> None:
    patch_extractor()
    patch_schema()
    patch_tests()


if __name__ == "__main__":
    main()
