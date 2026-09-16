"""Canonical app-server RPC and thread/turn/item lifecycle extraction.

App-server owns its wire envelope, request/response dispatch, notification
projection, lifecycle state, and pagination contract. Local persistence,
Responses transport, permission policy, and agent execution remain separate.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile, SourceSnapshot
from .registry import ExtractorResult, register_extractor
from .app_server_history_mutation import (
    APP_SERVER_THREAD_PROCESSOR,
    STORAGE_PAGINATED_FORK,
    STORAGE_REVERT,
    THREAD_MANAGER,
    TUI_APP_SERVER_SESSION,
    TUI_BACKTRACK,
    build_history_mutation,
    validate_history_mutation_sources,
)

EXTRACTOR_ID = "extractor.app_server_rpc"
SCHEMA_VERSION = "2.0.0"
SCHEMA_ID = "https://schemas.codex-system-contract.invalid/app-server/rpc-lifecycle-v2.schema.json"

SOURCE_IDS = {
    "common": "source_spec.extra.app_server_common",
    "thread": "source_spec.extra.app_server_thread",
    "thread_data": "source_spec.extra.app_server_thread_data",
    "turn": "source_spec.extra.app_server_turn",
    "item": "source_spec.extra.app_server_item",
    "rpc": "source_spec.extra.app_server_rpc",
    "processor": APP_SERVER_THREAD_PROCESSOR,
    "thread_manager": THREAD_MANAGER,
    "tui_session": TUI_APP_SERVER_SESSION,
    "tui_backtrack": TUI_BACKTRACK,
    "storage_fork": STORAGE_PAGINATED_FORK,
    "storage_revert": STORAGE_REVERT,
}

CORE_METHODS = {
    "thread/start",
    "thread/resume",
    "thread/read",
    "thread/list",
    "thread/turns/list",
    "thread/items/list",
    "thread/fork",
    "thread/revert",
    "turn/start",
    "turn/steer",
    "turn/interrupt",
}
CORE_NOTIFICATIONS = {
    "thread/started",
    "thread/status/changed",
    "thread/reverted",
    "turn/started",
    "turn/completed",
    "item/started",
    "item/completed",
}


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


def _missing(
    diagnostics: DiagnosticCollector,
    *,
    code: str,
    token: str,
    source: SourceFile | None,
    entity: str,
) -> None:
    diagnostics.emit(
        code=code,
        severity="error",
        category="app_server_rpc",
        message=f"Required app-server lifecycle evidence is missing: {token}",
        extractor_id=EXTRACTOR_ID,
        entity_id=entity,
        source_refs=[source.spec_id] if source else [],
        details={"path": source.selected_path, "token": token} if source else {"token": token},
        recoverable=False,
        strict_failure=True,
    )


def _require(
    diagnostics: DiagnosticCollector,
    source: SourceFile,
    tokens: tuple[tuple[str, str], ...],
    *,
    entity: str,
) -> bool:
    complete = True
    for code, token in tokens:
        if token not in source.text:
            complete = False
            _missing(diagnostics, code=code, token=token, source=source, entity=entity)
    return complete


def _balanced_block(text: str, marker: str) -> str | None:
    start = text.find(marker)
    if start < 0:
        return None
    opening = text.find("{", start + len(marker))
    if opening < 0:
        return None
    depth = 0
    for index in range(opening, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    return None


def _struct_fields(text: str, name: str) -> list[str]:
    body = _balanced_block(text, f"pub struct {name}")
    if body is None:
        return []
    return re.findall(
        r"(?:^\s*|,\s*)(?:#\[[^\]]+\]\s*)*pub\s+(?:r#)?([A-Za-z_][A-Za-z0-9_]*)\s*:",
        body,
        re.MULTILINE,
    )


def _enum_variants(text: str, name: str) -> list[str]:
    body = _balanced_block(text, f"pub enum {name}")
    if body is None:
        return []
    variants = re.findall(
        r"(?:^|,)\s*(?:#\[[^\]]+\]\s*)*([A-Z][A-Za-z0-9_]*)\b",
        body,
        re.MULTILINE,
    )
    return list(dict.fromkeys(variants))


def _request_dispatch(text: str) -> list[dict[str, str]]:
    block = _balanced_block(text, "client_request_definitions!")
    if block is None:
        return []
    rows: list[dict[str, str]] = []
    pattern = re.compile(
        r"(?m)^\s*(?:#\[[^\n]+\]\s*)*(?P<variant>[A-Za-z][A-Za-z0-9_]*)\s*=>\s*"
        r'"(?P<wire>[^"]+)"\s*\{(?P<body>.*?)^\s*\},',
        re.DOTALL,
    )
    for match in pattern.finditer(block):
        wire = match.group("wire")
        if not wire.startswith(("thread/", "turn/")):
            continue
        body = match.group("body")
        params = re.search(r"params:\s*(?:#\[[^\]]+\]\s*)*(?P<value>[^,\n]+)", body)
        response = re.search(r"response:\s*(?P<value>[^,\n]+)", body)
        serialization = re.search(r"serialization:\s*(?P<value>[^\n]+?),\s*$", body, re.MULTILINE)
        if not params or not response or not serialization:
            continue
        rows.append(
            {
                "variant": match.group("variant"),
                "method": wire,
                "params": params.group("value").strip(),
                "response": response.group("value").strip(),
                "serialization": serialization.group("value").strip(),
            }
        )
    return rows


def _notification_dispatch(text: str) -> list[dict[str, str]]:
    block = _balanced_block(text, "server_notification_definitions!")
    if block is None:
        return []
    rows = []
    pattern = re.compile(
        r"(?m)^\s*(?:#\[[^\n]+\]\s*)*(?P<variant>[A-Za-z][A-Za-z0-9_]*)\s*"
        r'=>\s*"(?P<wire>[^"]+)"\s*\((?P<payload>[^)]+)\)',
    )
    for match in pattern.finditer(block):
        wire = match.group("wire")
        if wire.startswith(("thread/", "turn/", "item/")):
            rows.append(
                {
                    "variant": match.group("variant"),
                    "method": wire,
                    "payload": match.group("payload").strip(),
                }
            )
    return rows


def _shape(text: str, names: tuple[str, ...]) -> dict[str, list[str]]:
    return {name: _struct_fields(text, name) for name in names}


def _validate_inventory(
    diagnostics: DiagnosticCollector,
    source: SourceFile,
    requests: list[dict[str, str]],
    notifications: list[dict[str, str]],
) -> bool:
    methods = {row["method"] for row in requests}
    notification_methods = {row["method"] for row in notifications}
    complete = True
    missing_methods = sorted(CORE_METHODS - methods)
    missing_notifications = sorted(CORE_NOTIFICATIONS - notification_methods)
    if missing_methods:
        complete = False
        _missing(
            diagnostics,
            code="APP_SERVER_CORE_METHOD_INVENTORY_INCOMPLETE",
            token=", ".join(missing_methods),
            source=source,
            entity="app_server_rpc.dispatch",
        )
    if missing_notifications:
        complete = False
        _missing(
            diagnostics,
            code="APP_SERVER_CORE_NOTIFICATION_INVENTORY_INCOMPLETE",
            token=", ".join(missing_notifications),
            source=source,
            entity="app_server_rpc.notifications",
        )
    return complete


def _build_contract_body(
    *,
    common: SourceFile,
    thread: SourceFile,
    thread_data: SourceFile,
    turn: SourceFile,
    item: SourceFile,
    rpc: SourceFile,
    processor: SourceFile,
    thread_manager: SourceFile,
    tui_session: SourceFile,
    tui_backtrack: SourceFile,
    storage_fork: SourceFile,
    storage_revert: SourceFile,
    history_mutation: dict[str, Any],
    requests: list[dict[str, str]],
    notifications: list[dict[str, str]],
    thread_statuses: list[str],
    turn_statuses: list[str],
    history_modes: list[str],
    item_views: list[str],
    complete: bool,
) -> dict[str, Any]:
    return {
        "$schema": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "ownership": {
            "owns": [
                "app-server request/response/notification wire dispatch",
                "thread/turn/item lifecycle payload shape",
                "per-request serialization scope",
                "thread history mode and item hydration view",
                "turn lifecycle status and steering precondition",
                "thread/turn/item pagination request shape",
                "fork/revert history mutation orchestration and client-visible identity semantics",
            ],
            "does_not_own": [
                "local rollout or SQLite persistence implementation",
                "Responses upstream request/event transport",
                "permission/approval policy semantics",
                "MCP/plugin capability projection",
                "multi-agent execution/control internals",
                "account/realtime/application feature APIs outside lifecycle dispatch",
            ],
        },
        "rpc_envelope": {
            "dialect": "JSON-RPC-shaped but omits the jsonrpc=2.0 wire field",
            "request_id": ["string", "integer"],
            "request": ["id", "method", "optional params", "optional W3C trace"],
            "notification": ["method", "optional params"],
            "response": ["id", "result"],
            "error": ["id", "error.code", "error.message", "optional error.data"],
        },
        "request_dispatch": requests,
        "notification_dispatch": notifications,
        "thread": {
            "statuses": thread_statuses,
            "history_modes": history_modes,
            "identity_fields": _struct_fields(thread_data.text, "Thread"),
            "start_fields": _struct_fields(thread.text, "ThreadStartParams"),
            "resume_fields": _struct_fields(thread.text, "ThreadResumeParams"),
            "read_fields": _struct_fields(thread.text, "ThreadReadParams"),
            "list_fields": _struct_fields(thread.text, "ThreadListParams"),
            "turns_list_fields": _struct_fields(thread.text, "ThreadTurnsListParams"),
            "items_list_fields": _struct_fields(thread.text, "ThreadItemsListParams"),
            "resume_precedence": "for non-running threads: history > non-empty path > thread_id; a running thread_id rejoins the live thread and a supplied path becomes a consistency check",
        },
        "turn": {
            "statuses": turn_statuses,
            "items_views": item_views,
            "data_fields": _struct_fields(thread_data.text, "Turn"),
            "start_fields": _struct_fields(turn.text, "TurnStartParams"),
            "steer_fields": _struct_fields(turn.text, "TurnSteerParams"),
            "interrupt_fields": _struct_fields(turn.text, "TurnInterruptParams"),
            "steer_precondition": "expectedTurnId must match the currently active turn",
        },
        "history_mutation": history_mutation,
        "pagination": {
            "thread_list": "opaque cursor + optional limit over thread summaries",
            "turn_list": "threadId + opaque cursor + optional limit; use for paginated history instead of full thread/read hydration",
            "item_list": "threadId + optional turnId + opaque cursor + optional limit across persisted item history",
            "items_view": "NotLoaded, Summary, and Full describe hydration independently of turn status",
        },
        "evidence": {
            "common": _evidence(common, "client_request_definitions/server_notification_definitions"),
            "thread": _evidence(thread, "ThreadStartParams/ThreadResumeParams/pagination params"),
            "thread_data": _evidence(thread_data, "Thread/Turn/ThreadHistoryMode/TurnItemsView"),
            "turn": _evidence(turn, "TurnStatus/TurnStartParams/TurnSteerParams/TurnInterruptParams"),
            "item": _evidence(item, "ThreadItem"),
            "rpc": _evidence(rpc, "JSONRPCMessage/JSONRPCRequest/JSONRPCNotification"),
            "processor": _evidence(processor, "thread_fork_inner/thread_revert_response/reload_paginated_thread"),
            "thread_manager": _evidence(thread_manager, "fork_prepared_thread/fork_thread_with_initial_history"),
            "tui_session": _evidence(tui_session, "fork_thread_at/ClientRequest::ThreadFork"),
            "tui_backtrack": _evidence(tui_backtrack, "ForkSessionForPromptEdit"),
            "storage_fork": _evidence(storage_fork, "prepare/history_base_at_boundary"),
            "storage_revert": _evidence(storage_revert, "revert/create_replacement_recorder"),
        },
        "semantic_complete": complete,
    }


class AppServerRpcExtractor:
    extractor_id = EXTRACTOR_ID
    source_spec_ids = tuple(SOURCE_IDS.values())

    def extract(self, snapshot: SourceSnapshot, diagnostics: DiagnosticCollector) -> ExtractorResult:
        sources = {key: snapshot.files.get(spec_id) for key, spec_id in SOURCE_IDS.items()}
        missing = [key for key, source in sources.items() if source is None]
        if missing:
            for key in missing:
                _missing(
                    diagnostics,
                    code="APP_SERVER_RPC_SOURCE_UNAVAILABLE",
                    token=key,
                    source=None,
                    entity=f"app_server_rpc.source.{key}",
                )
            return ExtractorResult(EXTRACTOR_ID, SCHEMA_VERSION, {}, False, self.source_spec_ids)

        common = sources["common"]
        thread = sources["thread"]
        thread_data = sources["thread_data"]
        turn = sources["turn"]
        item = sources["item"]
        rpc = sources["rpc"]
        processor = sources["processor"]
        thread_manager = sources["thread_manager"]
        tui_session = sources["tui_session"]
        tui_backtrack = sources["tui_backtrack"]
        storage_fork = sources["storage_fork"]
        storage_revert = sources["storage_revert"]
        assert common and thread and thread_data and turn and item and rpc and processor and thread_manager and tui_session and tui_backtrack and storage_fork and storage_revert

        complete = _require(
            diagnostics,
            common,
            (
                ("APP_SERVER_REQUEST_MACRO_MISSING", "client_request_definitions!"),
                ("APP_SERVER_NOTIFICATION_MACRO_MISSING", "server_notification_definitions!"),
                ("APP_SERVER_SERIALIZATION_SCOPE_MISSING", "ClientRequestSerializationScope"),
                ("APP_SERVER_THREAD_START_WIRE_MISSING", 'ThreadStart => "thread/start"'),
                ("APP_SERVER_TURN_START_WIRE_MISSING", 'TurnStart => "turn/start"'),
            ),
            entity="app_server_rpc.dispatch",
        )
        complete &= _require(
            diagnostics,
            rpc,
            (
                ("APP_SERVER_JSONRPC_MESSAGE_MISSING", "pub enum JSONRPCMessage"),
                ("APP_SERVER_JSONRPC_REQUEST_MISSING", "pub struct JSONRPCRequest"),
                ("APP_SERVER_JSONRPC_NOTIFICATION_MISSING", "pub struct JSONRPCNotification"),
                ("APP_SERVER_JSONRPC_RESPONSE_MISSING", "pub struct JSONRPCResponse"),
                ("APP_SERVER_JSONRPC_ERROR_MISSING", "pub struct JSONRPCError"),
                ("APP_SERVER_JSONRPC_VERSION_NOTE_MISSING", "We do not do true JSON-RPC 2.0"),
            ),
            entity="app_server_rpc.envelope",
        )
        complete &= _require(
            diagnostics,
            thread,
            (
                ("APP_SERVER_THREAD_START_PARAMS_MISSING", "pub struct ThreadStartParams"),
                ("APP_SERVER_THREAD_RESUME_PARAMS_MISSING", "pub struct ThreadResumeParams"),
                ("APP_SERVER_THREAD_READ_PARAMS_MISSING", "pub struct ThreadReadParams"),
                ("APP_SERVER_THREAD_LIST_PARAMS_MISSING", "pub struct ThreadListParams"),
                ("APP_SERVER_THREAD_TURNS_LIST_MISSING", "pub struct ThreadTurnsListParams"),
                ("APP_SERVER_THREAD_ITEMS_LIST_MISSING", "pub struct ThreadItemsListParams"),
                ("APP_SERVER_THREAD_FORK_PARAMS_MISSING", "pub struct ThreadForkParams"),
                ("APP_SERVER_THREAD_REVERT_PARAMS_MISSING", "pub struct ThreadRevertParams"),
                ("APP_SERVER_THREAD_REVERT_FILES_BOUNDARY_MISSING", "This only changes persisted conversation history. It does not revert local file changes."),
                ("APP_SERVER_THREAD_STATUS_MISSING", "pub enum ThreadStatus"),
            ),
            entity="app_server_rpc.thread",
        )
        complete &= _require(
            diagnostics,
            thread_data,
            (
                ("APP_SERVER_THREAD_HISTORY_MODE_MISSING", "pub enum ThreadHistoryMode"),
                ("APP_SERVER_THREAD_DATA_MISSING", "pub struct Thread"),
                ("APP_SERVER_TURN_DATA_MISSING", "pub struct Turn"),
                ("APP_SERVER_TURN_ITEMS_VIEW_MISSING", "pub enum TurnItemsView"),
            ),
            entity="app_server_rpc.data",
        )
        complete &= _require(
            diagnostics,
            turn,
            (
                ("APP_SERVER_TURN_STATUS_MISSING", "pub enum TurnStatus"),
                ("APP_SERVER_TURN_START_PARAMS_MISSING", "pub struct TurnStartParams"),
                ("APP_SERVER_TURN_STEER_PARAMS_MISSING", "pub struct TurnSteerParams"),
                ("APP_SERVER_TURN_INTERRUPT_PARAMS_MISSING", "pub struct TurnInterruptParams"),
                ("APP_SERVER_EXPECTED_TURN_ID_MISSING", "pub expected_turn_id: String"),
            ),
            entity="app_server_rpc.turn",
        )
        complete &= _require(
            diagnostics,
            item,
            (("APP_SERVER_THREAD_ITEM_MISSING", "pub enum ThreadItem"),),
            entity="app_server_rpc.item",
        )
        complete &= validate_history_mutation_sources(
            diagnostics=diagnostics,
            extractor_id=EXTRACTOR_ID,
            processor=processor,
            thread_manager=thread_manager,
            tui_session=tui_session,
            tui_backtrack=tui_backtrack,
            storage_fork=storage_fork,
            storage_revert=storage_revert,
        )
        history_mutation = build_history_mutation()

        requests = _request_dispatch(common.text)
        notifications = _notification_dispatch(common.text)
        complete &= _validate_inventory(diagnostics, common, requests, notifications)

        thread_statuses = _enum_variants(thread.text, "ThreadStatus")
        turn_statuses = _enum_variants(turn.text, "TurnStatus")
        history_modes = _enum_variants(thread_data.text, "ThreadHistoryMode")
        item_views = _enum_variants(thread_data.text, "TurnItemsView")
        if not {"NotLoaded", "Idle", "SystemError", "Active"}.issubset(thread_statuses):
            complete = False
            _missing(
                diagnostics,
                code="APP_SERVER_THREAD_STATUS_DRIFT",
                token="NotLoaded, Idle, SystemError, Active",
                source=thread,
                entity="app_server_rpc.thread_status",
            )
        if not {"Completed", "Interrupted", "Failed", "InProgress"}.issubset(turn_statuses):
            complete = False
            _missing(
                diagnostics,
                code="APP_SERVER_TURN_STATUS_DRIFT",
                token="Completed, Interrupted, Failed, InProgress",
                source=turn,
                entity="app_server_rpc.turn_status",
            )
        if history_modes != ["Legacy", "Paginated"]:
            complete = False
            _missing(
                diagnostics,
                code="APP_SERVER_HISTORY_MODE_DRIFT",
                token="Legacy, Paginated",
                source=thread_data,
                entity="app_server_rpc.history_mode",
            )
        if not {"NotLoaded", "Summary", "Full"}.issubset(item_views):
            complete = False
            _missing(
                diagnostics,
                code="APP_SERVER_ITEMS_VIEW_DRIFT",
                token="NotLoaded, Summary, Full",
                source=thread_data,
                entity="app_server_rpc.items_view",
            )

        body = _build_contract_body(
            common=common,
            thread=thread,
            thread_data=thread_data,
            turn=turn,
            item=item,
            rpc=rpc,
            processor=processor,
            thread_manager=thread_manager,
            tui_session=tui_session,
            tui_backtrack=tui_backtrack,
            storage_fork=storage_fork,
            storage_revert=storage_revert,
            history_mutation=history_mutation,
            requests=requests,
            notifications=notifications,
            thread_statuses=thread_statuses,
            turn_statuses=turn_statuses,
            history_modes=history_modes,
            item_views=item_views,
            complete=complete,
        )
        body["semantic_digest"] = hashlib.sha256(_canonical(body)).hexdigest()
        return ExtractorResult(
            extractor_id=EXTRACTOR_ID,
            schema_version=SCHEMA_VERSION,
            data=body,
            semantic_complete=complete,
            source_spec_ids=self.source_spec_ids,
        )


@register_extractor(EXTRACTOR_ID)
def _factory() -> AppServerRpcExtractor:
    return AppServerRpcExtractor()
