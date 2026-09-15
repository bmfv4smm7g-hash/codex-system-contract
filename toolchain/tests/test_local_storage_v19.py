from __future__ import annotations
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.extractors import create_extractors
from codex_wire_audit.extractors.local_storage import LocalStorageExtractor, SOURCE_IDS
from codex_wire_audit.models import SourceFile, SourceGroup, SourceRevision, SourceSnapshot, SourceSpec
from codex_wire_audit.source_registry import from_legacy_maps
SOURCE_TEXTS = {'home_dir': '\n        /// specified by CODEX_HOME; otherwise ~/.codex.\n        let codex_home_env = std::env::var("CODEX_HOME");\n        p.push(".codex");\n    ', 'thread_types': '\n        /// Session id shared by the root thread and all of its subagents.\n        pub session_id: SessionId,\n        pub thread_id: ThreadId,\n        /// Stable logical thread to revert.\n    ', 'rollout_lib': '\n        pub const SESSIONS_SUBDIR: &str = "sessions";\n        pub const ARCHIVED_SESSIONS_SUBDIR: &str = "archived_sessions";\n    ', 'rollout_filename': '\n        let (thread_id, rollout_id) = ids.split_once(\'_\').unwrap_or((ids, ids));\n        if self.thread_id == self.rollout_id { ordinary() }\n        format!("rollout-{timestamp}-{}_{}.jsonl", self.thread_id, self.rollout_id)\n    ', 'rollout_recorder': '\n        rollout_id_override: Option<RolloutId>,\n        pub fn with_session_id(self, session_id: SessionId) -> Self { self }\n        pub fn with_rollout_id(self, rollout_id: RolloutId) -> Self { self }\n        let rollout_id = rollout_id_override.unwrap_or(thread_id);\n        let timestamp = OffsetDateTime::now_local();\n        dir.push(SESSIONS_SUBDIR);\n        let session_meta = SessionMeta {\n            session_id,\n            id: conversation_id,\n        };\n        Self::Resume { path }\n    ', 'rollout_compression': '\n        const COMPRESSED_SUFFIX: &str = ".zst";\n        let plain_file_name = parse_rollout_file_name(name);\n    ', 'session_index': '\n        const SESSION_INDEX_FILE: &str = "session_index.jsonl";\n        pub struct SessionIndexEntry { pub id: ThreadId }\n        /// Name updates are append-only; the most recent entry wins.\n    ', 'revert_thread': '\n        /// Revert by creating a new immutable rollout file.\n        /// Old rollouts stay intact.\n        if source_meta.history_mode != ThreadHistoryMode::Paginated { reject(); }\n        let rollout_id = ThreadId::new();\n        RolloutRecorderParams::new(\n            source_meta.id,\n            source_meta.forked_from_id,\n            source_meta.parent_thread_id,\n        )\n        .with_session_id(source_meta.session_id)\n        .with_rollout_id(rollout_id);\n        state_db.replace_rollout_path_if_current(\n            thread_id,\n            expected_sqlite_path,\n            replacement_path,\n        );\n    ', 'paginated_fork': '\n        resolve_rollout_lineage_for_reference(thread_id);\n        materialize_to_sqlite(store, rollout_id, path);\n        let position = HistoryPosition {\n            thread_id: rollout_id,\n            end_ordinal_exclusive,\n            end_byte_offset,\n        };\n    ', 'archive_thread': '\n        use codex_rollout::ARCHIVED_SESSIONS_SUBDIR;\n        let destination = archive_folder.join(&file_name);\n        std::fs::rename(source, destination);\n        ctx.mark_archived(thread_id, archived_path, now);\n    ', 'unarchive_thread': '\n        let parts = rollout_date_parts(&file_name);\n        let destination = codex_home.join(SESSIONS_SUBDIR);\n        std::fs::rename(source, destination);\n        ctx.mark_unarchived(thread_id, restored_path);\n    ', 'delete_thread': '\n        let index = RolloutReferenceIndex::scan(codex_home);\n        "cannot delete thread: forked history still references it";\n        remove_thread_name_entries(codex_home, thread_id);\n    ', 'writer_lock': '\n        const WRITER_LOCK_DIR: &str = "thread-writer-locks";\n        const COORDINATION_LOCK_FILE: &str = ".coordination.lock";\n        let path = directory.join(format!("{thread_id}.lock"));\n        file.try_lock();\n    ', 'state_sqlite': '\n        const LOGS_DB_FILENAME: &str = "logs_2.sqlite";\n        const GOALS_DB_FILENAME: &str = "goals_1.sqlite";\n        const MEMORIES_DB_FILENAME: &str = "memories_1.sqlite";\n        const QUEUE_DB_FILENAME: &str = "queue_1.sqlite";\n        const STATE_DB_FILENAME: &str = "state_5.sqlite";\n        const THREAD_HISTORY_DB_FILENAME: &str = "thread_history_1.sqlite";\n        const RUNTIME_DBS: [RuntimeDbSpec; 6] = [];\n        options\n            .journal_mode(SqliteJournalMode::Wal)\n            .synchronous(SqliteSynchronous::Normal)\n            .auto_vacuum(SqliteAutoVacuum::Incremental)\n            .busy_timeout(Duration::from_secs(5));\n        SqlitePoolOptions::new().max_connections(5);\n    ', 'state_threads': '\n        /// Only the physical rollout path changes; logical metadata remains\n        /// attached to the stable thread id.\n        sqlx::query("UPDATE threads SET rollout_path = ? WHERE id = ? AND rollout_path = ?");\n    ', 'threads_migration': '\n        CREATE TABLE threads (\n            id TEXT PRIMARY KEY,\n            rollout_path TEXT NOT NULL,\n            created_at INTEGER NOT NULL\n        );\n    ', 'history_materialization': '\n        pub(super) async fn materialize_to_sqlite() {\n            let initial_ordinal = session_meta\n                .history_base\n                .map_or(0, |base| base.end_ordinal_exclusive);\n            apply_projection(store, thread_id);\n        }\n    ', 'shell_snapshot': '\n        const SNAPSHOT_RETENTION: Duration = Duration::from_secs(60 * 60 * 24 * 3);\n        const SNAPSHOT_DIR: &str = "shell_snapshots";\n        let path = format!("{session_id}.{nonce}.{extension}");\n        let span = info_span!("shell_snapshot", thread_id = %config.session_id);\n    ', 'visualization': '\n        let visualizations_dir = codex_home.join("visualizations");\n        let thread_dir = visualizations_dir\n            .join(created_at.format("%Y/%m/%d").to_string())\n            .join(&thread_id);\n        let viewer_dir = codex_home\n            .join("visualization-viewers")\n            .join(thread_id)\n            .join(artifact_thread_id);\n    ', 'config_toml': '\n        /// Directory where Codex stores the SQLite state DB.\n        /// Defaults to `$CODEX_SQLITE_HOME` when set. Otherwise uses `$CODEX_HOME`.\n        pub sqlite_home: Option<AbsolutePathBuf>,\n    '}

def _snapshot(overrides: dict[str, str] | None=None) -> SourceSnapshot:
    source_texts = dict(SOURCE_TEXTS)
    source_texts.update(overrides or {})
    files: dict[str, SourceFile] = {}
    for key, spec_id in SOURCE_IDS.items():
        spec = SourceSpec(id=spec_id, legacy_key=f'fixture_{key}', group=SourceGroup.EXTRA, path_candidates=(f'fixture/{key}.rs',), required=False, roles=('local_storage',), extractor_ids=('extractor.local_storage',))
        files[spec_id] = SourceFile.create(spec=spec, selected_path=spec.primary_path, raw_bytes=source_texts[key].encode('utf-8'))
    digest = SourceSnapshot.digest_files(files)
    return SourceSnapshot(revision=SourceRevision(source_mode='fixture', repository='openai/codex', requested_ref='fixture', resolved_commit_sha='6af345407d9c2a568da9d01b6c4b81a9e61495c0', source_set_sha256=digest, dirty=False, commit_date='2026-09-01T00:00:00Z', commit_message='fixture'), files=files)

def _extract(overrides: dict[str, str] | None=None):
    diagnostics = DiagnosticCollector()
    result = LocalStorageExtractor().extract(_snapshot(overrides), diagnostics)
    return (result, diagnostics)

def test_local_storage_extractor_builds_complete_identity_and_layout_contract() -> None:
    result, diagnostics = _extract()
    assert result.semantic_complete is True
    assert diagnostics.summary()['error'] == 0
    data = result.data
    assert data['roots']['codex_home']['default'] == '~/.codex'
    assert data['roots']['sqlite_home']['fallback'] == '$CODEX_HOME'
    assert data['identity_domains']['session_id']['filename_component'] is False
    assert data['identity_domains']['thread_id']['sqlite_threads_primary_key'] == 'threads.id'
    assert data['identity_domains']['rollout_id']['ordinary_equals_thread_id'] is True
    assert data['rollouts']['filename_grammar']['replacement'].endswith('<thread_id>_<rollout_id>.jsonl[.zst]')
    assert data['rollouts']['filename_grammar']['underscore_meaning'] == 'distinct rollout revision, not a fork edge'
    assert data['transitions']['resume']['creates_replacement_rollout'] is False
    assert data['transitions']['revert']['session_id'] == 'preserved verbatim from source_meta.session_id'
    assert data['transitions']['revert']['creates_thread_row_for_rollout_id'] is False
    assert data['transitions']['fork']['equivalent_to_revert'] is False
    assert data['sidecars']['shell_snapshot']['retention_seconds'] == 259200
    assert data['sidecars']['writer_lock']['key_domain'] == 'thread_id'

def test_local_storage_database_catalog_and_pointer_are_exact() -> None:
    result, _ = _extract()
    data = result.data
    assert [row['filename'] for row in data['databases']['files']] == ['state_5.sqlite', 'logs_2.sqlite', 'goals_1.sqlite', 'memories_1.sqlite', 'queue_1.sqlite', 'thread_history_1.sqlite']
    pointer = data['databases']['state_thread_pointer']
    assert pointer['logical_key_domain'] == 'thread_id'
    assert pointer['session_id_column_present_in_initial_table'] is False
    assert pointer['session_id_authority'] == 'rollout session_meta payload'
    assert pointer['rollout_id_row_created_for_replacement'] is False
    assert pointer['compare_and_swap_sql'] == 'UPDATE threads SET rollout_path = ? WHERE id = ? AND rollout_path = ?'

def test_local_storage_payload_validates_against_package_schema() -> None:
    result, _ = _extract()
    schema_path = Path(__file__).parents[1] / 'codex_wire_audit' / 'proof_schema_templates' / 'local-storage-semantics-v1.schema.json'
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(result.data), key=lambda item: list(item.absolute_path))
    assert errors == [], '\n'.join((f"/{'/'.join(map(str, error.absolute_path))}: {error.message}" for error in errors))

def test_rollout_filename_marker_accepts_rustfmt_line_break() -> None:
    source = SOURCE_TEXTS['rollout_filename'].replace(
        'format!("rollout-{timestamp}-{}_{}.jsonl", self.thread_id, self.rollout_id)',
        'format!(\n            "rollout-{timestamp}-{}_{}.jsonl",\n            self.thread_id, self.rollout_id\n        )',
    )
    result, diagnostics = _extract({'rollout_filename': source})
    assert result.semantic_complete is True
    assert 'LOCAL_STORAGE_SEMANTIC_MARKER_MISSING' not in {item.code for item in diagnostics.values()}

def test_local_storage_semantic_drift_is_fail_visible() -> None:
    result, diagnostics = _extract({'rollout_filename': SOURCE_TEXTS['rollout_filename'].replace("ids.split_once('_').unwrap_or((ids, ids))", 'parse_ids_with_new_grammar(ids)')})
    assert result.semantic_complete is False
    codes = {item.code for item in diagnostics.values()}
    assert 'LOCAL_STORAGE_SEMANTIC_MARKER_MISSING' in codes
    filename_check = next((row for row in result.data['coverage']['marker_checks'] if row['source_key'] == 'rollout_filename'))
    assert "ids.split_once('_').unwrap_or((ids, ids))" in filename_check['missing_markers']

def test_threads_session_id_column_change_requires_review() -> None:
    result, diagnostics = _extract({'threads_migration': SOURCE_TEXTS['threads_migration'].replace('rollout_path TEXT NOT NULL,', 'rollout_path TEXT NOT NULL,\n            session_id TEXT NOT NULL,')})
    assert result.semantic_complete is False
    assert result.data['databases']['state_thread_pointer']['session_id_column_present_in_initial_table'] is True
    assert 'LOCAL_STORAGE_SQLITE_IDENTITY_SHAPE_CHANGED' in {item.code for item in diagnostics.values()}

def test_local_storage_is_registered_and_has_source_registry_coverage() -> None:
    extractor_ids = {extractor.extractor_id for extractor in create_extractors()}
    assert 'extractor.local_storage' in extractor_ids
    registry = from_legacy_maps({}, {}, {'config_toml': 'codex-rs/config/src/config_toml.rs'})
    registry_ids = {spec.id for spec in registry.specs}
    assert set(SOURCE_IDS.values()) <= registry_ids
    config_spec = registry.get('source_spec.extra.config_toml')
    assert 'extractor.local_storage' in config_spec.extractor_ids

def test_full_and_focused_profiles_require_local_storage_extractor() -> None:
    profile_path = Path(__file__).parents[1] / 'codex_wire_audit' / 'coverage_profiles.v3.json'
    document = json.loads(profile_path.read_text(encoding='utf-8'))
    profiles = {row['id']: row for row in document['profiles']}
    assert 'extractor.local_storage' in profiles['codex_wire_full']['required_extractors']
    assert profiles['local_storage_only']['required_extractors'] == ['extractor.local_storage']

def test_release_spec_declares_local_storage_capability_closure() -> None:
    release_path = Path(__file__).parents[1] / 'codex_wire_audit' / 'release_spec.v1.json'
    document = json.loads(release_path.read_text(encoding='utf-8'))
    claims = {row['id']: row for row in document['capability_claims']}
    local = claims['local_storage']
    assert local['extractor_ids'] == ['extractor.local_storage']
    assert 'extractors/local_storage.py' in local['required_resources']
    assert 'proof_schema_templates/local-storage-semantics-v1.schema.json' in local['required_resources']
