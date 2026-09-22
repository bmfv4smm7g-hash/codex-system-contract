"""Responses retry, reconnect, and app-server retry-surface classification."""
from __future__ import annotations

import re
from typing import Any

from ..models import SourceFile


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


def codex_error_retryability(source: SourceFile | None) -> dict[str, Any]:
    if source is None:
        return {"observed": False, "retryable": [], "terminal": []}

    body = _balanced_body(
        source.text,
        r"pub\s+fn\s+retry_delay\s*\(&self,\s*retry_count:\s*u64\)\s*->\s*Option<Duration>",
    )
    implementation = "retry_delay"
    value_pattern = r"=>\s*(None|Some\s*\()"
    if body is None:
        body = _balanced_body(source.text, r"pub\s+fn\s+is_retryable\s*\(&self\)\s*->\s*bool")
        implementation = "is_retryable"
        value_pattern = r"=>\s*(true|false)\s*,"
    if body is None:
        return {"observed": False, "retryable": [], "terminal": []}

    table: dict[str, bool] = {}
    cursor = 0
    for match in re.finditer(value_pattern, body):
        arm = body[cursor : match.start()]
        retryable = match.group(1) == "true" or match.group(1).startswith("Some")
        for variant in re.findall(r"CodexErrorDetails::([A-Za-z_][A-Za-z0-9_]*)", arm):
            table[variant] = retryable
        cursor = match.end()

    return {
        "observed": bool(table),
        "implementation": implementation,
        "retryable": sorted(name for name, retryable in table.items() if retryable),
        "terminal": sorted(name for name, retryable in table.items() if not retryable),
        "table": {name: table[name] for name in sorted(table)},
        "source_semantics": (
            "CodexErr::retry_delay(retry_count) Option table"
            if implementation == "retry_delay"
            else "legacy CodexErr::is_retryable match table"
        ),
    }


def turn_state_reconnect(core: SourceFile | None, ws: SourceFile | None) -> dict[str, Any]:
    ws_body = (
        _balanced_body(ws.text, r"async\s+fn\s+run_websocket_response_stream\b")
        if ws is not None
        else None
    )
    generic_close = bool(
        ws_body
        and "Message::Close(_)" in ws_body
        and "websocket closed by server before response.completed" in ws_body
    )
    close_code_inspected = bool(ws_body and ("frame.code" in ws_body or "close.code" in ws_body))
    core_text = core.text if core is not None else ""
    owner_reset = (
        "if owner_changed" in core_text
        and "self.turn_state = Arc::new(OnceLock::new())" in core_text
    )
    reconnect_detected = (
        "conn.is_closed().await" in core_text
        or "needs_new = match self.websocket_session.connection.as_ref()" in core_text
    )
    replayed = "client_metadata.insert(X_CODEX_TURN_STATE_HEADER" in core_text
    return {
        "close_frame": {
            "observed": generic_close,
            "close_code_inspected": close_code_inspected,
            "service_restart_1012_special_cased": bool(ws_body and "1012" in ws_body),
            "api_error": "Stream" if generic_close else None,
        },
        "turn_state": {
            "fresh_per_logical_turn": "turn_state: Arc::new(OnceLock::new())" in core_text,
            "replayed_in_websocket_client_metadata": replayed,
            "physical_reconnect_detected": reconnect_detected,
            "preserved_across_plain_connection_close": reconnect_detected and replayed,
            "reset_on_auth_owner_change": owner_reset,
            "source_semantics": (
                "physical WebSocket state resets independently from the turn-scoped OnceLock; "
                "current main additionally resets turn state on auth-owner change"
            ),
        },
    }


def app_server_retry_surface(
    notification: SourceFile | None,
    events: SourceFile | None,
    retryability: dict[str, Any],
) -> dict[str, Any]:
    notification_contract = (
        notification is not None
        and "will_retry" in notification.text
        and "automatically retry" in notification.text
    )
    stream_is_retry = (
        events is not None
        and "EventMsg::StreamError" in events.text
        and "will_retry: true" in events.text
    )
    terminal_is_not_retry = (
        events is not None
        and "EventMsg::Error" in events.text
        and "will_retry: false" in events.text
    )
    server_overloaded_retryable = retryability.get("table", {}).get("ServerOverloaded")
    return {
        "notification_contract_observed": notification_contract,
        "will_retry_true_means_app_server_automatic_retry": notification_contract,
        "stream_error_emits_will_retry_true": stream_is_retry,
        "terminal_error_emits_will_retry_false": terminal_is_not_retry,
        "server_overloaded_core_retryable": server_overloaded_retryable,
        "server_overloaded_app_server_will_retry": (
            False
            if server_overloaded_retryable is False and terminal_is_not_retry
            else None
        ),
        "desktop_outer_retry": (
            "outside this open-source app-server retry contract; a desktop frontend may resubmit "
            "a terminal failed turn independently"
        ),
    }
