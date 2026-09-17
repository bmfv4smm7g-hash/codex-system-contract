"""Source-derived app-server history mutation semantics."""
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


def _has(source: SourceFile, *tokens: str) -> bool:
    return all(token in source.text for token in tokens)


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


def build_history_mutation(
    *,
    processor: SourceFile,
    thread_manager: SourceFile,
    tui_session: SourceFile,
    tui_backtrack: SourceFile,
    storage_fork: SourceFile,
    storage_revert: SourceFile,
) -> dict[str, Any]:
    """Build the public mutation contract only from source predicates already validated.

    The strings below are normalized semantic labels. Their presence and boolean
    values are gated by the source expressions that establish each behavior.
    """

    fork_fresh_id = _has(
        thread_manager,
        "The new thread will have",
        "a fresh id.",
        "pub async fn fork_prepared_thread",
    )
    fork_relation = _has(
        thread_manager,
        "conversation_id: prepared.source_thread_id",
        "request.forked_from_thread_id = source_thread_id;",
    )
    latest_boundary = _has(storage_fork, "ForkBoundary::Latest")
    through_boundary = _has(storage_fork, "ForkBoundary::ThroughTurn")
    before_boundary = _has(storage_fork, "ForkBoundary::BeforeTurn")
    prepared_history_base = _has(storage_fork, "HistoryPosition", "history_base_at_boundary")
    paginated_fork = _has(
        processor,
        "let paginated_source = matches!(source_thread.history_mode, ThreadHistoryMode::Paginated)",
        ".prepare_fork(codex_thread_store::PrepareForkParams",
        ".fork_prepared_thread(",
    )
    fork_notification = _has(processor, "ServerNotification::ThreadStarted(notif)")

    revert_paginated_only = _has(
        processor,
        '"thread/revert only supports paginated threads"',
    )
    revert_preserves_thread_id = _has(
        processor,
        "async fn reload_paginated_thread",
        "if resumed_thread_id != thread_id",
    ) and _has(
        storage_revert,
        "RolloutRecorderParams::new(",
        "source_meta.id,",
    )
    revert_new_rollout = _has(
        storage_revert,
        "let rollout_id = ThreadId::new();",
        ".with_rollout_id(rollout_id)",
    )
    revert_pointer_cutover = _has(storage_revert, ".replace_rollout_path_if_current(")
    revert_orchestration = [
        label
        for present, label in (
            (_has(processor, "wait_for_thread_shutdown(&thread).await"), "shut down loaded runtime and drain shutdown events"),
            (_has(processor, ".remove_thread(&thread_id)"), "remove runtime from ThreadManager"),
            (_has(processor, "Keep thread state and subscriptions across the internal reload"), "preserve app-server thread state/subscriptions while cancelling pending requests"),
            (_has(processor, ".revert_thread(codex_thread_store::RevertThreadParams"), "delegate durable replacement to thread_store.revert_thread"),
            (_has(processor, "async fn reload_paginated_thread"), "reload the same logical thread from the replacement rollout"),
        )
        if present
    ]
    revert_notification = _has(processor, "ServerNotification::ThreadReverted(")

    prompt_edit_fork = _has(
        tui_session,
        "pub(crate) async fn fork_thread_at",
        "ClientRequest::ThreadFork",
        "before_turn_id,",
    ) and _has(
        tui_backtrack,
        "source-preserving branch",
        "ForkSessionForPromptEdit",
    )
    steer_not_boundary = _has(tui_backtrack, "app-server cannot fork in the middle of a turn")

    return {
        "fork": {
            "rpc": "thread/fork",
            "logical_identity": "new thread_id" if fork_fresh_id else "unresolved",
            "source_thread_preserved": fork_fresh_id and fork_relation,
            "source_relation": (
                "new thread forked_from_id references source thread_id"
                if fork_relation
                else "unresolved"
            ),
            "boundaries": {
                "latest": "ForkBoundary::Latest" if latest_boundary else None,
                "lastTurnId": (
                    "ForkBoundary::ThroughTurn; referenced completed turn is included"
                    if through_boundary
                    else None
                ),
                "beforeTurnId": (
                    "ForkBoundary::BeforeTurn; referenced turn and all later turns are excluded"
                    if before_boundary
                    else None
                ),
                "last_and_before_mutually_exclusive": through_boundary and before_boundary,
            },
            "paginated_source": {
                "preparation": (
                    "thread_store.prepare_fork computes immutable source HistoryPosition/history_base"
                    if paginated_fork and prepared_history_base
                    else None
                ),
                "model_context": (
                    "loaded from source lineage through the prepared history_base"
                    if prepared_history_base
                    else None
                ),
                "new_runtime": (
                    "thread_manager.fork_prepared_thread starts the new logical thread"
                    if paginated_fork
                    else None
                ),
                "full_history_hydration": (
                    "excludeTurns can avoid eager compatibility hydration"
                    if _has(tui_session, "ThreadHistorySupport::Paginated")
                    else None
                ),
            },
            "legacy_source": (
                "separate non-PreparedFork path exists"
                if _has(processor, "paginated_source")
                else "unresolved"
            ),
            "notification": "thread/started" if fork_notification else None,
        },
        "revert": {
            "rpc": "thread/revert",
            "logical_identity": "preserved thread_id" if revert_preserves_thread_id else "unresolved",
            "supported_history_mode": "Paginated" if revert_paginated_only else "unresolved",
            "boundary": (
                "beforeTurnId excludes the referenced turn and every later turn"
                if _has(processor, "before_turn_id")
                else "unresolved"
            ),
            "local_file_changes_reverted": False,
            "loaded_thread_orchestration": revert_orchestration,
            "storage_bridge": {
                "replacement_rollout_id": "new UUID" if revert_new_rollout else "unresolved",
                "logical_thread_id": "preserved" if revert_preserves_thread_id else "unresolved",
                "replacement_identity": (
                    "stable logical thread_id plus new rollout_id"
                    if revert_preserves_thread_id and revert_new_rollout
                    else "unresolved"
                ),
                "physical_layout_owner": "extractor.local_storage",
                "state_cutover": (
                    "compare-and-swap the existing thread row's rollout_path"
                    if revert_pointer_cutover
                    else "unresolved"
                ),
                "new_thread_row": False,
            },
            "notification": "thread/reverted" if revert_notification else None,
        },
        "tui_prompt_edit_policy": {
            "operation": "thread/fork" if prompt_edit_fork else "unresolved",
            "boundary": (
                "beforeTurnId for the selected initial prompt's turn"
                if prompt_edit_fork
                else "unresolved"
            ),
            "source_preserving": prompt_edit_fork,
            "steer_is_independent_branch_boundary": not steer_not_boundary,
            "uses_thread_revert": False,
        },
        "desktop_observation_classifier": {
            "public_source_claim": "Desktop host choice is not determined by public Codex source; classify an observation by public fork/revert signatures instead of assuming the host route",
            "revert_signature": (
                "same thread.id; thread/reverted; replacement rollout_id changes while logical thread_id remains stable"
                if revert_preserves_thread_id and revert_new_rollout and revert_notification
                else "unresolved"
            ),
            "fork_signature": (
                "new thread.id B; forked_from_id=A; thread/started; source A remains independently addressable"
                if fork_fresh_id and fork_relation and fork_notification
                else "unresolved"
            ),
        },
        "source_predicates": {
            "fork_fresh_id": fork_fresh_id,
            "fork_relation": fork_relation,
            "paginated_fork": paginated_fork,
            "prepared_history_base": prepared_history_base,
            "revert_paginated_only": revert_paginated_only,
            "revert_preserves_thread_id": revert_preserves_thread_id,
            "revert_new_rollout": revert_new_rollout,
            "revert_pointer_cutover": revert_pointer_cutover,
            "prompt_edit_fork": prompt_edit_fork,
        },
    }
