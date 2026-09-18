"""Source-derived fork/revert identity and Responses routing semantics.

This extractor keeps three concepts separate:
- logical thread/session identity,
- physical rollout/history identity,
- Responses cache/routing identity.

The distinction is revision-sensitive. Older Codex revisions send the logical
session_id directly on Responses requests; newer revisions may override the
root Responses session-id/prompt_cache_key for ephemeral forks while preserving
actual session identity in metadata.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile, SourceSnapshot
from .registry import ExtractorResult, register_extractor


EXTRACTOR_ID = "extractor.history_identity"
SCHEMA_VERSION = "1.0.0"

CORE = "source_spec.base.core"
SESSION = "source_spec.extra.responses_transport_session"
THREAD_MANAGER = "source_spec.extra.app_server_thread_manager"
THREAD_PROCESSOR = "source_spec.extra.app_server_thread_processor"
TUI_BACKTRACK = "source_spec.extra.local_storage_tui_backtrack"
STORAGE_REVERT = "source_spec.extra.local_storage_revert_thread"

SOURCE_IDS = (
    CORE,
    SESSION,
    THREAD_MANAGER,
    THREAD_PROCESSOR,
    TUI_BACKTRACK,
    STORAGE_REVERT,
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


def _responses_identity_mode(core: SourceFile | None) -> str:
    if _observed(
        core,
        "fn responses_session_id",
        "self.prompt_cache_key(metadata)",
        "ChatGPT derives cache affinity from the Responses session-id header",
    ):
        return "root_cache_affinity_session_id"
    if _observed(
        core,
        "session_id: Some(responses_metadata.session_id.to_string())",
        "Some(responses_metadata.session_id.to_string())",
    ):
        return "logical_session_id"
    return "unknown"


def _fork_identity(
    core: SourceFile | None,
    session: SourceFile | None,
    thread_manager: SourceFile | None,
    tui_backtrack: SourceFile | None,
) -> dict[str, Any]:
    ephemeral_cache_override = _observed(
        session,
        "Ephemeral forks reuse cache routing, without sharing storage or lifecycle identity.",
        "let fork_cache_key = match &initial_history",
        "if config.ephemeral",
        "!session_configuration.session_source.is_non_root_agent()",
        "RolloutItem::SessionMeta(meta) => Some(meta.meta.session_id.to_string())",
        ".or(fork_cache_key)",
    )
    cache_affinity_header = _observed(
        core,
        "fn responses_session_id",
        "self.prompt_cache_key(metadata)",
        "ChatGPT derives cache affinity from the Responses session-id header",
    )
    prompt_cache_override = _observed(
        core,
        "if let Some(prompt_cache_key) = &self.prompt_cache_key_override",
        "return prompt_cache_key.clone();",
        "responses_metadata.session_id.clone()",
    )
    body_prompt_cache_key = _observed(
        core,
        "let prompt_cache_key = Some(self.prompt_cache_key(responses_metadata));",
        "client_metadata: Some(responses_metadata.client_metadata())",
    )
    root_identity = _observed(
        session,
        "InitialHistory::New | InitialHistory::Cleared | InitialHistory::Forked(_) => None",
        "session_id is equal to the root thread's ID.",
        "SessionId::from(thread_id)",
    )
    fresh_thread = _observed(thread_manager, "fresh id", "fork_prepared_thread")
    fork_lineage = _observed(thread_manager, "forked_from_thread_id")

    return {
        "operation": "thread/fork",
        "logical_identity": {
            "fresh_thread_id": {
                "observed": fresh_thread,
                "source_semantics": "fork allocates a new logical thread identity",
            },
            "root_session_id_from_new_thread_id": {
                "observed": root_identity,
                "source_semantics": "Forked history does not resume an old session_id; a root session_id is derived from the new thread_id",
            },
            "lineage_is_separate_from_identity": {
                "observed": fork_lineage,
                "source_semantics": "source identity is carried as forked_from_thread_id instead of replacing the new fork identity",
                "field": "forked_from_thread_id",
            },
        },
        "responses_routing": {
            "revision_mode": _responses_identity_mode(core),
            "prompt_cache_key_override_priority": _rule(
                core,
                tokens=(
                    "if let Some(prompt_cache_key) = &self.prompt_cache_key_override",
                    "return prompt_cache_key.clone();",
                    "responses_metadata.session_id.clone()",
                ),
                source_semantics="prompt_cache_key override wins; otherwise ordinary root/user requests fall back to the actual Responses metadata session_id",
            ),
            "new_root_cache_affinity_header": _rule(
                core,
                tokens=(
                    "ChatGPT derives cache affinity from the Responses session-id header",
                    "fn responses_session_id",
                    "self.prompt_cache_key(metadata)",
                ),
                source_semantics="newer root Responses requests derive the session-id routing header from prompt-cache identity while retaining actual identity elsewhere",
            ),
            "legacy_actual_session_header": _rule(
                core,
                tokens=(
                    "session_id: Some(responses_metadata.session_id.to_string())",
                    "Some(responses_metadata.session_id.to_string())",
                ),
                source_semantics="older Responses request and WebSocket header paths send the actual metadata session_id directly",
            ),
            "body_prompt_cache_key": _rule(
                core,
                tokens=(
                    "let prompt_cache_key = Some(self.prompt_cache_key(responses_metadata));",
                    "client_metadata: Some(responses_metadata.client_metadata())",
                ),
                source_semantics="Responses body carries prompt_cache_key while client_metadata retains the separately derived metadata identity",
            ),
        },
        "persistent_root_fork": {
            "observed": root_identity and fresh_thread and fork_lineage and prompt_cache_override,
            "actual_thread_id": "new fork thread_id",
            "actual_session_id": "new fork session_id equal to the new root thread_id",
            "source_identity": "forked_from_thread_id",
            "source_session_reused_as_fork_cache_key": False,
            "responses_session_id": "new fork session_id when no unrelated prompt_cache_key override applies",
            "body_prompt_cache_key": "new fork session_id when no unrelated prompt_cache_key override applies",
            "source_semantics": "durable/root fork has a new logical identity; the ephemeral-only fork_cache_key guard does not apply",
        },
        "ephemeral_root_fork": {
            "cache_routing_override_observed": ephemeral_cache_override,
            "cache_affinity_header_observed": cache_affinity_header,
            "body_prompt_cache_key_observed": body_prompt_cache_key,
            "actual_thread_id": "new fork thread_id",
            "actual_session_id": "new fork session_id equal to the new root thread_id",
            "cache_key_source": "source SessionMeta.session_id" if ephemeral_cache_override else None,
            "responses_session_id": (
                "source SessionMeta.session_id for cache affinity"
                if ephemeral_cache_override and cache_affinity_header
                else "actual fork session_id on revisions without the fork cache-routing override"
            ),
            "body_prompt_cache_key": (
                "source SessionMeta.session_id"
                if ephemeral_cache_override and body_prompt_cache_key
                else "actual fork session_id unless another override applies"
            ),
            "actual_identity_still_in_client_metadata": body_prompt_cache_key,
            "source_semantics": "ephemeral root fork may reuse source cache routing without sharing storage or lifecycle identity",
        },
        "tui_prompt_edit_rewind": {
            "uses_fork": _rule(
                tui_backtrack,
                tokens=("ForkSessionForPromptEdit",),
                source_semantics="TUI prompt-edit/backtrack creates a fork rather than invoking thread/revert",
                operation="thread/fork",
            ),
        },
    }


def _revert_identity(
    core: SourceFile | None,
    session: SourceFile | None,
    processor: SourceFile | None,
    storage: SourceFile | None,
) -> dict[str, Any]:
    logical_thread_preserved = _observed(
        storage,
        "source_meta.id",
        "replace_rollout_path_if_current(",
    )
    session_preserved = _observed(storage, ".with_session_id(source_meta.session_id)")
    rollout_replaced = _observed(
        storage,
        "let rollout_id = ThreadId::new();",
        ".with_rollout_id(rollout_id)",
        "replace_rollout_path_if_current(",
    )
    lineage_preserved = _observed(
        storage,
        "source_meta.forked_from_id",
        ".with_forked_from_ordinal_exclusive(forked_from_ordinal_exclusive)",
    )
    fork_cutoff_shrink = _observed(
        storage,
        "Reverting into inherited history can shrink, but never grow, the parent prefix.",
        "cutoff.min(history_base.map_or(0, |base| base.end_ordinal_exclusive))",
    )
    resumed_has_no_fork_cache_key = _observed(
        session,
        "InitialHistory::Resumed(_)\n            | InitialHistory::Forked(_) => None",
    ) or _observed(
        session,
        "InitialHistory::Resumed(_)",
        "| InitialHistory::Forked(_) => None",
        "let fork_cache_key = match &initial_history",
    )
    prompt_cache_fallback = _observed(
        core,
        "responses_metadata.session_id.clone()",
        "fn prompt_cache_key",
    )

    return {
        "operation": "thread/revert",
        "app_server": {
            "paginated_only": _rule(
                processor,
                tokens=("thread/revert only supports paginated threads",),
                source_semantics="app-server revert operates on paginated history",
            ),
            "reload_same_logical_thread": _rule(
                processor,
                tokens=("reload_paginated_thread", "resumed_thread_id != thread_id"),
                source_semantics="revert reload checks that resumed identity matches the requested logical thread_id",
            ),
        },
        "storage_identity": {
            "logical_thread_id_preserved": {
                "observed": logical_thread_preserved,
                "value": "source_meta.id / existing thread_id",
            },
            "session_id_preserved": {
                "observed": session_preserved,
                "value": "source_meta.session_id",
            },
            "rollout_id_replaced": {
                "observed": rollout_replaced,
                "value": "new ThreadId UUID used as physical rollout_id",
            },
            "existing_thread_row_repointed": {
                "observed": rollout_replaced,
                "source_semantics": "replace_rollout_path_if_current repoints the existing logical thread instead of creating a fork thread row",
            },
            "fork_lineage_preserved": {
                "observed": lineage_preserved,
                "source_semantics": "existing forked_from_id is retained and the ordinal cutoff is carried into the replacement rollout",
            },
            "fork_cutoff_can_shrink": {
                "observed": fork_cutoff_shrink,
                "source_semantics": "reverting into inherited parent history can reduce but never increase forked_from_ordinal_exclusive",
            },
        },
        "responses_after_persistent_root_revert": {
            "observed": logical_thread_preserved and session_preserved and prompt_cache_fallback,
            "actual_thread_id": "same logical thread_id",
            "actual_session_id": "same source_meta.session_id",
            "physical_rollout_id": "new rollout_id",
            "fork_cache_key_created_by_revert": False,
            "resumed_history_excluded_from_ephemeral_fork_cache_override": resumed_has_no_fork_cache_key,
            "responses_session_id": "same logical session_id unless another independent prompt_cache_key override applies",
            "body_prompt_cache_key": "same logical session_id unless another independent prompt_cache_key override applies",
        },
    }


def _operation_matrix(fork: dict[str, Any], revert: dict[str, Any]) -> dict[str, Any]:
    return {
        "persistent_root_fork": {
            "logical_thread": "new",
            "logical_session": "new",
            "physical_rollout": "new fork rollout",
            "responses_routing_session": "new session",
            "lineage": "forked_from_thread_id points to source",
            "observed": fork["persistent_root_fork"]["observed"],
        },
        "ephemeral_root_fork": {
            "logical_thread": "new",
            "logical_session": "new",
            "physical_rollout": "ephemeral/no durable thread metadata reservation",
            "responses_routing_session": (
                "source session for cache affinity"
                if fork["ephemeral_root_fork"]["cache_routing_override_observed"]
                and fork["ephemeral_root_fork"]["cache_affinity_header_observed"]
                else "new session on revisions without cache-routing override"
            ),
            "lineage": "forked_from_thread_id points to source",
            "observed": fork["logical_identity"]["fresh_thread_id"]["observed"],
        },
        "persistent_root_revert": {
            "logical_thread": "preserved",
            "logical_session": "preserved",
            "physical_rollout": "new rollout_id",
            "responses_routing_session": "preserved session",
            "lineage": "existing fork lineage retained; cutoff may shrink",
            "observed": revert["responses_after_persistent_root_revert"]["observed"],
        },
    }


class HistoryIdentityExtractor:
    extractor_id = EXTRACTOR_ID
    source_spec_ids = SOURCE_IDS

    def extract(
        self,
        snapshot: SourceSnapshot,
        diagnostics: DiagnosticCollector,
    ) -> ExtractorResult:
        del diagnostics  # Optional revision evidence is represented explicitly via observed=false.
        sources = {source_id: snapshot.files.get(source_id) for source_id in SOURCE_IDS}
        available = sorted(source_id for source_id, source in sources.items() if source is not None)
        missing = sorted(source_id for source_id, source in sources.items() if source is None)

        fork = _fork_identity(
            sources[CORE],
            sources[SESSION],
            sources[THREAD_MANAGER],
            sources[TUI_BACKTRACK],
        )
        revert = _revert_identity(
            sources[CORE],
            sources[SESSION],
            sources[THREAD_PROCESSOR],
            sources[STORAGE_REVERT],
        )
        body: dict[str, Any] = {
            "ownership": {
                "owns": [
                    "revision-sensitive fork/revert logical session and thread identity",
                    "physical rollout identity changes across revert",
                    "root Responses cache/routing identity versus actual session identity",
                ],
                "does_not_own": [
                    "generic thread/fork presentation and persistence UX",
                    "generic Responses transport lifecycle",
                    "server-side cache implementation",
                    "turn metadata field schema",
                ],
            },
            "coverage": {
                "available_source_spec_ids": available,
                "missing_source_spec_ids": missing,
                "mode": "source-pattern classification; revision-specific behavior remains observed=false when absent",
            },
            "fork": fork,
            "revert": revert,
            "operation_matrix": _operation_matrix(fork, revert),
            "evidence": {
                source_id: _evidence(source, "history identity observation")
                for source_id, source in sorted(sources.items())
                if source is not None
            },
        }
        body["semantic_digest"] = hashlib.sha256(_canonical(body)).hexdigest()
        return ExtractorResult(
            extractor_id=EXTRACTOR_ID,
            schema_version=SCHEMA_VERSION,
            data=body,
            semantic_complete=True,
            source_spec_ids=SOURCE_IDS,
        )


@register_extractor(EXTRACTOR_ID)
def _history_identity_factory() -> HistoryIdentityExtractor:
    return HistoryIdentityExtractor()
