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
async fn run_websocket_response_stream() {
    match message {
        Message::Close(_) => {
            return Err(ApiError::Stream(
                "websocket closed by server before response.completed".into(),
            ));
        }
        _ => {}
    }
}
''',
        ),
        _file(
            "source_spec.base.core",
            "codex-rs/core/src/client.rs",
            '''
fn new_session() {
    turn_state: Arc::new(OnceLock::new());
}
fn websocket_connection() {
    let needs_new = match self.websocket_session.connection.as_ref() {
        Some(conn) if conn.is_closed().await => true,
        _ => false,
    };
    if owner_changed {
        self.turn_state = Arc::new(OnceLock::new());
    }
}
fn stream_responses_websocket() {
    client_metadata.insert(X_CODEX_TURN_STATE_HEADER.to_string(), turn_state.clone());
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
let retry_count = retry_state.retries.saturating_add(1);
let Some(delay) = err.retry_delay(retry_count) else {
    return Err(err);
};
let report_error = retry_count > 1 || cfg!(debug_assertions) || !responses_websocket_enabled();
''',
        ),
        _file(
            "source_spec.extra.prompt_turn",
            "codex-rs/core/src/session/turn.rs",
            '''
if !err.is_retryable() { return Err(err); }
handle_response_stream_error();
''',
        ),
        _file(
            "source_spec.extra.response_api_bridge",
            "codex-rs/codex-api/src/api_bridge.rs",
            '''
ApiError::Retryable => CodexErrorDetails::Stream(message).into();
ApiError::RateLimitExceeded => CodexErrorDetails::RateLimitExceeded(message).into();
ApiError::ServerOverloaded => CodexErrorDetails::ServerOverloaded.into();
StatusCode::SERVICE_UNAVAILABLE;
"server_is_overloaded"; CodexErrorDetails::ServerOverloaded;
"slow_down"; CodexErrorDetails::RateLimitExceeded(message);
StatusCode::INTERNAL_SERVER_ERROR; CodexErrorDetails::InternalServerError;
StatusCode::TOO_MANY_REQUESTS; CodexErrorDetails::RetryLimit(error);
''',
        ),
        _file(
            "source_spec.extra.response_protocol_error",
            "codex-rs/protocol/src/error.rs",
            '''
pub enum CodexErrorDetails {
    Stream(String),
    RateLimitExceeded(String),
    ServerOverloaded,
    InvalidRequest(String),
    ConnectionFailed(String),
}
impl CodexErr {
    pub fn retry_delay(&self, retry_count: u64) -> Option<Duration> {
        match self.details() {
            CodexErrorDetails::ServerOverloaded
            | CodexErrorDetails::InvalidRequest(_) => None,
            CodexErrorDetails::Stream(..)
            | CodexErrorDetails::RateLimitExceeded(_)
            | CodexErrorDetails::ConnectionFailed(_) => Some(
                self.server_retry_delay.unwrap_or_else(|| backoff(retry_count)),
            ),
        }
    }
}
''',
        ),
        _file(
            "source_spec.extra.app_server_error_notification",
            "codex-rs/app-server-protocol/src/protocol/v2/notification.rs",
            '''
pub struct ErrorNotification {
    // Set to true if the error is transient and the app-server process will automatically retry.
    pub will_retry: bool,
}
''',
        ),
        _file(
            "source_spec.extra.app_server_bespoke_events",
            "codex-rs/app-server/src/bespoke_event_handling.rs",
            '''
match msg {
    EventMsg::StreamError(ev) => ErrorNotification { will_retry: true },
    EventMsg::Error(ev) => handle_error_notification(ev),
}
fn handle_error_notification(error: TurnError) {
    ErrorNotification { error, will_retry: false };
}
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
        _file(
            "source_spec.extra.tui_side",
            "codex-rs/tui/src/app/side.rs",
            '''
fork_config.ephemeral = true;
app_server.fork_side_thread(&self.local_settings, fork_config, parent_thread_id).await;
''',
        ),
        _file(
            "source_spec.extra.tui_slash_command",
            "codex-rs/tui/src/slash_command.rs",
            '''
SlashCommand::Side | SlashCommand::Btw => {
    "start a side conversation in an ephemeral fork"
}
''',
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

    assert result.semantic_complete
    assert errors["response_failed"]["server_overloaded"]["observed"]
    assert errors["response_failed"]["server_overloaded"]["api_error"] == "ServerOverloaded"
    assert errors["response_failed"]["rate_limit_codes"]["error_codes"] == [
        "rate_limit_exceeded",
        "slow_down",
    ]
    assert errors["websocket_wrapped_error"]["previous_response_not_found"]["observed"]
    assert errors["api_to_codex_error"]["server_overloaded_api_error"]["observed"]
    assert errors["codex_error_retryability"]["implementation"] == "retry_delay"
    assert errors["codex_error_retryability"]["table"]["ServerOverloaded"] is False
    assert errors["codex_error_retryability"]["table"]["RateLimitExceeded"] is True
    assert errors["turn_retry_control"]["retryability_gate"]["observed"]
    assert errors["turn_retry_control"]["websocket_to_http_fallback"]["observed"]
    reconnect = errors["websocket_reconnect_state"]
    assert reconnect["close_frame"]["service_restart_1012_special_cased"] is False
    assert reconnect["close_frame"]["close_code_inspected"] is False
    assert reconnect["turn_state"]["preserved_across_plain_connection_close"] is True
    assert reconnect["turn_state"]["reset_on_auth_owner_change"] is True
    retry_surface = result.data["client_retry_surface"]
    assert retry_surface["will_retry_true_means_app_server_automatic_retry"] is True
    assert retry_surface["server_overloaded_core_retryable"] is False
    assert retry_surface["server_overloaded_app_server_will_retry"] is False


def test_runtime_behavior_separates_fork_lineage_persistence_and_presentation() -> None:
    result = RuntimeBehaviorExtractor().extract(_snapshot(), DiagnosticCollector())
    fork = result.data["fork"]

    assert "ephemeral" in fork["request_fields"]
    assert fork["axes"]["history_lineage"]["fresh_thread_identity"]["observed"]
    assert fork["axes"]["persistence"]["ephemeral_request_flag"]["observed"]
    assert fork["axes"]["persistence"]["durability_branch"]["observed"]
    assert fork["axes"]["tui_presentation"]["presentation_enum"]["observed"]
    assert fork["axes"]["tui_presentation"]["persistence_is_not_presentation"]["observed"]
    assert fork["axes"]["product_surface"]["side_conversation_forces_ephemeral"]["observed"]
    assert fork["axes"]["product_surface"]["slash_aliases"]["commands"] == ["/side", "/btw"]
    assert fork["axes"]["rewind_prompt_edit"]["uses_fork"]["observed"]



def test_retryability_legacy_is_retryable_shape_remains_supported() -> None:
    snapshot = _snapshot()
    source = snapshot.files["source_spec.extra.response_protocol_error"]
    current = source.text
    legacy = current.replace(
        """pub fn retry_delay(&self, retry_count: u64) -> Option<Duration> {
        match self.details() {
            CodexErrorDetails::ServerOverloaded
            | CodexErrorDetails::InvalidRequest(_) => None,
            CodexErrorDetails::Stream(..)
            | CodexErrorDetails::RateLimitExceeded(_)
            | CodexErrorDetails::ConnectionFailed(_) => Some(
                self.server_retry_delay.unwrap_or_else(|| backoff(retry_count)),
            ),
        }
    }""",
        """pub fn is_retryable(&self) -> bool {
        match self.details() {
            CodexErrorDetails::ServerOverloaded
            | CodexErrorDetails::InvalidRequest(_) => false,
            CodexErrorDetails::Stream(..)
            | CodexErrorDetails::RateLimitExceeded(_)
            | CodexErrorDetails::ConnectionFailed(_) => true,
        }
    }""",
    )
    files = dict(snapshot.files)
    files[source.spec_id] = _file(source.spec_id, source.selected_path, legacy)
    result = RuntimeBehaviorExtractor().extract(
        SourceSnapshot(snapshot.revision, files),
        DiagnosticCollector(),
    )
    retryability = result.data["responses"]["codex_error_retryability"]
    assert retryability["implementation"] == "is_retryable"
    assert retryability["table"]["ServerOverloaded"] is False
    assert retryability["table"]["RateLimitExceeded"] is True
