from __future__ import annotations

from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.extractors import create_extractors
from codex_wire_audit.extractors.history_identity import HistoryIdentityExtractor
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


def _snapshot(*, cache_affinity_revision: bool) -> SourceSnapshot:
    prompt_cache = '''
fn prompt_cache_key(&self, responses_metadata: &CodexResponsesMetadata) -> String {
    if let Some(prompt_cache_key) = &self.prompt_cache_key_override {
        return prompt_cache_key.clone();
    }
    responses_metadata.session_id.clone()
}
let prompt_cache_key = Some(self.prompt_cache_key(responses_metadata));
client_metadata: Some(responses_metadata.client_metadata()),
'''
    if cache_affinity_revision:
        core = prompt_cache + '''
// ChatGPT derives cache affinity from the Responses session-id header. Keep the
// actual session identity in turn metadata, hooks, and history/notes requests.
fn responses_session_id(&self, metadata: &CodexResponsesMetadata) -> String {
    if self.state.session_source.is_non_root_agent() {
        metadata.session_id.clone()
    } else {
        self.prompt_cache_key(metadata)
    }
}
session_id: Some(self.client.responses_session_id(responses_metadata)),
'''
    else:
        core = prompt_cache + '''
headers.extend(build_session_headers(
    Some(responses_metadata.session_id.to_string()),
    Some(responses_metadata.thread_id.to_string()),
));
session_id: Some(responses_metadata.session_id.to_string()),
'''

    session_common = '''
let thread_id = match (&initial_history, reserved_thread_id) {
    (InitialHistory::New | InitialHistory::Cleared | InitialHistory::Forked(_), None) => {
        agent_control.generate_thread_id()
    }
    (InitialHistory::Resumed(resumed_history), None) => resumed_history.conversation_id,
};
let resumed_session_id = match &initial_history {
    InitialHistory::Resumed(resumed) => resumed.history.iter().find_map(|item| match item {
        RolloutItem::SessionMeta(meta_line) => Some(meta_line.meta.session_id),
        _ => None,
    }),
    InitialHistory::New | InitialHistory::Cleared | InitialHistory::Forked(_) => None,
};
// session_id is equal to the root thread's ID.
let session_id = resumed_session_id.unwrap_or_else(|| {
    if session_configuration.session_source.is_non_root_agent() {
        agent_control.session_id()
    } else {
        SessionId::from(thread_id)
    }
});
'''
    if cache_affinity_revision:
        session = session_common + '''
// Ephemeral forks reuse cache routing, without sharing storage or lifecycle identity.
let fork_cache_key = match &initial_history {
    InitialHistory::Forked(items)
        if config.ephemeral
            && !session_configuration.session_source.is_non_root_agent() =>
    {
        items.iter().find_map(|item| match item {
            RolloutItem::SessionMeta(meta) => Some(meta.meta.session_id.to_string()),
            _ => None,
        })
    }
    InitialHistory::New
    | InitialHistory::Cleared
    | InitialHistory::Resumed(_)
    | InitialHistory::Forked(_) => None,
};
.with_session_context(review_override.or(fork_cache_key), tx_event.clone())
'''
    else:
        session = session_common + '''
.with_session_context(review_override, tx_event.clone())
'''

    rows = [
        _file("source_spec.base.core", "codex-rs/core/src/client.rs", core),
        _file(
            "source_spec.extra.responses_transport_session",
            "codex-rs/core/src/session/session.rs",
            session,
        ),
        _file(
            "source_spec.extra.app_server_thread_manager",
            "codex-rs/core/src/thread_manager.rs",
            '''
/// Fork an existing thread. The new thread will have a fresh id.
pub async fn fork_prepared_thread() {}
request.forked_from_thread_id = source_thread_id;
''',
        ),
        _file(
            "source_spec.extra.app_server_thread_processor",
            "codex-rs/app-server/src/request_processors/thread_processor.rs",
            '''
async fn thread_revert_response() {
    "thread/revert only supports paginated threads";
    reload_paginated_thread();
    if resumed_thread_id != thread_id { panic!(); }
}
''',
        ),
        _file(
            "source_spec.extra.local_storage_tui_backtrack",
            "codex-rs/tui/src/app_backtrack.rs",
            "AppEvent::ForkSessionForPromptEdit { thread_id, prompt };",
        ),
        _file(
            "source_spec.extra.local_storage_revert_thread",
            "codex-rs/thread-store/src/local/revert_thread.rs",
            '''
let forked_from_ordinal_exclusive = source_cutoff.map(|cutoff| {
    // Reverting into inherited history can shrink, but never grow, the parent prefix.
    cutoff.min(history_base.map_or(0, |base| base.end_ordinal_exclusive))
});
let rollout_id = ThreadId::new();
let mut params = RolloutRecorderParams::new(
    source_meta.id,
    source_meta.forked_from_id,
    source_meta.parent_thread_id,
);
params = params
    .with_session_id(source_meta.session_id)
    .with_rollout_id(rollout_id)
    .with_forked_from_ordinal_exclusive(forked_from_ordinal_exclusive);
state_db.replace_rollout_path_if_current(
    thread_id,
    expected_sqlite_path.as_path(),
    replacement_path.as_path(),
).await;
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


def test_new_revision_splits_ephemeral_cache_routing_from_actual_fork_identity() -> None:
    result = HistoryIdentityExtractor().extract(
        _snapshot(cache_affinity_revision=True),
        DiagnosticCollector(),
    )
    fork = result.data["fork"]

    assert fork["logical_identity"]["fresh_thread_id"]["observed"]
    assert fork["logical_identity"]["root_session_id_from_new_thread_id"]["observed"]
    assert fork["responses_routing"]["revision_mode"] == "root_cache_affinity_session_id"
    assert fork["persistent_root_fork"]["source_session_reused_as_fork_cache_key"] is False
    assert fork["persistent_root_fork"]["responses_session_id"] == (
        "new fork session_id when no unrelated prompt_cache_key override applies"
    )

    ephemeral = fork["ephemeral_root_fork"]
    assert ephemeral["cache_routing_override_observed"]
    assert ephemeral["cache_affinity_header_observed"]
    assert ephemeral["cache_key_source"] == "source SessionMeta.session_id"
    assert ephemeral["responses_session_id"] == "source SessionMeta.session_id for cache affinity"
    assert ephemeral["actual_identity_still_in_client_metadata"]

    matrix = result.data["operation_matrix"]
    assert matrix["persistent_root_fork"]["logical_session"] == "new"
    assert matrix["persistent_root_fork"]["responses_routing_session"] == "new session"
    assert matrix["ephemeral_root_fork"]["responses_routing_session"] == (
        "source session for cache affinity"
    )


def test_older_revision_keeps_responses_session_header_on_actual_session_identity() -> None:
    result = HistoryIdentityExtractor().extract(
        _snapshot(cache_affinity_revision=False),
        DiagnosticCollector(),
    )
    fork = result.data["fork"]

    assert fork["responses_routing"]["revision_mode"] == "logical_session_id"
    assert fork["responses_routing"]["legacy_actual_session_header"]["observed"]
    assert not fork["responses_routing"]["new_root_cache_affinity_header"]["observed"]
    assert not fork["ephemeral_root_fork"]["cache_routing_override_observed"]
    assert fork["ephemeral_root_fork"]["responses_session_id"] == (
        "actual fork session_id on revisions without the fork cache-routing override"
    )


def test_revert_preserves_logical_identity_but_replaces_physical_rollout() -> None:
    result = HistoryIdentityExtractor().extract(
        _snapshot(cache_affinity_revision=True),
        DiagnosticCollector(),
    )
    revert = result.data["revert"]
    storage = revert["storage_identity"]

    assert storage["logical_thread_id_preserved"]["observed"]
    assert storage["session_id_preserved"]["observed"]
    assert storage["rollout_id_replaced"]["observed"]
    assert storage["existing_thread_row_repointed"]["observed"]
    assert storage["fork_lineage_preserved"]["observed"]
    assert storage["fork_cutoff_can_shrink"]["observed"]
    assert revert["responses_after_persistent_root_revert"]["actual_thread_id"] == (
        "same logical thread_id"
    )

    matrix = result.data["operation_matrix"]["persistent_root_revert"]
    assert matrix["logical_thread"] == "preserved"
    assert matrix["logical_session"] == "preserved"
    assert matrix["physical_rollout"] == "new rollout_id"


def test_tui_prompt_edit_remains_fork_not_revert() -> None:
    result = HistoryIdentityExtractor().extract(
        _snapshot(cache_affinity_revision=True),
        DiagnosticCollector(),
    )
    rewind = result.data["fork"]["tui_prompt_edit_rewind"]["uses_fork"]
    assert rewind["observed"]
    assert rewind["operation"] == "thread/fork"


def test_history_identity_extractor_is_registered() -> None:
    ids = {extractor.extractor_id for extractor in create_extractors()}
    assert "extractor.history_identity" in ids
