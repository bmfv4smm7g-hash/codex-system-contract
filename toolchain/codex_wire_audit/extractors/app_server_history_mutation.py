"""Deterministic app-server history mutation semantics."""
from __future__ import annotations

from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile

APP_SERVER_THREAD_PROCESSOR = "source_spec.extra.app_server_thread_processor"
THREAD_MANAGER = "source_spec.extra.app_server_thread_manager"
TUI_APP_SERVER_SESSION = "source_spec.extra.app_server_tui_session"
TUI_BACKTRACK = "source_spec.extra.local_storage_tui_backtrack"
STORAGE_PAGINATED_FORK = "source_spec.extra.local_storage_paginated_fork"
STORAGE_REVERT = "source_spec.extra.local_storage_revert_thread"


def _require(
    diagnostics: DiagnosticCollector,
    *,
    extractor_id: str,
    source: SourceFile,
    entity: str,
    tokens: tuple[tuple[str, str], ...],
) -> bool:
    complete = True
    for code, token in tokens:
        if token in source.text:
            continue
        complete = False
        diagnostics.emit(
            code=code,
            severity="error",
            category="app_server_rpc",
            message=f"Required history-mutation evidence is missing: {token}",
            extractor_id=extractor_id,
            entity_id=entity,
            source_refs=[source.spec_id],
            details={"path": source.selected_path, "token": token},
            recoverable=False,
            strict_failure=True,
        )
    return complete


def validate_history_mutation_sources(
    *,
    diagnostics: DiagnosticCollector,
    extractor_id: str,
    processor: SourceFile,
    thread_manager: SourceFile,
    tui_session: SourceFile,
    tui_backtrack: SourceFile,
    storage_fork: SourceFile,
    storage_revert: SourceFile,
) -> bool:
    complete = _require(
        diagnostics,
        extractor_id=extractor_id,
        source=processor,
        entity="app_server_rpc.history_mutation.orchestration",
        tokens=(
            ("APP_SERVER_FORK_HANDLER_MISSING", "async fn thread_fork_inner"),
            ("APP_SERVER_FORK_PAGINATED_GATE_MISSING", "let paginated_source = matches!(source_thread.history_mode, ThreadHistoryMode::Paginated)"),
            ("APP_SERVER_FORK_PREPARE_MISSING", ".prepare_fork(codex_thread_store::PrepareForkParams"),
            ("APP_SERVER_FORK_PREPARED_START_MISSING", ".fork_prepared_thread("),
            ("APP_SERVER_FORK_STARTED_NOTIFICATION_MISSING", "ServerNotification::ThreadStarted(notif)"),
            ("APP_SERVER_REVERT_HANDLER_MISSING", "async fn thread_revert_response"),
            ("APP_SERVER_REVERT_PAGINATED_ONLY_MISSING", '"thread/revert only supports paginated threads"'),
            ("APP_SERVER_REVERT_SHUTDOWN_MISSING", "wait_for_thread_shutdown(&thread).await"),
            ("APP_SERVER_REVERT_REMOVE_LOADED_MISSING", ".remove_thread(&thread_id)"),
            ("APP_SERVER_REVERT_STORE_CALL_MISSING", ".revert_thread(codex_thread_store::RevertThreadParams"),
            ("APP_SERVER_REVERT_RELOAD_MISSING", "async fn reload_paginated_thread"),
            ("APP_SERVER_REVERT_IDENTITY_GUARD_MISSING", "if resumed_thread_id != thread_id"),
            ("APP_SERVER_REVERT_SUBSCRIPTION_PRESERVE_MISSING", "Keep thread state and subscriptions across the internal reload"),
            ("APP_SERVER_REVERT_NOTIFICATION_MISSING", "ServerNotification::ThreadReverted("),
        ),
    )
    complete &= _require(
        diagnostics,
        extractor_id=extractor_id,
        source=thread_manager,
        entity="app_server_rpc.history_mutation.fork_identity",
        tokens=(
            ("APP_SERVER_FORK_FRESH_ID_MISSING", "The new thread will have"),
            ("APP_SERVER_FORK_FRESH_ID_SUFFIX_MISSING", "a fresh id."),
            ("APP_SERVER_PREPARED_FORK_ENTRY_MISSING", "pub async fn fork_prepared_thread"),
            ("APP_SERVER_PREPARED_FORK_SOURCE_ID_MISSING", "conversation_id: prepared.source_thread_id"),
            ("APP_SERVER_FORK_RELATION_MISSING", "request.forked_from_thread_id = source_thread_id;"),
        ),
    )
    complete &= _require(
        diagnostics,
        extractor_id=extractor_id,
        source=tui_session,
        entity="app_server_rpc.history_mutation.tui",
        tokens=(
            ("APP_SERVER_TUI_FORK_AT_MISSING", "pub(crate) async fn fork_thread_at"),
            ("APP_SERVER_TUI_FORK_PARAMS_MISSING", "let mut params = ThreadForkParams"),
            ("APP_SERVER_TUI_FORK_RPC_MISSING", "ClientRequest::ThreadFork"),
            ("APP_SERVER_TUI_FORK_BOUNDARY_MISSING", "before_turn_id,"),
            ("APP_SERVER_TUI_PAGINATED_EXCLUDE_TURNS_MISSING", "ThreadHistorySupport::Paginated"),
        ),
    )
    complete &= _require(
        diagnostics,
        extractor_id=extractor_id,
        source=tui_backtrack,
        entity="app_server_rpc.history_mutation.tui",
        tokens=(
            ("APP_SERVER_TUI_SOURCE_PRESERVING_BRANCH_MISSING", "source-preserving branch"),
            ("APP_SERVER_TUI_PROMPT_EDIT_FORK_MISSING", "ForkSessionForPromptEdit"),
            ("APP_SERVER_TUI_STEER_BOUNDARY_MISSING", "app-server cannot fork in the middle of a turn"),
        ),
    )
    complete &= _require(
        diagnostics,
        extractor_id=extractor_id,
        source=storage_fork,
        entity="app_server_rpc.history_mutation.storage_bridge",
        tokens=(
            ("APP_SERVER_PAGINATED_FORK_BOUNDARY_LATEST_MISSING", "ForkBoundary::Latest"),
            ("APP_SERVER_PAGINATED_FORK_BOUNDARY_THROUGH_MISSING", "ForkBoundary::ThroughTurn"),
            ("APP_SERVER_PAGINATED_FORK_BOUNDARY_BEFORE_MISSING", "ForkBoundary::BeforeTurn"),
            ("APP_SERVER_PAGINATED_FORK_HISTORY_POSITION_MISSING", "HistoryPosition"),
            ("APP_SERVER_PAGINATED_FORK_HISTORY_BASE_MISSING", "history_base_at_boundary"),
        ),
    )
    complete &= _require(
        diagnostics,
        extractor_id=extractor_id,
        source=storage_revert,
        entity="app_server_rpc.history_mutation.storage_bridge",
        tokens=(
            ("APP_SERVER_REVERT_NEW_ROLLOUT_ID_MISSING", "let rollout_id = ThreadId::new();"),
            ("APP_SERVER_REVERT_ROLLOUT_OVERRIDE_MISSING", ".with_rollout_id(rollout_id)"),
            ("APP_SERVER_REVERT_STABLE_THREAD_RECORDER_MISSING", "RolloutRecorderParams::new("),
            ("APP_SERVER_REVERT_STABLE_THREAD_ID_MISSING", "source_meta.id,"),
            ("APP_SERVER_REVERT_POINTER_CAS_MISSING", ".replace_rollout_path_if_current("),
        ),
    )
    return complete


def build_history_mutation() -> dict[str, Any]:
    return {
        "fork": {
            "rpc": "thread/fork",
            "logical_identity": "new thread_id",
            "source_thread_preserved": True,
            "source_relation": "new thread forked_from_id references source thread_id",
            "boundaries": {
                "latest": "ForkBoundary::Latest",
                "lastTurnId": "ForkBoundary::ThroughTurn; referenced completed turn is included",
                "beforeTurnId": "ForkBoundary::BeforeTurn; referenced turn and all later turns are excluded",
                "last_and_before_mutually_exclusive": True,
            },
            "paginated_source": {
                "preparation": "thread_store.prepare_fork computes immutable source HistoryPosition/history_base",
                "model_context": "loaded from source lineage through the prepared history_base",
                "new_runtime": "thread_manager.fork_prepared_thread starts the new logical thread",
                "full_history_hydration": "optional compatibility response path; excludeTurns avoids eager hydration",
            },
            "legacy_source": "forks from reconstructed/truncated source history rather than PreparedFork",
            "notification": "thread/started",
        },
        "revert": {
            "rpc": "thread/revert",
            "logical_identity": "preserved thread_id",
            "supported_history_mode": "Paginated",
            "boundary": "beforeTurnId excludes the referenced turn and every later turn",
            "local_file_changes_reverted": False,
            "loaded_thread_orchestration": [
                "ensure listener and register shutdown drain waiter",
                "shut down loaded runtime and drain shutdown events",
                "remove runtime from ThreadManager",
                "preserve app-server thread state/subscriptions while cancelling pending requests",
                "delegate durable replacement to thread_store.revert_thread",
                "reload the same logical thread from the replacement rollout",
                "restore runtime settings and restart the listener",
            ],
            "storage_bridge": {
                "replacement_rollout_id": "new UUID",
                "logical_thread_id": "preserved",
                "replacement_identity": "stable logical thread_id plus new rollout_id",
                "physical_layout_owner": "extractor.local_storage",
                "state_cutover": "compare-and-swap the existing thread row's rollout_path",
                "new_thread_row": False,
            },
            "notification": "thread/reverted",
        },
        "tui_prompt_edit_policy": {
            "operation": "thread/fork",
            "boundary": "beforeTurnId for the selected initial prompt's turn",
            "source_preserving": True,
            "steer_is_independent_branch_boundary": False,
            "uses_thread_revert": False,
        },
        "desktop_observation_classifier": {
            "public_source_claim": "Desktop host choice is not determined by public Codex source; classify an observation by public fork/revert signatures instead of assuming the host route",
            "revert_signature": "same thread.id; thread/reverted; storage-selected replacement whose parsed logical thread_id remains A while rollout_id changes",
            "fork_signature": "new thread.id B; forked_from_id=A; thread/started; source A remains independently addressable",
        },
    }
