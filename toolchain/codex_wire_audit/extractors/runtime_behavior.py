"""Source-derived runtime behavior for Responses retries and thread forks.

This extractor intentionally owns concrete, revision-sensitive behavior that is
not suitable for architecture prose: error classification paths, retry control,
and fork persistence/presentation modes. It consumes exact source snapshots and
emits observations; absence remains explicit rather than becoming a fallback
fact.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile, SourceSnapshot
from .registry import ExtractorResult, register_extractor


EXTRACTOR_ID = "extractor.runtime_behavior"
SCHEMA_VERSION = "1.1.0"

SSE = "source_spec.base.response_sse"
WS = "source_spec.base.ws"
RESPONSES_RETRY = "source_spec.extra.responses_transport_retry"
PROMPT_TURN = "source_spec.extra.prompt_turn"
API_BRIDGE = "source_spec.extra.response_api_bridge"
PROTOCOL_ERROR = "source_spec.extra.response_protocol_error"
THREAD_PROTOCOL = "source_spec.extra.app_server_thread"
THREAD_PROCESSOR = "source_spec.extra.app_server_thread_processor"
THREAD_MANAGER = "source_spec.extra.app_server_thread_manager"
TUI_SESSION = "source_spec.extra.app_server_tui_session"
TUI_BACKTRACK = "source_spec.extra.local_storage_tui_backtrack"
TUI_SIDE = "source_spec.extra.tui_side"
TUI_SLASH = "source_spec.extra.tui_slash_command"

SOURCE_IDS = (
    SSE,
    WS,
    RESPONSES_RETRY,
    PROMPT_TURN,
    API_BRIDGE,
    PROTOCOL_ERROR,
    THREAD_PROTOCOL,
    THREAD_PROCESSOR,
    THREAD_MANAGER,
    TUI_SESSION,
    TUI_BACKTRACK,
    TUI_SIDE,
    TUI_SLASH,
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _evidence(source: SourceFile, symbol: str) -> dict[str, Any]:
    return {
        "source_spec_id": source.spec_id,
        "path": source.selected_path,
        "sha256": source.content_sha256,
        "git_blob_sha": source.git_blob_sha,
        "symbol": symbol,
    }


def _observed(source: SourceFile | None, *tokens: str) -> bool:
    return source is not None and all(token in source.text for token in tokens)


def _rule(
    source: SourceFile | None,
    *,
    tokens: tuple[str, ...],
    source_semantics: str,
    **facts: Any,
) -> dict[str, Any]:
    return {
        "observed": _observed(source, *tokens),
        "source_semantics": source_semantics,
        **facts,
    }


def _balanced_body(text: str, declaration_pattern: str) -> str | None:
    match = re.search(declaration_pattern, text)
    if not match:
        return None
    opening = text.find("{", match.end())
    if opening < 0:
        return None
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    return None


def _struct_fields(source: SourceFile | None, name: str) -> list[str]:
    if source is None:
        return []
    body = _balanced_body(source.text, rf"pub\s+struct\s+{re.escape(name)}\b")
    if body is None:
        return []
    return re.findall(
        r"(?m)^\s*(?:#\[[^\n]+\]\s*)*pub\s+(?:r#)?([A-Za-z_][A-Za-z0-9_]*)\s*:",
        body,
    )


def _codex_error_retryability(source: SourceFile | None) -> dict[str, Any]:
    if source is None:
        return {"observed": False, "retryable": [], "terminal": []}
    body = _balanced_body(source.text, r"pub\s+fn\s+is_retryable\s*\(&self\)\s*->\s*bool")
    if body is None:
        return {"observed": False, "retryable": [], "terminal": []}

    table: dict[str, bool] = {}
    cursor = 0
    for match in re.finditer(r"=>\s*(true|false)\s*,", body):
        arm = body[cursor : match.start()]
        value = match.group(1) == "true"
        for variant in re.findall(r"CodexErrorDetails::([A-Za-z_][A-Za-z0-9_]*)", arm):
            table[variant] = value
        cursor = match.end()

    return {
        "observed": bool(table),
        "retryable": sorted(name for name, retryable in table.items() if retryable),
        "terminal": sorted(name for name, retryable in table.items() if not retryable),
        "table": {name: table[name] for name in sorted(table)},
        "source_semantics": "CodexErr::is_retryable match table",
    }


def _api_bridge_map(source: SourceFile | None) -> dict[str, Any]:
    return {
        "retryable_api_error": _rule(
            source,
            tokens=("ApiError::Retryable", "CodexErrorDetails::Stream"),
            source_semantics="ApiError::Retryable becomes Codex Stream with optional retry delay",
            codex_error="Stream",
        ),
        "rate_limit_api_error": _rule(
            source,
            tokens=("ApiError::RateLimitExceeded", "CodexErrorDetails::RateLimitExceeded"),
            source_semantics="stream rate-limit classification is preserved into Codex error details",
            codex_error="RateLimitExceeded",
        ),
        "server_overloaded_api_error": _rule(
            source,
            tokens=("ApiError::ServerOverloaded", "CodexErrorDetails::ServerOverloaded"),
            source_semantics="capacity classification is preserved into Codex error details",
            codex_error="ServerOverloaded",
        ),
        "http_503_server_overloaded": _rule(
            source,
            tokens=("StatusCode::SERVICE_UNAVAILABLE", "server_is_overloaded", "CodexErrorDetails::ServerOverloaded"),
            source_semantics="HTTP-shaped transport 503 with server_is_overloaded maps to capacity error",
            codex_error="ServerOverloaded",
        ),
        "http_503_slow_down": _rule(
            source,
            tokens=("StatusCode::SERVICE_UNAVAILABLE", "slow_down", "CodexErrorDetails::RateLimitExceeded"),
            source_semantics="HTTP-shaped transport 503 with slow_down maps to retryable rate-limit class",
            codex_error="RateLimitExceeded",
        ),
        "http_500": _rule(
            source,
            tokens=("StatusCode::INTERNAL_SERVER_ERROR", "CodexErrorDetails::InternalServerError"),
            source_semantics="HTTP 500 maps to Codex internal-server-error class",
            codex_error="InternalServerError",
        ),
        "http_429": _rule(
            source,
            tokens=("StatusCode::TOO_MANY_REQUESTS", "CodexErrorDetails::RetryLimit"),
            source_semantics="HTTP 429 is further classified for usage/quota conditions; otherwise RetryLimit",
            default_codex_error="RetryLimit",
        ),
    }


def _responses_error_map(
    sse: SourceFile | None,
    ws: SourceFile | None,
    turn: SourceFile | None,
    retry: SourceFile | None,
    api_bridge: SourceFile | None,
    protocol_error: SourceFile | None,
) -> dict[str, Any]:
    return {
        "response_failed": {
            "context_window": _rule(
                sse,
                tokens=("is_context_window_error(&error)", "ApiError::ContextWindowExceeded"),
                source_semantics="response.failed classifier",
                api_error="ContextWindowExceeded",
            ),
            "quota_exceeded": _rule(
                sse,
                tokens=("is_quota_exceeded_error(&error)", "ApiError::QuotaExceeded"),
                source_semantics="response.failed classifier",
                api_error="QuotaExceeded",
            ),
            "usage_not_included": _rule(
                sse,
                tokens=("is_usage_not_included(&error)", "ApiError::UsageNotIncluded"),
                source_semantics="response.failed classifier",
                api_error="UsageNotIncluded",
            ),
            "cyber_policy": _rule(
                sse,
                tokens=("is_cyber_policy_error(&error)", "ApiError::CyberPolicy"),
                source_semantics="response.failed classifier",
                api_error="CyberPolicy",
            ),
            "misalignment_policy_violation": _rule(
                sse,
                tokens=("misalignment_policy_violation", "ApiError::MisalignmentPolicyViolation"),
                source_semantics="response.failed error.code classifier",
                error_codes=["misalignment_policy_violation"],
                api_error="MisalignmentPolicyViolation",
            ),
            "invalid_request_codes": _rule(
                sse,
                tokens=("invalid_prompt", "bio_policy", "ApiError::InvalidRequest"),
                source_semantics="response.failed error.code classifier",
                error_codes=["invalid_prompt", "bio_policy"],
                api_error="InvalidRequest",
            ),
            "server_overloaded": _rule(
                sse,
                tokens=("is_server_overloaded_error(&error)", "ApiError::ServerOverloaded"),
                source_semantics="response.failed error.code classifier",
                error_codes=["server_is_overloaded"],
                api_error="ServerOverloaded",
            ),
            "rate_limit_codes": _rule(
                sse,
                tokens=("rate_limit_exceeded", "slow_down", "ApiError::RateLimitExceeded", "try_parse_retry_after"),
                source_semantics="response.failed fallback classifier with retry advice",
                error_codes=["rate_limit_exceeded", "slow_down"],
                api_error="RateLimitExceeded",
                retry_after="parsed from response error when present",
            ),
            "default": _rule(
                sse,
                tokens=("ApiError::Retryable { message, delay }", "try_parse_retry_after"),
                source_semantics="unrecognized response.failed error-code fallback",
                api_error="Retryable",
                retry_after="parsed from response error when present",
            ),
        },
        "response_incomplete": _rule(
            sse,
            tokens=('"response.incomplete"', "ApiError::Stream(message)"),
            source_semantics="response.incomplete classifier",
            api_error="Stream",
        ),
        "websocket_wrapped_error": {
            "previous_response_not_found": _rule(
                ws,
                tokens=("PREVIOUS_RESPONSE_NOT_FOUND_CODE", "ApiError::Retryable"),
                source_semantics="wrapped WebSocket error-code override before status mapping",
                api_error="Retryable",
            ),
            "websocket_connection_limit_reached": _rule(
                ws,
                tokens=("WEBSOCKET_CONNECTION_LIMIT_REACHED_CODE", "ApiError::Retryable"),
                source_semantics="wrapped WebSocket error-code override before status mapping",
                api_error="Retryable",
            ),
            "other_non_success_status": _rule(
                ws,
                tokens=("StatusCode::from_u16", "ApiError::Transport(TransportError::Http"),
                source_semantics="wrapped WebSocket error converted back to HTTP-shaped transport error",
                api_error="Transport::Http",
            ),
        },
        "websocket_transport": {
            "closed": _rule(
                ws,
                tokens=("WsError::ConnectionClosed | WsError::AlreadyClosed", 'ApiError::Stream("websocket closed"'),
                source_semantics="WebSocket transport error mapping",
                api_error="Stream",
            ),
            "io_or_other": _rule(
                ws,
                tokens=("ApiError::Transport(TransportError::Network",),
                source_semantics="WebSocket I/O/other error mapping",
                api_error="Transport::Network",
            ),
            "idle_timeout": _rule(
                ws,
                tokens=('ApiError::Stream("idle timeout waiting for websocket"',),
                source_semantics="WebSocket response polling timeout",
                api_error="Stream",
            ),
        },
        "api_to_codex_error": _api_bridge_map(api_bridge),
        "codex_error_retryability": _codex_error_retryability(protocol_error),
        "turn_retry_control": {
            "retryability_gate": _rule(
                turn,
                tokens=("if !err.is_retryable()", "handle_retryable_response_stream_error"),
                source_semantics="sampling loop returns terminal errors before entering retry handler",
                gate="CodexErr::is_retryable()",
            ),
            "retry_delay": _rule(
                retry,
                tokens=("err.retry_delay().unwrap_or_else(|| backoff(retry_count))",),
                source_semantics="server retry advice wins over local backoff",
                priority=["error retry_delay", "local backoff"],
            ),
            "websocket_to_http_fallback": _rule(
                retry,
                tokens=("try_switch_fallback_transport", "Falling back from WebSockets to HTTPS transport"),
                source_semantics="after normal stream retries are exhausted, eligible sessions can switch transport",
                target_transport="https",
            ),
            "unbounded_connection_retry_feature": _rule(
                retry,
                tokens=("Feature::UnboundedConnectionRetries", "CodexErrorDetails::ConnectionFailed"),
                source_semantics="feature-gated sampling connection failures use an independent exponential delay path",
                initial_delay_seconds=5,
                max_delay_seconds=60,
            ),
            "first_websocket_retry_ui_hidden_in_release": _rule(
                retry,
                tokens=("retry_count > 1", "cfg!(debug_assertions)", "responses_websocket_enabled"),
                source_semantics="release UI suppresses the first transient WebSocket reconnect notification",
            ),
        },
    }


def _fork_behavior(
    thread_protocol: SourceFile | None,
    processor: SourceFile | None,
    thread_manager: SourceFile | None,
    tui_session: SourceFile | None,
    tui_backtrack: SourceFile | None,
    tui_side: SourceFile | None,
    tui_slash: SourceFile | None,
) -> dict[str, Any]:
    fork_fields = _struct_fields(thread_protocol, "ThreadForkParams")
    side_surface_observed = _observed(
        tui_side,
        "fork_config.ephemeral = true",
        "fork_side_thread",
    )
    slash_aliases_observed = _observed(
        tui_slash,
        "SlashCommand::Side | SlashCommand::Btw",
        "ephemeral fork",
    )
    return {
        "rpc": "thread/fork",
        "request_fields": fork_fields,
        "axes": {
            "history_lineage": {
                "fresh_thread_identity": _rule(
                    thread_manager,
                    tokens=("fresh id", "fork_prepared_thread"),
                    source_semantics="fork allocates a new thread identity",
                ),
                "forked_from_relation": _rule(
                    thread_manager,
                    tokens=("forked_from_thread_id",),
                    source_semantics="new thread records the source thread as fork lineage",
                ),
            },
            "persistence": {
                "ephemeral_request_flag": {
                    "observed": "ephemeral" in fork_fields,
                    "field": "ephemeral" if "ephemeral" in fork_fields else None,
                    "source_semantics": "ThreadForkParams independently supplies an ephemeral override; persistence is not encoded by fork lineage itself",
                },
                "ephemeral_override_applied": _rule(
                    processor,
                    tokens=("typesafe_overrides.ephemeral = ephemeral.then_some(true)",),
                    source_semantics="thread/fork propagates ephemeral=true into effective thread config",
                ),
                "ephemeral_paginated_requires_exclude_turns": _rule(
                    processor,
                    tokens=("ephemeral paginated thread/fork requires `excludeTurns: true`",),
                    source_semantics="paginated ephemeral fork rejects embedded-turn hydration",
                ),
                "ephemeral_disallows_deferred_goal_continuation": _rule(
                    processor,
                    tokens=("if ephemeral && defer_goal_continuation",),
                    source_semantics="ephemeral fork rejects deferGoalContinuation",
                ),
                "durability_branch": _rule(
                    processor,
                    tokens=("let reserved_thread_id = if config.ephemeral", "stage_pending_thread_metadata"),
                    source_semantics="effective ephemeral threads skip the durable metadata reservation path; non-ephemeral threads use the persistent reservation path",
                    ephemeral="no reserved durable thread metadata",
                    non_ephemeral="stage pending durable thread metadata",
                ),
            },
            "tui_presentation": {
                "presentation_enum": _rule(
                    tui_session,
                    tokens=("enum ForkPresentation", "Regular", "SideConversation"),
                    source_semantics="TUI fork presentation is a separate axis from the thread/fork ephemeral flag",
                    variants=["Regular", "SideConversation"],
                ),
                "side_conversation_path": _rule(
                    tui_session,
                    tokens=("pub(crate) async fn fork_side_thread", "ForkPresentation::SideConversation"),
                    source_semantics="TUI has a dedicated SideConversation presentation wrapper over thread/fork",
                ),
                "side_forces_paginated_exclude_turns": _rule(
                    tui_session,
                    tokens=("presentation == ForkPresentation::SideConversation", "exclude_turns"),
                    source_semantics="SideConversation presentation forces excludeTurns in paginated-history mode",
                ),
                "persistence_is_not_presentation": {
                    "observed": ("ephemeral" in fork_fields)
                    and _observed(tui_session, "enum ForkPresentation", "SideConversation"),
                    "source_semantics": "ephemeral/durable persistence is represented separately from Regular/SideConversation presentation",
                },
            },
            "product_surface": {
                "side_conversation_forces_ephemeral": {
                    "observed": side_surface_observed,
                    "source_semantics": "TUI side-conversation setup sets fork_config.ephemeral=true before calling fork_side_thread",
                },
                "slash_aliases": {
                    "observed": slash_aliases_observed,
                    "commands": ["/side", "/btw"] if slash_aliases_observed else [],
                    "source_semantics": "SlashCommand::Side and SlashCommand::Btw are described as starting a side conversation in an ephemeral fork",
                },
                "classification": (
                    "side/btw = SideConversation presentation + ephemeral persistence override"
                    if side_surface_observed and slash_aliases_observed
                    else None
                ),
            },
            "rewind_prompt_edit": {
                "uses_fork": _rule(
                    tui_backtrack,
                    tokens=("ForkSessionForPromptEdit",),
                    source_semantics="TUI prompt-edit/backtrack creates a source-preserving branch instead of mutating the source thread",
                    operation="thread/fork",
                ),
            },
        },
    }


class RuntimeBehaviorExtractor:
    extractor_id = EXTRACTOR_ID
    source_spec_ids = SOURCE_IDS

    def extract(
        self,
        snapshot: SourceSnapshot,
        diagnostics: DiagnosticCollector,
    ) -> ExtractorResult:
        del diagnostics
        sources = {source_id: snapshot.files.get(source_id) for source_id in SOURCE_IDS}
        available = sorted(source_id for source_id, source in sources.items() if source is not None)
        missing = sorted(source_id for source_id, source in sources.items() if source is None)

        body: dict[str, Any] = {
            "ownership": {
                "owns": [
                    "revision-sensitive Responses error classification and retry control observations",
                    "revision-sensitive thread/fork persistence, presentation, and product-surface observations",
                ],
                "does_not_own": [
                    "high-level transport design rationale",
                    "generic app-server RPC schema",
                    "prompt composition",
                    "server-side routing implementation",
                ],
            },
            "coverage": {
                "available_source_spec_ids": available,
                "missing_source_spec_ids": missing,
                "mode": "observation-by-source-pattern; absence remains explicit and does not become a fallback fact",
            },
            "responses": _responses_error_map(
                sources[SSE],
                sources[WS],
                sources[PROMPT_TURN],
                sources[RESPONSES_RETRY],
                sources[API_BRIDGE],
                sources[PROTOCOL_ERROR],
            ),
            "fork": _fork_behavior(
                sources[THREAD_PROTOCOL],
                sources[THREAD_PROCESSOR],
                sources[THREAD_MANAGER],
                sources[TUI_SESSION],
                sources[TUI_BACKTRACK],
                sources[TUI_SIDE],
                sources[TUI_SLASH],
            ),
            "evidence": {
                source_id: _evidence(source, "runtime behavior observation")
                for source_id, source in sorted(sources.items())
                if source is not None
            },
        }
        body["semantic_digest"] = hashlib.sha256(_canonical(body)).hexdigest()
        return ExtractorResult(
            extractor_id=EXTRACTOR_ID,
            schema_version=SCHEMA_VERSION,
            data=body,
            semantic_complete=not missing,
            source_spec_ids=SOURCE_IDS,
        )


@register_extractor(EXTRACTOR_ID)
def _runtime_behavior_factory() -> RuntimeBehaviorExtractor:
    return RuntimeBehaviorExtractor()
