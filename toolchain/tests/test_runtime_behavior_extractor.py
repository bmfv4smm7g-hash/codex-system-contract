from __future__ import annotations

from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.extractors.runtime_behavior import RuntimeBehaviorExtractor
from codex_wire_audit.models import SourceFile, SourceGroup, SourceRevision, SourceSnapshot, SourceSpec


def _file(spec_id: str, path: str, text: str) -> SourceFile:
    spec = SourceSpec(
        id=spec_id,
        legacy_key=spec_id.rsplit(".", 1)[-1],
        group=SourceGroup.EXTRA,
        path_candidates=(path,),
        required=False,
    )
    return SourceFile.create(spec=spec, selected_path=path, raw_bytes=text.encode())


def _snapshot() -> SourceSnapshot:
    rows = [
        _file(
            "source_spec.base.response_sse",
            "codex-rs/codex-api/src/sse/responses.rs",
            '''
fn process_responses_event() {
    if is_context_window_error(&error) { ApiError::ContextWindowExceeded; }
    if is_quota_exceeded_error(&error) { ApiError::QuotaExceeded; }
    if is_usage_not_included(&error) { ApiError::UsageNotIncluded; }
    if is_cyber_policy_error(&error) { ApiError::CyberPolicy; }
    "misalignment_policy_violation"; ApiError::MisalignmentPolicyViolation;
    "invalid_prompt"; "bio_policy"; ApiError::InvalidRequest;
    is_server_overloaded_error(&error); ApiError::ServerOverloaded;
    "rate_limit_exceeded"; "slow_down"; ApiError::RateLimitExceeded;
    let delay = try_parse_retry_after(&error);
    ApiError::Retryable { message, delay };
    "response.incomplete"; ApiError::Stream(message);
}
''',
        ),
        _file(
            "source_spec.base.ws",
            "codex-rs/codex-api/src/endpoint/responses_websocket.rs",
            '''
const PREVIOUS_RESPONSE_NOT_FOUND_CODE: &str = "previous_response_not_found";
const WEBSOCKET_CONNECTION_LIMIT_REACHED_CODE: &str = "websocket_connection_limit_reached";
fn map_wrapped() {
    ApiError::Retryable;
    StatusCode::from_u16(503);
    ApiError::Transport(TransportError::Http { });
    WsError::ConnectionClosed | WsError::AlreadyClosed;
    ApiError::Stream("websocket closed".to_string());
    ApiError::Transport(TransportError::Network("x".into()));
    ApiError::Stream("idle timeout waiting for websocket".into());
}
''',
        ),
        _file(
            "source_spec.extra.responses_transport_retry",
            "codex-rs/core/src/responses_retry.rs",
            '''
Feature::UnboundedConnectionRetries;
CodexErrorDetails::ConnectionFailed;
try_switch_fallback_transport();
"Falling back from WebSockets to HTTPS transport";
let delay = err.retry_delay().unwrap_or_else(|| backoff(retry_count));
let report_error = retry_count > 1 || cfg!(debug_assertions) || !responses_websocket_enabled();
''',
        ),
        _file(
            "source_spec.extra.prompt_turn",
            "codex-rs/core/src/session/turn.rs",
            '''
if !err.is_retryable() { return Err(err); }
handle_retryable_response_stream_error();
''',
        ),
        _file(
            "source_spec.extra.app_server_thread",
            "codex-rs/app-server-protocol/src/protocol/v2/thread.rs",
            '''
pub struct ThreadForkParams {
    pub thread_id: String,
    pub ephemeral: bool,
    pub exclude_turns: bool,
}
''',
        ),
        _file(
            "source_spec.extra.app_server_thread_processor",
            "codex-rs/app-server/src/request_processors/thread_processor.rs",
            '''
typesafe_overrides.ephemeral = ephemeral.then_some(true);
if ephemeral && defer_goal_continuation { return Err(()); }
"ephemeral paginated thread/fork requires `excludeTurns: true`";
let reserved_thread_id = if config.ephemeral { None } else {
    stage_pending_thread_metadata();
};
''',
        ),
        _file(
            "source_spec.extra.app_server_thread_manager",
            "codex-rs/core/src/thread_manager.rs",
            '''
/// The new thread will have a fresh id.
pub async fn fork_prepared_thread() {}
request.forked_from_thread_id = source_thread_id;
''',
        ),
        _file(
            "source_spec.extra.app_server_tui_session",
            "codex-rs/tui/src/app_server_session.rs",
            '''
enum ForkPresentation { Regular, SideConversation }
pub(crate) async fn fork_side_thread() { ForkPresentation::SideConversation; }
let exclude_turns = presentation == ForkPresentation::SideConversation;
''',
        ),
        _file(
            "source_spec.extra.local_storage_tui_backtrack",
            "codex-rs/tui/src/app_backtrack.rs",
            "AppEvent::ForkSessionForPromptEdit { thread_id, prompt };",
        ),
    ]
    files = {row.spec_id: row for row in rows}
    revision = SourceRevision(
        "fixture",
        "openai/codex",
        "fixture",
        "1" * 40,
        SourceSnapshot.digest_files(files),
        False,
    )
    return SourceSnapshot(revision, files)


def test_runtime_behavior_derives_error_map_and_retry_control() -> None:
    result = RuntimeBehaviorExtractor().extract(_snapshot(), DiagnosticCollector())
    errors = result.data["responses"]

    assert errors["response_failed"]["server_overloaded"]["observed"]
    assert errors["response_failed"]["server_overloaded"]["api_error"] == "ServerOverloaded"
    assert errors["response_failed"]["rate_limit_codes"]["error_codes"] == [
        "rate_limit_exceeded",
        "slow_down",
    ]
    assert errors["websocket_wrapped_error"]["previous_response_not_found"]["observed"]
    assert errors["turn_retry_control"]["retryability_gate"]["observed"]
    assert errors["turn_retry_control"]["websocket_to_http_fallback"]["observed"]


def test_runtime_behavior_separates_fork_lineage_persistence_and_presentation() -> None:
    result = RuntimeBehaviorExtractor().extract(_snapshot(), DiagnosticCollector())
    fork = result.data["fork"]

    assert "ephemeral" in fork["request_fields"]
    assert fork["axes"]["history_lineage"]["fresh_thread_identity"]["observed"]
    assert fork["axes"]["persistence"]["ephemeral_request_flag"]["observed"]
    assert fork["axes"]["persistence"]["ephemeral_skips_durable_thread_metadata_reservation"]["observed"]
    assert fork["axes"]["tui_presentation"]["presentation_enum"]["observed"]
    assert fork["axes"]["tui_presentation"]["persistence_is_not_the_presentation_enum"]["observed"]
    assert fork["axes"]["rewind_prompt_edit"]["uses_fork"]["observed"]
