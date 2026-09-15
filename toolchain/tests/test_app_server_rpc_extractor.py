from __future__ import annotations

from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.extractors.app_server_rpc import AppServerRpcExtractor
from codex_wire_audit.legacy import load_legacy_modules
from codex_wire_audit.models import SourceFile, SourceGroup, SourceRevision, SourceSnapshot, SourceSpec
from codex_wire_audit.orchestrator import build_registry


def _file(spec_id: str, key: str, path: str, text: str) -> SourceFile:
    spec = SourceSpec(
        id=spec_id,
        legacy_key=key,
        group=SourceGroup.EXTRA,
        path_candidates=(path,),
        required=False,
        roles=("legacy_extra",),
        expected_symbols=(),
        extractor_ids=(),
    )
    return SourceFile.create(spec=spec, selected_path=path, raw_bytes=text.encode())


def _snapshot(*, omit: str | None = None, break_turn_status: bool = False) -> SourceSnapshot:
    common = '''
pub enum ClientRequestSerializationScope { Global(&'static str), Thread { thread_id: String } }
macro_rules! client_request_definitions { ($($tt:tt)*) => {}; }
client_request_definitions! {
    ThreadStart => "thread/start" {
        params: v2::ThreadStartParams,
        serialization: None,
        response: v2::ThreadStartResponse,
    },
    ThreadResume => "thread/resume" {
        params: v2::ThreadResumeParams,
        serialization: thread_or_path(params.thread_id, params.path),
        response: v2::ThreadResumeResponse,
    },
    ThreadRead => "thread/read" {
        params: v2::ThreadReadParams,
        serialization: thread_id(params.thread_id),
        response: v2::ThreadReadResponse,
    },
    ThreadList => "thread/list" {
        params: v2::ThreadListParams,
        serialization: global_shared_read("thread/list"),
        response: v2::ThreadListResponse,
    },
    ThreadTurnsList => "thread/turns/list" {
        params: v2::ThreadTurnsListParams,
        serialization: thread_id(params.thread_id),
        response: v2::ThreadTurnsListResponse,
    },
    ThreadItemsList => "thread/items/list" {
        params: v2::ThreadItemsListParams,
        serialization: thread_id(params.thread_id),
        response: v2::ThreadItemsListResponse,
    },
    TurnStart => "turn/start" {
        params: v2::TurnStartParams,
        serialization: thread_id(params.thread_id),
        response: v2::TurnStartResponse,
    },
    TurnSteer => "turn/steer" {
        params: v2::TurnSteerParams,
        serialization: thread_id(params.thread_id),
        response: v2::TurnSteerResponse,
    },
    TurnInterrupt => "turn/interrupt" {
        params: v2::TurnInterruptParams,
        serialization: thread_id(params.thread_id),
        response: v2::TurnInterruptResponse,
    },
}
macro_rules! server_notification_definitions { ($($tt:tt)*) => {}; }
server_notification_definitions! {
    ThreadStarted => "thread/started" (v2::ThreadStartedNotification),
    ThreadStatusChanged => "thread/status/changed" (v2::ThreadStatusChangedNotification),
    TurnStarted => "turn/started" (v2::TurnStartedNotification),
    TurnCompleted => "turn/completed" (v2::TurnCompletedNotification),
    ItemStarted => "item/started" (v2::ItemStartedNotification),
    ItemCompleted => "item/completed" (v2::ItemCompletedNotification),
}
'''
    thread = '''
pub struct ThreadStartParams { pub model: Option<String>, pub cwd: Option<String> }
pub struct ThreadResumeParams { pub thread_id: String, pub history: Option<Vec<String>>, pub path: Option<String> }
pub struct ThreadReadParams { pub thread_id: String, pub include_turns: bool }
pub struct ThreadListParams { pub cursor: Option<String>, pub limit: Option<usize> }
pub struct ThreadTurnsListParams { pub thread_id: String, pub cursor: Option<String>, pub limit: Option<usize> }
pub struct ThreadItemsListParams { pub thread_id: String, pub turn_id: Option<String>, pub cursor: Option<String>, pub limit: Option<usize> }
pub enum ThreadStatus { NotLoaded, Idle, SystemError, Active { active_flags: Vec<String> } }
'''
    thread_data = '''
pub enum ThreadHistoryMode { Legacy, Paginated }
pub struct Thread {
    pub id: String,
    pub session_id: String,
    pub forked_from_id: Option<String>,
    pub parent_thread_id: Option<String>,
    pub history_mode: ThreadHistoryMode,
    pub status: ThreadStatus,
    pub turns: Vec<Turn>,
}
pub struct Turn {
    pub id: String,
    pub items: Vec<ThreadItem>,
    pub items_view: TurnItemsView,
    pub status: TurnStatus,
    pub error: Option<String>,
}
pub enum TurnItemsView { NotLoaded, Summary, Full }
'''
    turn = '''
pub enum TurnStatus { Completed, Interrupted, Failed, InProgress }
pub struct TurnStartParams { pub thread_id: String, pub input: Vec<String> }
pub struct TurnSteerParams { pub thread_id: String, pub input: Vec<String>, pub expected_turn_id: String }
pub struct TurnInterruptParams { pub thread_id: String, pub turn_id: String }
'''
    if break_turn_status:
        turn = turn.replace("Interrupted, ", "")
    item = '''
pub enum ThreadItem { UserMessage { id: String }, AgentMessage { id: String } }
'''
    rpc = '''
//! We do not do true JSON-RPC 2.0, as we neither send nor expect the "jsonrpc": "2.0" field.
pub enum RequestId { String(String), Integer(i64) }
pub enum JSONRPCMessage { Request(JSONRPCRequest), Notification(JSONRPCNotification), Response(JSONRPCResponse), Error(JSONRPCError) }
pub struct JSONRPCRequest { pub id: RequestId, pub method: String, pub params: Option<String>, pub trace: Option<String> }
pub struct JSONRPCNotification { pub method: String, pub params: Option<String> }
pub struct JSONRPCResponse { pub id: RequestId, pub result: String }
pub struct JSONRPCError { pub error: String, pub id: RequestId }
'''
    rows = {
        "common": _file("source_spec.extra.app_server_common", "app_server_common", "codex-rs/app-server-protocol/src/protocol/common.rs", common),
        "thread": _file("source_spec.extra.app_server_thread", "app_server_thread", "codex-rs/app-server-protocol/src/protocol/v2/thread.rs", thread),
        "thread_data": _file("source_spec.extra.app_server_thread_data", "app_server_thread_data", "codex-rs/app-server-protocol/src/protocol/v2/thread_data.rs", thread_data),
        "turn": _file("source_spec.extra.app_server_turn", "app_server_turn", "codex-rs/app-server-protocol/src/protocol/v2/turn.rs", turn),
        "item": _file("source_spec.extra.app_server_item", "app_server_item", "codex-rs/app-server-protocol/src/protocol/v2/item.rs", item),
        "rpc": _file("source_spec.extra.app_server_rpc", "app_server_rpc", "codex-rs/app-server-protocol/src/rpc.rs", rpc),
    }
    if omit:
        rows.pop(omit)
    files = {row.spec_id: row for row in rows.values()}
    revision = SourceRevision("fixture", "openai/codex", "fixture", "3" * 40, SourceSnapshot.digest_files(files), False)
    return SourceSnapshot(revision, files)


def test_default_registry_assigns_lifecycle_sources_to_app_server_domain():
    registry = build_registry(load_legacy_modules())
    expected = {
        "source_spec.extra.app_server_common",
        "source_spec.extra.app_server_thread",
        "source_spec.extra.app_server_thread_data",
        "source_spec.extra.app_server_turn",
        "source_spec.extra.app_server_item",
        "source_spec.extra.app_server_rpc",
    }
    observed = {spec.id for spec in registry.specs if "extractor.app_server_rpc" in spec.extractor_ids}
    assert observed == expected


def test_app_server_extractor_parses_dispatch_and_serialization_scope():
    diagnostics = DiagnosticCollector()
    result = AppServerRpcExtractor().extract(_snapshot(), diagnostics)
    assert result.semantic_complete
    assert diagnostics.summary()["error"] == 0
    methods = {row["method"]: row for row in result.data["request_dispatch"]}
    assert methods["thread/resume"]["serialization"] == "thread_or_path(params.thread_id, params.path)"
    assert methods["turn/start"]["params"] == "v2::TurnStartParams"
    assert methods["turn/interrupt"]["response"] == "v2::TurnInterruptResponse"


def test_app_server_extractor_captures_lifecycle_state_and_pagination():
    result = AppServerRpcExtractor().extract(_snapshot(), DiagnosticCollector())
    assert result.data["thread"]["statuses"] == ["NotLoaded", "Idle", "SystemError", "Active"]
    assert result.data["thread"]["history_modes"] == ["Legacy", "Paginated"]
    assert result.data["turn"]["statuses"] == ["Completed", "Interrupted", "Failed", "InProgress"]
    assert result.data["turn"]["items_views"] == ["NotLoaded", "Summary", "Full"]
    assert result.data["thread"]["turns_list_fields"] == ["thread_id", "cursor", "limit"]
    assert result.data["thread"]["items_list_fields"] == ["thread_id", "turn_id", "cursor", "limit"]


def test_notifications_cover_thread_turn_item_lifecycle():
    result = AppServerRpcExtractor().extract(_snapshot(), DiagnosticCollector())
    methods = {row["method"] for row in result.data["notification_dispatch"]}
    assert {"thread/started", "thread/status/changed", "turn/started", "turn/completed", "item/started", "item/completed"} <= methods


def test_rpc_envelope_records_nonstandard_jsonrpc_wire_contract():
    result = AppServerRpcExtractor().extract(_snapshot(), DiagnosticCollector())
    assert "omits the jsonrpc=2.0 wire field" in result.data["rpc_envelope"]["dialect"]
    assert result.data["rpc_envelope"]["request_id"] == ["string", "integer"]


def test_missing_lifecycle_source_fails_closed():
    diagnostics = DiagnosticCollector()
    result = AppServerRpcExtractor().extract(_snapshot(omit="thread"), diagnostics)
    assert not result.semantic_complete
    assert result.data == {}
    assert any(item.code == "APP_SERVER_RPC_SOURCE_UNAVAILABLE" for item in diagnostics.values())


def test_turn_status_drift_is_error_not_fallback():
    diagnostics = DiagnosticCollector()
    result = AppServerRpcExtractor().extract(_snapshot(break_turn_status=True), diagnostics)
    assert not result.semantic_complete
    assert any(item.code == "APP_SERVER_TURN_STATUS_DRIFT" for item in diagnostics.values())


def test_app_server_source_identity_is_exact():
    registry = build_registry(load_legacy_modules())
    assert registry.get("source_spec.extra.app_server_common").primary_path == "codex-rs/app-server-protocol/src/protocol/common.rs"
    assert registry.get("source_spec.extra.app_server_thread").primary_path == "codex-rs/app-server-protocol/src/protocol/v2/thread.rs"
    assert registry.get("source_spec.extra.app_server_thread_data").primary_path == "codex-rs/app-server-protocol/src/protocol/v2/thread_data.rs"
    assert registry.get("source_spec.extra.app_server_turn").primary_path == "codex-rs/app-server-protocol/src/protocol/v2/turn.rs"
    assert registry.get("source_spec.extra.app_server_item").primary_path == "codex-rs/app-server-protocol/src/protocol/v2/item.rs"
    assert registry.get("source_spec.extra.app_server_rpc").primary_path == "codex-rs/app-server-protocol/src/rpc.rs"
