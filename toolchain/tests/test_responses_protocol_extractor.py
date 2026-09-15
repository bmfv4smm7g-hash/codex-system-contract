from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.extractors.responses_protocol import ResponseEventsExtractor
from codex_wire_audit.extractors.responses_protocol import ResponsesLiteExtractor
from codex_wire_audit.extractors.responses_protocol import ResponsesRequestExtractor
from codex_wire_audit.legacy import load_legacy_modules
from codex_wire_audit.models import SourceFile, SourceGroup, SourceRevision, SourceSnapshot, SourceSpec
from codex_wire_audit.orchestrator import build_registry


def _file(spec_id: str, key: str, path: str, text: str) -> SourceFile:
    spec = SourceSpec(
        id=spec_id,
        legacy_key=key,
        group=SourceGroup.BASE,
        path_candidates=(path,),
        required=True,
        roles=("legacy_base",),
        expected_symbols=(),
        extractor_ids=(),
    )
    return SourceFile.create(spec=spec, selected_path=path, raw_bytes=text.encode())


def _snapshot(*, omit: str | None = None, break_events: bool = False) -> SourceSnapshot:
    common = '''
pub enum ResponseEvent {
    Created { response_id: Option<String> },
    OutputItemDone(ResponseItem),
    OutputTextDelta(String),
    ToolCallInputDelta { item_id: String },
    ReasoningSummaryDelta { delta: String },
    ReasoningSummaryDone { item_id: String },
    ReasoningContentDelta { delta: String },
    Completed { response_id: String },
    RateLimits(RateLimitSnapshot),
}
pub struct ResponsesApiRequest {
    pub model: String,
    pub instructions: String,
    pub input: Vec<ResponseItem>,
    pub tools: Option<ResponsesApiTools>,
    pub tool_choice: String,
    pub parallel_tool_calls: bool,
    pub reasoning: Option<Reasoning>,
    pub store: bool,
    pub stream: bool,
    pub stream_options: Option<StreamOptions>,
    pub include: Vec<String>,
    pub service_tier: Option<String>,
    pub prompt_cache_key: Option<String>,
    pub text: Option<TextControls>,
    pub client_metadata: Option<HashMap<String, String>>,
    pub access_programs: Option<AccessPrograms>,
}
pub struct ResponseCreateWsRequest<'a> {
    pub model: &'a str,
    pub instructions: &'a str,
    pub previous_response_id: Option<String>,
    pub input: &'a [ResponseItem],
    pub tools: Option<&'a RawValue>,
    pub tool_choice: &'a str,
    pub parallel_tool_calls: bool,
    pub reasoning: Option<&'a Reasoning>,
    pub store: bool,
    pub stream: bool,
    pub stream_options: Option<&'a StreamOptions>,
    pub include: &'a [String],
    pub service_tier: Option<&'a str>,
    pub prompt_cache_key: Option<&'a str>,
    pub text: Option<&'a TextControls>,
    pub generate: Option<bool>,
    pub client_metadata: Option<HashMap<String, String>>,
    pub access_programs: Option<AccessPrograms>,
}
pub enum ResponsesWsRequest<'a> {
    #[serde(rename = "response.create")]
    ResponseCreate(ResponseCreateWsRequest<'a>),
}
'''
    core = '''
fn responses_request_properties_match() { previous_response_id; }
fn build_ws_client_metadata() {}
fn build_responses_request() {
    model_info.use_responses_lite;
    prompt.get_formatted_input_for_request(model_info.use_responses_lite);
    create_tools_json_for_responses_lite;
    ResponseItem::AdditionalTools;
    ContextualUserFragment::into(BaseInstructionsFragment("x".into()));
    input.splice(0..0, prefix);
    (String::new(), None);
    parallel_tool_calls: prompt.parallel_tool_calls && !model_info.use_responses_lite;
    ReasoningContext::AllTurns;
    X_OPENAI_INTERNAL_CODEX_RESPONSES_LITE_HEADER;
    WS_REQUEST_HEADER_RESPONSES_LITE_CLIENT_METADATA_KEY;
}
'''
    core += """
fn get_incremental_items() {}
fn responses_websocket_enabled() { disable_websockets; }
fn try_switch_fallback_transport() {}
fn websocket_lifecycle() {
    generate: if warmup { Some(false) } else { None };
    Ok(ResponseEvent::Completed { .. }) => break;
    StatusCode::UPGRADE_REQUIRED;
    WebsocketStreamOutcome::FallbackToHttp;
}
"""
    http = '''
pub enum ResponsesEndpoint { Responses, Guardian, GuardianClassifier }
impl ResponsesEndpoint {
    fn path(self) -> &'static str {
        match self {
            Self::Responses => "/responses",
            Self::Guardian => "/guardian",
            Self::GuardianClassifier => "/guardian-classifier",
        }
    }
}
pub async fn stream_request() { Method::POST; "text/event-stream"; build_session_headers; "x-openai-subagent"; }
'''
    sse = '''
const X_REASONING_INCLUDED_HEADER: &str = "x-reasoning-included";
const X_CODEX_TURN_STATE_HEADER: &str = "x-codex-turn-state";
const OPENAI_MODEL_HEADER: &str = "openai-model";
const REQUEST_ID_HEADER: &str = "x-request-id";
pub struct ResponsesStreamEvent { kind: String }
pub fn process_responses_event() {
    match event.kind.as_str() {
        "response.output_item.done" => {}
        "response.output_text.delta" => {}
        "response.custom_tool_call_input.delta" => {}
        "response.reasoning_summary_text.delta" => {}
        "response.reasoning_summary_text.done" => {}
        "response.reasoning_text.delta" => {}
        "response.created" => {}
        "response.failed" => {}
        "response.incomplete" => {}
        "response.completed" => {}
        "response.metadata" => {}
        _ => {}
    }
    X_CODEX_TURN_STATE_HEADER;
    REQUEST_ID_HEADER;
}
'''
    if break_events:
        sse = sse.replace('"response.completed" => {}', '')
    ws = '''
pub struct ResponsesWebsocketConnection;
pub async fn stream_request() { serialize_websocket_request; process_responses_event; parse_rate_limit_event; }
fn connect() { websocket_url_for_path(self.endpoint.path()); }
fn run_websocket_response_stream() { previous_response_not_found; websocket_connection_limit_reached; ResponsesStreamEvent; let failed_stream = guard.take(); }
impl Drop for WsStream { fn drop(&mut self) { self.pump_task.abort(); } }
'''
    startup = """
fn schedule_startup_prewarm() {}
CodexResponsesRequestKind::Prewarm;
client.prewarm_websocket();
let startup_prompt = build_prompt(
        Vec::new(),
        step_context,
        base_instructions,
);
"""
    session = """
sess.schedule_startup_prewarm(base).await;
record_initial_history(initial_history);
"""
    retry = """
fn handle_retryable_response_stream_error() {
    Feature::UnboundedConnectionRetries;
    client_session.try_switch_fallback_transport();
    "Falling back from WebSockets to HTTPS transport.";
}
"""
    provider = """
fn websocket_url_for_path() { match scheme { "http" => "ws", "https" => "wss", "ws" | "wss" => return; } }
"""
    rows = {
        "common": _file("source_spec.base.common", "common", "codex-rs/codex-api/src/common.rs", common),
        "core": _file("source_spec.base.core", "core", "codex-rs/core/src/client.rs", core),
        "http": _file("source_spec.base.http", "http", "codex-rs/codex-api/src/endpoint/responses.rs", http),
        "sse": _file("source_spec.base.response_sse", "response_sse", "codex-rs/codex-api/src/sse/responses.rs", sse),
        "ws": _file("source_spec.base.ws", "ws", "codex-rs/codex-api/src/endpoint/responses_websocket.rs", ws),
        "startup": _file("source_spec.extra.responses_transport_startup", "responses_transport_startup", "codex-rs/core/src/session_startup_prewarm.rs", startup),
        "session": _file("source_spec.extra.responses_transport_session", "responses_transport_session", "codex-rs/core/src/session/session.rs", session),
        "retry": _file("source_spec.extra.responses_transport_retry", "responses_transport_retry", "codex-rs/core/src/responses_retry.rs", retry),
        "provider": _file("source_spec.extra.responses_transport_provider", "responses_transport_provider", "codex-rs/codex-api/src/provider.rs", provider),
    }
    if omit:
        rows.pop(omit)
    files = {value.spec_id: value for value in rows.values()}
    revision = SourceRevision("fixture", "openai/codex", "fixture", "1" * 40, SourceSnapshot.digest_files(files), False)
    return SourceSnapshot(revision, files)


def test_default_registry_assigns_responses_sources_to_native_domain():
    registry = build_registry(load_legacy_modules())
    by_extractor = {
        extractor_id: {spec.id for spec in registry.specs if extractor_id in spec.extractor_ids}
        for extractor_id in (
            "extractor.responses_request",
            "extractor.responses_lite",
            "extractor.response_events",
        )
    }
    assert by_extractor["extractor.responses_request"] == {
        "source_spec.base.common", "source_spec.base.core", "source_spec.base.http", "source_spec.base.ws",
        "source_spec.extra.responses_transport_startup", "source_spec.extra.responses_transport_session",
        "source_spec.extra.responses_transport_retry", "source_spec.extra.responses_transport_provider",
    }
    assert by_extractor["extractor.responses_lite"] == {"source_spec.base.core"}
    assert by_extractor["extractor.response_events"] == {
        "source_spec.base.common", "source_spec.base.response_sse", "source_spec.base.ws"
    }


def test_request_extractor_parses_exact_wire_field_inventory():
    diagnostics = DiagnosticCollector()
    result = ResponsesRequestExtractor().extract(_snapshot(), diagnostics)
    assert result.semantic_complete
    assert diagnostics.summary()["error"] == 0
    assert result.data["request_shape"]["endpoint_paths"]["Responses"] == "/responses"
    assert result.data["request_shape"]["http_fields"][0:3] == ["model", "instructions", "input"]
    assert "previous_response_id" in result.data["request_shape"]["websocket_fields"]
    assert result.data["request_shape"]["websocket_envelope_type"] == "response.create"
    assert result.schema_version == "2.0.0"
    lifecycle = result.data["transport_lifecycle"]
    assert lifecycle["startup_prewarm"]["generate"] is False
    assert lifecycle["startup_prewarm"]["occurs_before_initial_history_restore"] is True
    assert lifecycle["state_scope"]["fallback_sticky_across_turns"] is True
    assert lifecycle["fallback"]["warning_prefix"] == "Falling back from WebSockets to HTTPS transport."
    assert lifecycle["selection"]["scheme_pairing"]["https_base"] == {"websocket": "wss", "fallback_http": "https"}


def test_lite_extractor_owns_transformation_not_prompt_composition():
    diagnostics = DiagnosticCollector()
    result = ResponsesLiteExtractor().extract(_snapshot(), diagnostics)
    assert result.semantic_complete
    assert result.data["transformation"]["top_level_instructions"] == "empty string"
    assert result.data["transformation"]["top_level_tools"] is None
    assert result.data["transformation"]["parallel_tool_calls"] is False
    assert "base instruction composition before transformation" in result.data["ownership"]["does_not_own"]


def test_event_extractor_parses_dispatch_inventory_and_transport_convergence():
    diagnostics = DiagnosticCollector()
    result = ResponseEventsExtractor().extract(_snapshot(), diagnostics)
    assert result.semantic_complete
    assert "Completed" in result.data["normalized_event_variants"]
    assert "response.completed" in result.data["wire_event_kinds"]
    assert result.data["stream_headers"]["turn_state"] == "x-codex-turn-state"
    assert result.data["dispatch"]["terminal_errors"] == ["response.failed", "response.incomplete"]


def test_missing_request_source_fails_closed():
    diagnostics = DiagnosticCollector()
    result = ResponsesRequestExtractor().extract(_snapshot(omit="http"), diagnostics)
    assert not result.semantic_complete
    assert result.data == {}
    assert any(item.code == "RESPONSES_REQUEST_SOURCE_UNAVAILABLE" for item in diagnostics.values())


def test_event_dispatch_drift_is_error_not_fallback():
    diagnostics = DiagnosticCollector()
    result = ResponseEventsExtractor().extract(_snapshot(break_events=True), diagnostics)
    assert not result.semantic_complete
    assert any(item.code in {"RESPONSES_EVENT_COMPLETED_MISSING", "RESPONSE_EVENT_DISPATCH_INVENTORY_INCOMPLETE"} for item in diagnostics.values())


def test_responses_source_identity_is_exact():
    registry = build_registry(load_legacy_modules())
    assert registry.get("source_spec.base.common").primary_path == "codex-rs/codex-api/src/common.rs"
    assert registry.get("source_spec.base.http").primary_path == "codex-rs/codex-api/src/endpoint/responses.rs"
    assert registry.get("source_spec.base.response_sse").primary_path == "codex-rs/codex-api/src/sse/responses.rs"
    assert registry.get("source_spec.base.ws").primary_path == "codex-rs/codex-api/src/endpoint/responses_websocket.rs"


def test_request_v2_schema_validates_transport_lifecycle() -> None:
    result = ResponsesRequestExtractor().extract(_snapshot(), DiagnosticCollector())
    schema_path = Path(__file__).parents[1] / "codex_wire_audit" / "proof_schema_templates" / "responses-request-semantics-v2.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(result.data))
    assert errors == []


def test_websocket_fallback_marker_drift_fails_closed() -> None:
    snapshot = _snapshot()
    core = snapshot.files["source_spec.base.core"]
    broken = core.text.replace("StatusCode::UPGRADE_REQUIRED", "StatusCode::BAD_GATEWAY")
    files = dict(snapshot.files)
    files[core.spec_id] = _file(core.spec_id, "core", core.selected_path, broken)
    drifted = SourceSnapshot(snapshot.revision, files)
    diagnostics = DiagnosticCollector()
    result = ResponsesRequestExtractor().extract(drifted, diagnostics)
    assert result.semantic_complete is False
    assert "RESPONSES_WS_426_FALLBACK_MISSING" in {item.code for item in diagnostics.values()}


def test_transport_source_identity_is_exact() -> None:
    registry = build_registry(load_legacy_modules())
    assert registry.get("source_spec.extra.responses_transport_startup").primary_path == "codex-rs/core/src/session_startup_prewarm.rs"
    assert registry.get("source_spec.extra.responses_transport_session").primary_path == "codex-rs/core/src/session/session.rs"
    assert registry.get("source_spec.extra.responses_transport_retry").primary_path == "codex-rs/core/src/responses_retry.rs"
    assert registry.get("source_spec.extra.responses_transport_provider").primary_path == "codex-rs/codex-api/src/provider.rs"
