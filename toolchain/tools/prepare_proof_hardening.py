from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path.cwd()
TOOLCHAIN = ROOT / "toolchain"


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one marker in {path}: {old[:80]!r}; got {text.count(old)}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


HISTORY_IDENTITY = r'''"""Fail-closed fork/revert identity and Responses routing semantics."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile, SourceSnapshot
from .registry import ExtractorResult, register_extractor


EXTRACTOR_ID = "extractor.history_identity"
SCHEMA_VERSION = "1.1.0"
SCHEMA_ID = "https://schemas.codex-system-contract.invalid/history/history-identity-semantics-v1.schema.json"

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


def _emit(
    diagnostics: DiagnosticCollector,
    *,
    code: str,
    message: str,
    entity: str,
    source_refs: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    diagnostics.emit(
        code=code,
        severity="error",
        category="history_identity",
        message=message,
        extractor_id=EXTRACTOR_ID,
        entity_id=entity,
        source_refs=source_refs or [],
        details=details or {},
        recoverable=False,
        strict_failure=True,
    )


def _revision_classification(core: SourceFile | None) -> dict[str, Any]:
    cache_affinity = _observed(
        core,
        "fn responses_session_id",
        "self.prompt_cache_key(metadata)",
        "ChatGPT derives cache affinity from the Responses session-id header",
    )
    logical_session = _observed(
        core,
        "session_id: Some(responses_metadata.session_id.to_string())",
        "Some(responses_metadata.session_id.to_string())",
    )
    if cache_affinity and logical_session:
        mode = "conflicting"
    elif cache_affinity:
        mode = "root_cache_affinity_session_id"
    elif logical_session:
        mode = "logical_session_id"
    else:
        mode = "unknown"
    return {
        "mode": mode,
        "cache_affinity_observed": cache_affinity,
        "logical_session_observed": logical_session,
        "exclusive": cache_affinity != logical_session,
    }


def _fork_identity(
    core: SourceFile | None,
    session: SourceFile | None,
    thread_manager: SourceFile | None,
    tui_backtrack: SourceFile | None,
    revision: dict[str, Any],
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
    persistent_observed = root_identity and fresh_thread and fork_lineage and prompt_cache_override
    ephemeral_observed = (
        persistent_observed
        and revision["mode"] == "root_cache_affinity_session_id"
        and ephemeral_cache_override
        and body_prompt_cache_key
    )
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
            "revision_mode": revision["mode"],
            "prompt_cache_key_override_priority": _rule(
                core,
                tokens=(
                    "if let Some(prompt_cache_key) = &self.prompt_cache_key_override",
                    "return prompt_cache_key.clone();",
                    "responses_metadata.session_id.clone()",
                ),
                source_semantics="prompt_cache_key override wins; ordinary root/user requests otherwise use the actual Responses metadata session_id",
            ),
            "new_root_cache_affinity_header": _rule(
                core,
                tokens=(
                    "ChatGPT derives cache affinity from the Responses session-id header",
                    "fn responses_session_id",
                    "self.prompt_cache_key(metadata)",
                ),
                source_semantics="newer root requests derive the session-id routing header from prompt-cache identity while retaining actual identity in metadata",
            ),
            "legacy_actual_session_header": _rule(
                core,
                tokens=(
                    "session_id: Some(responses_metadata.session_id.to_string())",
                    "Some(responses_metadata.session_id.to_string())",
                ),
                source_semantics="older Responses request paths send the actual metadata session_id directly",
            ),
            "body_prompt_cache_key": _rule(
                core,
                tokens=(
                    "let prompt_cache_key = Some(self.prompt_cache_key(responses_metadata));",
                    "client_metadata: Some(responses_metadata.client_metadata())",
                ),
                source_semantics="Responses body carries prompt_cache_key while client_metadata retains separately derived actual identity",
            ),
        },
        "persistent_root_fork": {
            "observed": persistent_observed,
            "actual_thread_id": "new fork thread_id" if persistent_observed else None,
            "actual_session_id": (
                "new fork session_id equal to the new root thread_id" if persistent_observed else None
            ),
            "source_identity": "forked_from_thread_id" if persistent_observed else None,
            "source_session_reused_as_fork_cache_key": False if persistent_observed else None,
            "responses_session_id": (
                "new fork session_id when no unrelated prompt_cache_key override applies"
                if persistent_observed
                else None
            ),
            "body_prompt_cache_key": (
                "new fork session_id when no unrelated prompt_cache_key override applies"
                if persistent_observed
                else None
            ),
            "source_semantics": "durable/root fork has a new logical identity; ephemeral cache routing does not replace it",
        },
        "ephemeral_root_fork": {
            "observed": ephemeral_observed,
            "cache_routing_override_observed": ephemeral_cache_override,
            "cache_affinity_header_observed": revision["cache_affinity_observed"],
            "body_prompt_cache_key_observed": body_prompt_cache_key,
            "actual_thread_id": "new fork thread_id" if persistent_observed else None,
            "actual_session_id": (
                "new fork session_id equal to the new root thread_id" if persistent_observed else None
            ),
            "cache_key_source": "source SessionMeta.session_id" if ephemeral_observed else None,
            "responses_session_id": (
                "source SessionMeta.session_id for cache affinity" if ephemeral_observed else None
            ),
            "body_prompt_cache_key": "source SessionMeta.session_id" if ephemeral_observed else None,
            "actual_identity_still_in_client_metadata": body_prompt_cache_key if ephemeral_observed else None,
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
    response_observed = logical_thread_preserved and session_preserved and prompt_cache_fallback
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
                "value": "source_meta.id / existing thread_id" if logical_thread_preserved else None,
            },
            "session_id_preserved": {
                "observed": session_preserved,
                "value": "source_meta.session_id" if session_preserved else None,
            },
            "rollout_id_replaced": {
                "observed": rollout_replaced,
                "value": "new ThreadId UUID used as physical rollout_id" if rollout_replaced else None,
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
            "observed": response_observed,
            "actual_thread_id": "same logical thread_id" if response_observed else None,
            "actual_session_id": "same source_meta.session_id" if response_observed else None,
            "physical_rollout_id": "new rollout_id" if rollout_replaced else None,
            "fork_cache_key_created_by_revert": False if response_observed else None,
            "resumed_history_excluded_from_ephemeral_fork_cache_override": (
                resumed_has_no_fork_cache_key if response_observed else None
            ),
            "responses_session_id": (
                "same logical session_id unless another independent prompt_cache_key override applies"
                if response_observed
                else None
            ),
            "body_prompt_cache_key": (
                "same logical session_id unless another independent prompt_cache_key override applies"
                if response_observed
                else None
            ),
        },
    }


def _invariants(
    fork: dict[str, Any],
    revert: dict[str, Any],
    revision: dict[str, Any],
) -> tuple[dict[str, bool], list[str]]:
    observed = {
        "revision_mode_exclusive": bool(revision["exclusive"]),
        "fork_fresh_thread_id": bool(fork["logical_identity"]["fresh_thread_id"]["observed"]),
        "fork_root_session_from_new_thread": bool(
            fork["logical_identity"]["root_session_id_from_new_thread_id"]["observed"]
        ),
        "fork_lineage_separate": bool(
            fork["logical_identity"]["lineage_is_separate_from_identity"]["observed"]
        ),
        "persistent_fork_identity": bool(fork["persistent_root_fork"]["observed"]),
        "prompt_edit_uses_fork": bool(fork["tui_prompt_edit_rewind"]["uses_fork"]["observed"]),
        "revert_paginated_only": bool(revert["app_server"]["paginated_only"]["observed"]),
        "revert_reload_same_thread": bool(
            revert["app_server"]["reload_same_logical_thread"]["observed"]
        ),
        "revert_logical_thread_preserved": bool(
            revert["storage_identity"]["logical_thread_id_preserved"]["observed"]
        ),
        "revert_session_preserved": bool(
            revert["storage_identity"]["session_id_preserved"]["observed"]
        ),
        "revert_rollout_replaced": bool(
            revert["storage_identity"]["rollout_id_replaced"]["observed"]
        ),
        "revert_lineage_preserved": bool(
            revert["storage_identity"]["fork_lineage_preserved"]["observed"]
        ),
        "revert_fork_cutoff_shrinks_only": bool(
            revert["storage_identity"]["fork_cutoff_can_shrink"]["observed"]
        ),
        "revert_response_identity": bool(
            revert["responses_after_persistent_root_revert"]["observed"]
        ),
    }
    if revision["mode"] == "root_cache_affinity_session_id":
        observed["ephemeral_fork_cache_routing"] = bool(fork["ephemeral_root_fork"]["observed"])
    missing = sorted(name for name, value in observed.items() if not value)
    return observed, missing


def _operation_matrix(fork: dict[str, Any], revert: dict[str, Any]) -> dict[str, Any]:
    persistent = bool(fork["persistent_root_fork"]["observed"])
    ephemeral = bool(fork["ephemeral_root_fork"]["observed"])
    reverted = bool(revert["responses_after_persistent_root_revert"]["observed"])
    return {
        "persistent_root_fork": {
            "observed": persistent,
            "logical_thread": "new" if persistent else "unknown",
            "logical_session": "new" if persistent else "unknown",
            "physical_rollout": "new fork rollout" if persistent else "unknown",
            "responses_routing_session": "new session" if persistent else "unknown",
            "lineage": "forked_from_thread_id points to source" if persistent else "unknown",
        },
        "ephemeral_root_fork": {
            "observed": ephemeral,
            "logical_thread": "new" if ephemeral else "unknown",
            "logical_session": "new" if ephemeral else "unknown",
            "physical_rollout": (
                "ephemeral/no durable thread metadata reservation" if ephemeral else "unknown"
            ),
            "responses_routing_session": (
                "source session for cache affinity" if ephemeral else "unknown"
            ),
            "lineage": "forked_from_thread_id points to source" if ephemeral else "unknown",
        },
        "persistent_root_revert": {
            "observed": reverted,
            "logical_thread": "preserved" if reverted else "unknown",
            "logical_session": "preserved" if reverted else "unknown",
            "physical_rollout": "new rollout_id" if reverted else "unknown",
            "responses_routing_session": "preserved session" if reverted else "unknown",
            "lineage": (
                "existing fork lineage retained; cutoff may shrink" if reverted else "unknown"
            ),
        },
    }


class HistoryIdentityExtractor:
    extractor_id = EXTRACTOR_ID
    source_spec_ids = SOURCE_IDS
    required_source_spec_ids = SOURCE_IDS

    def extract(
        self,
        snapshot: SourceSnapshot,
        diagnostics: DiagnosticCollector,
    ) -> ExtractorResult:
        sources = {source_id: snapshot.files.get(source_id) for source_id in SOURCE_IDS}
        available = sorted(source_id for source_id, source in sources.items() if source is not None)
        missing_sources = sorted(source_id for source_id, source in sources.items() if source is None)
        for source_id in missing_sources:
            _emit(
                diagnostics,
                code="HISTORY_IDENTITY_SOURCE_UNAVAILABLE",
                message=f"Required history-identity source is unavailable: {source_id}",
                entity=f"history_identity.source.{source_id}",
                details={"source_spec_id": source_id},
            )

        revision = _revision_classification(sources[CORE])
        if revision["mode"] == "unknown":
            _emit(
                diagnostics,
                code="HISTORY_IDENTITY_REVISION_UNKNOWN",
                message="Responses session/cache identity revision could not be classified.",
                entity="history_identity.responses_revision",
                source_refs=[CORE] if sources[CORE] else [],
            )
        elif revision["mode"] == "conflicting":
            _emit(
                diagnostics,
                code="HISTORY_IDENTITY_REVISION_CONFLICT",
                message="Both legacy and cache-affinity Responses session-id modes were observed.",
                entity="history_identity.responses_revision",
                source_refs=[CORE] if sources[CORE] else [],
            )

        fork = _fork_identity(
            sources[CORE],
            sources[SESSION],
            sources[THREAD_MANAGER],
            sources[TUI_BACKTRACK],
            revision,
        )
        revert = _revert_identity(
            sources[CORE],
            sources[SESSION],
            sources[THREAD_PROCESSOR],
            sources[STORAGE_REVERT],
        )
        observed, missing_invariants = _invariants(fork, revert, revision)
        for name in missing_invariants:
            _emit(
                diagnostics,
                code="HISTORY_IDENTITY_INVARIANT_MISSING",
                message=f"Required history-identity invariant is not source-proven: {name}",
                entity=f"history_identity.invariant.{name}",
                source_refs=available,
                details={"invariant": name, "revision_mode": revision["mode"]},
            )

        complete = (
            not missing_sources
            and revision["mode"] in {"logical_session_id", "root_cache_affinity_session_id"}
            and not missing_invariants
        )
        body: dict[str, Any] = {
            "$schema": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
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
                "required_source_spec_ids": list(SOURCE_IDS),
                "available_source_spec_ids": available,
                "missing_source_spec_ids": missing_sources,
                "revision_classification": revision,
                "mode": "fail-closed source-pattern classification",
            },
            "invariants": {
                "observed": observed,
                "missing_required": missing_invariants,
            },
            "fork": fork,
            "revert": revert,
            "operation_matrix": _operation_matrix(fork, revert),
            "evidence": {
                source_id: _evidence(source, "history identity observation")
                for source_id, source in sorted(sources.items())
                if source is not None
            },
            "semantic_complete": complete,
        }
        body["semantic_digest"] = hashlib.sha256(_canonical(body)).hexdigest()
        return ExtractorResult(
            extractor_id=EXTRACTOR_ID,
            schema_version=SCHEMA_VERSION,
            data=body,
            semantic_complete=complete,
            source_spec_ids=SOURCE_IDS,
        )


@register_extractor(EXTRACTOR_ID)
def _history_identity_factory() -> HistoryIdentityExtractor:
    return HistoryIdentityExtractor()
'''

HISTORY_SCHEMA = r'''{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://schemas.codex-system-contract.invalid/history/history-identity-semantics-v1.schema.json",
  "title": "Codex history identity and Responses cache-routing semantics",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "$schema",
    "schema_version",
    "ownership",
    "coverage",
    "invariants",
    "fork",
    "revert",
    "operation_matrix",
    "evidence",
    "semantic_complete",
    "semantic_digest"
  ],
  "properties": {
    "$schema": {"const": "https://schemas.codex-system-contract.invalid/history/history-identity-semantics-v1.schema.json"},
    "schema_version": {"const": "1.1.0"},
    "ownership": {"$ref": "#/$defs/ownership"},
    "coverage": {
      "type": "object",
      "additionalProperties": false,
      "required": ["required_source_spec_ids", "available_source_spec_ids", "missing_source_spec_ids", "revision_classification", "mode"],
      "properties": {
        "required_source_spec_ids": {"type": "array", "minItems": 6, "items": {"type": "string"}, "uniqueItems": true},
        "available_source_spec_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
        "missing_source_spec_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
        "revision_classification": {
          "type": "object",
          "additionalProperties": false,
          "required": ["mode", "cache_affinity_observed", "logical_session_observed", "exclusive"],
          "properties": {
            "mode": {"enum": ["logical_session_id", "root_cache_affinity_session_id", "unknown", "conflicting"]},
            "cache_affinity_observed": {"type": "boolean"},
            "logical_session_observed": {"type": "boolean"},
            "exclusive": {"type": "boolean"}
          }
        },
        "mode": {"const": "fail-closed source-pattern classification"}
      }
    },
    "invariants": {
      "type": "object",
      "additionalProperties": false,
      "required": ["observed", "missing_required"],
      "properties": {
        "observed": {"type": "object", "minProperties": 14, "additionalProperties": {"type": "boolean"}},
        "missing_required": {"type": "array", "items": {"type": "string"}, "uniqueItems": true}
      }
    },
    "fork": {"type": "object"},
    "revert": {"type": "object"},
    "operation_matrix": {
      "type": "object",
      "additionalProperties": false,
      "required": ["persistent_root_fork", "ephemeral_root_fork", "persistent_root_revert"],
      "properties": {
        "persistent_root_fork": {"$ref": "#/$defs/operation"},
        "ephemeral_root_fork": {"$ref": "#/$defs/operation"},
        "persistent_root_revert": {"$ref": "#/$defs/operation"}
      }
    },
    "evidence": {"type": "object", "additionalProperties": {"$ref": "#/$defs/evidence"}},
    "semantic_complete": {"type": "boolean"},
    "semantic_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
  },
  "allOf": [
    {
      "if": {"properties": {"semantic_complete": {"const": true}}, "required": ["semantic_complete"]},
      "then": {
        "properties": {
          "coverage": {
            "properties": {
              "missing_source_spec_ids": {"maxItems": 0},
              "revision_classification": {
                "properties": {
                  "mode": {"enum": ["logical_session_id", "root_cache_affinity_session_id"]},
                  "exclusive": {"const": true}
                }
              }
            }
          },
          "invariants": {
            "properties": {
              "missing_required": {"maxItems": 0},
              "observed": {"additionalProperties": {"const": true}}
            }
          }
        }
      }
    }
  ],
  "$defs": {
    "ownership": {
      "type": "object",
      "additionalProperties": false,
      "required": ["owns", "does_not_own"],
      "properties": {
        "owns": {"type": "array", "minItems": 1, "items": {"type": "string"}, "uniqueItems": true},
        "does_not_own": {"type": "array", "minItems": 1, "items": {"type": "string"}, "uniqueItems": true}
      }
    },
    "operation": {
      "type": "object",
      "additionalProperties": false,
      "required": ["observed", "logical_thread", "logical_session", "physical_rollout", "responses_routing_session", "lineage"],
      "properties": {
        "observed": {"type": "boolean"},
        "logical_thread": {"enum": ["new", "preserved", "unknown"]},
        "logical_session": {"enum": ["new", "preserved", "unknown"]},
        "physical_rollout": {"type": "string"},
        "responses_routing_session": {"type": "string"},
        "lineage": {"type": "string"}
      }
    },
    "evidence": {
      "type": "object",
      "additionalProperties": false,
      "required": ["source_spec_id", "path", "sha256", "git_blob_sha", "symbol"],
      "properties": {
        "source_spec_id": {"type": "string"},
        "path": {"type": "string"},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "git_blob_sha": {"type": ["string", "null"]},
        "symbol": {"type": "string"}
      }
    }
  }
}
'''

HISTORY_TESTS = r'''from __future__ import annotations

from codex_wire_audit.diagnostics import DiagnosticCollector
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


def _snapshot(*, mode: str = "new", missing: str | None = None, break_invariant: bool = False) -> SourceSnapshot:
    common_core = """
fn prompt_cache_key(&self, responses_metadata: &CodexResponsesMetadata) -> String {
    if let Some(prompt_cache_key) = &self.prompt_cache_key_override {
        return prompt_cache_key.clone();
    }
    responses_metadata.session_id.clone()
}
let prompt_cache_key = Some(self.prompt_cache_key(responses_metadata));
client_metadata: Some(responses_metadata.client_metadata()),
"""
    legacy = """
headers.extend(build_session_headers(
    Some(responses_metadata.session_id.to_string()),
    Some(responses_metadata.thread_id.to_string()),
));
session_id: Some(responses_metadata.session_id.to_string()),
"""
    current = """
// ChatGPT derives cache affinity from the Responses session-id header.
fn responses_session_id(&self, metadata: &CodexResponsesMetadata) -> String {
    self.prompt_cache_key(metadata)
}
"""
    if mode == "legacy":
        core = common_core + legacy
    elif mode == "conflict":
        core = common_core + legacy + current
    elif mode == "unknown":
        core = common_core
    else:
        core = common_core + current
    session = """
InitialHistory::New | InitialHistory::Cleared | InitialHistory::Forked(_) => None
// session_id is equal to the root thread's ID.
SessionId::from(thread_id)
// Ephemeral forks reuse cache routing, without sharing storage or lifecycle identity.
let fork_cache_key = match &initial_history {
    InitialHistory::Forked(items) if config.ephemeral
        && !session_configuration.session_source.is_non_root_agent() => {
        items.iter().find_map(|item| match item {
            RolloutItem::SessionMeta(meta) => Some(meta.meta.session_id.to_string()),
            _ => None,
        })
    }
    InitialHistory::New | InitialHistory::Cleared | InitialHistory::Resumed(_)
        | InitialHistory::Forked(_) => None,
};
review_override.or(fork_cache_key)
"""
    processor = '"thread/revert only supports paginated threads"; reload_paginated_thread(); if resumed_thread_id != thread_id {}'
    manager = '/// The new thread will have a fresh id.\nfn fork_prepared_thread() {}\nrequest.forked_from_thread_id = source_thread_id;'
    backtrack = 'AppEvent::ForkSessionForPromptEdit {}'
    storage = """
let forked_from_ordinal_exclusive = source_cutoff.map(|cutoff| {
    // Reverting into inherited history can shrink, but never grow, the parent prefix.
    cutoff.min(history_base.map_or(0, |base| base.end_ordinal_exclusive))
});
let rollout_id = ThreadId::new();
RolloutRecorderParams::new(source_meta.id, source_meta.forked_from_id, source_meta.parent_thread_id)
    .with_session_id(source_meta.session_id)
    .with_rollout_id(rollout_id)
    .with_forked_from_ordinal_exclusive(forked_from_ordinal_exclusive);
replace_rollout_path_if_current(
"""
    if break_invariant:
        manager = manager.replace("fresh id", "different id")
    rows = [
        _file("source_spec.base.core", "client.rs", core),
        _file("source_spec.extra.responses_transport_session", "session.rs", session),
        _file("source_spec.extra.app_server_thread_manager", "thread_manager.rs", manager),
        _file("source_spec.extra.app_server_thread_processor", "thread_processor.rs", processor),
        _file("source_spec.extra.local_storage_tui_backtrack", "app_backtrack.rs", backtrack),
        _file("source_spec.extra.local_storage_revert_thread", "revert_thread.rs", storage),
    ]
    files = {row.spec_id: row for row in rows if row.spec_id != missing}
    revision = SourceRevision(
        "fixture",
        "openai/codex",
        "fixture",
        "1" * 40,
        SourceSnapshot.digest_files(files),
        False,
    )
    return SourceSnapshot(revision, files)


def test_missing_source_fails_closed() -> None:
    diagnostics = DiagnosticCollector()
    result = HistoryIdentityExtractor().extract(
        _snapshot(missing="source_spec.extra.local_storage_revert_thread"), diagnostics
    )
    assert not result.semantic_complete
    assert result.data["coverage"]["missing_source_spec_ids"]
    assert "HISTORY_IDENTITY_SOURCE_UNAVAILABLE" in {item.code for item in diagnostics.values()}


def test_unknown_revision_fails_closed() -> None:
    diagnostics = DiagnosticCollector()
    result = HistoryIdentityExtractor().extract(_snapshot(mode="unknown"), diagnostics)
    assert not result.semantic_complete
    assert result.data["coverage"]["revision_classification"]["mode"] == "unknown"
    assert "HISTORY_IDENTITY_REVISION_UNKNOWN" in {item.code for item in diagnostics.values()}


def test_conflicting_revision_fails_closed() -> None:
    diagnostics = DiagnosticCollector()
    result = HistoryIdentityExtractor().extract(_snapshot(mode="conflict"), diagnostics)
    assert not result.semantic_complete
    assert result.data["coverage"]["revision_classification"]["mode"] == "conflicting"
    assert "HISTORY_IDENTITY_REVISION_CONFLICT" in {item.code for item in diagnostics.values()}


def test_missing_required_invariant_does_not_publish_categorical_claim() -> None:
    diagnostics = DiagnosticCollector()
    result = HistoryIdentityExtractor().extract(_snapshot(break_invariant=True), diagnostics)
    assert not result.semantic_complete
    matrix = result.data["operation_matrix"]["persistent_root_fork"]
    assert matrix["observed"] is False
    assert matrix["logical_thread"] == "unknown"
    assert "HISTORY_IDENTITY_INVARIANT_MISSING" in {item.code for item in diagnostics.values()}


def test_legacy_and_cache_affinity_modes_are_exclusive_and_complete() -> None:
    for mode, expected in (
        ("legacy", "logical_session_id"),
        ("new", "root_cache_affinity_session_id"),
    ):
        result = HistoryIdentityExtractor().extract(_snapshot(mode=mode), DiagnosticCollector())
        assert result.semantic_complete
        classification = result.data["coverage"]["revision_classification"]
        assert classification["mode"] == expected
        assert classification["exclusive"] is True
'''

MODEL_CONTROL = r'''"""Source-derived Codex model catalog, capability, reroute, and safety control plane."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..diagnostics import DiagnosticCollector
from ..models import SourceFile, SourceSnapshot
from .registry import ExtractorResult, register_extractor

EXTRACTOR_ID = "extractor.model_control_plane"
SCHEMA_VERSION = "1.0.0"
SCHEMA_ID = "https://schemas.codex-system-contract.invalid/model/model-control-plane-v1.schema.json"

COMMON = "source_spec.extra.app_server_common"
MODEL = "source_spec.extra.app_server_model"
EVENTS = "source_spec.extra.app_server_bespoke_events"
SOURCE_IDS = (COMMON, MODEL, EVENTS)


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


def _emit(diagnostics: DiagnosticCollector, source: SourceFile | None, code: str, token: str) -> None:
    diagnostics.emit(
        code=code,
        severity="error",
        category="model_control_plane",
        message=f"Required model-control-plane evidence is missing: {token}",
        extractor_id=EXTRACTOR_ID,
        entity_id=f"model_control_plane.{code.lower()}",
        source_refs=[source.spec_id] if source else [],
        details={"token": token, "path": source.selected_path if source else None},
        recoverable=False,
        strict_failure=True,
    )


def _check(
    diagnostics: DiagnosticCollector,
    source: SourceFile | None,
    checks: tuple[tuple[str, str], ...],
) -> tuple[dict[str, bool], bool]:
    observed: dict[str, bool] = {}
    complete = source is not None
    for code, token in checks:
        present = source is not None and token in source.text
        observed[code.lower()] = present
        if not present:
            complete = False
            _emit(diagnostics, source, code, token)
    return observed, complete


class ModelControlPlaneExtractor:
    extractor_id = EXTRACTOR_ID
    source_spec_ids = SOURCE_IDS
    required_source_spec_ids = SOURCE_IDS
    coverage_profiles = ("model_control_plane_only", "current_main_static_full")

    def extract(self, snapshot: SourceSnapshot, diagnostics: DiagnosticCollector) -> ExtractorResult:
        sources = {source_id: snapshot.files.get(source_id) for source_id in SOURCE_IDS}
        missing = sorted(source_id for source_id, source in sources.items() if source is None)
        for source_id in missing:
            _emit(diagnostics, None, "MODEL_CONTROL_SOURCE_UNAVAILABLE", source_id)

        common_observed, common_ok = _check(
            diagnostics,
            sources[COMMON],
            (
                ("MODEL_LIST_RPC_MISSING", 'ModelList => "model/list"'),
                ("MODEL_CAPABILITIES_RPC_MISSING", 'ModelProviderCapabilitiesRead => "modelProvider/capabilities/read"'),
                ("MODEL_REROUTED_WIRE_MISSING", 'ModelRerouted => "model/rerouted"'),
                ("MODEL_VERIFICATION_WIRE_MISSING", 'ModelVerification => "model/verification"'),
                ("MODEL_SAFETY_BUFFERING_WIRE_MISSING", 'ModelSafetyBufferingUpdated => "model/safetyBuffering/updated"'),
            ),
        )
        model_observed, model_ok = _check(
            diagnostics,
            sources[MODEL],
            (
                ("MODEL_PROVIDER_CAPABILITIES_MISSING", "pub struct ModelProviderCapabilitiesReadResponse"),
                ("MODEL_INPUT_MODALITIES_MISSING", "pub input_modalities: Vec<InputModality>"),
                ("MODEL_MULTI_AGENT_VERSION_MISSING", "pub multi_agent_version: Option<MultiAgentVersion>"),
                ("MODEL_SERVICE_TIERS_MISSING", "pub service_tiers: Vec<ModelServiceTier>"),
                ("MODEL_DEFAULT_SERVICE_TIER_MISSING", "pub default_service_tier: Option<String>"),
                ("MODEL_ACCESS_PROGRAMS_MISSING", "pub available_access_programs: Option<ModelAccessPrograms>"),
                ("MODEL_REROUTE_PAYLOAD_MISSING", "pub struct ModelReroutedNotification"),
                ("MODEL_VERIFICATION_PAYLOAD_MISSING", "pub struct ModelVerificationNotification"),
                ("MODEL_SAFETY_BUFFERING_PAYLOAD_MISSING", "pub struct ModelSafetyBufferingUpdatedNotification"),
            ),
        )
        event_observed, events_ok = _check(
            diagnostics,
            sources[EVENTS],
            (
                ("MODEL_REROUTE_EVENT_BRIDGE_MISSING", "EventMsg::ModelReroute(event)"),
                ("MODEL_REROUTE_NOTIFICATION_BRIDGE_MISSING", "ModelReroutedNotification"),
                ("MODEL_SAFETY_EVENT_BRIDGE_MISSING", "EventMsg::SafetyBuffering(event)"),
                ("MODEL_SAFETY_NOTIFICATION_BRIDGE_MISSING", "ModelSafetyBufferingUpdatedNotification"),
            ),
        )
        complete = not missing and common_ok and model_ok and events_ok
        body: dict[str, Any] = {
            "$schema": SCHEMA_ID,
            "schema_version": SCHEMA_VERSION,
            "ownership": {
                "owns": [
                    "app-server model catalog and provider-capability wire surface",
                    "model reroute, verification, moderation, and safety-buffering notifications",
                    "requested/catalog/effective-model boundary classification",
                ],
                "does_not_own": [
                    "backend policy that selects an effective model",
                    "Responses OpenAI-Model response-header extraction",
                    "billing or rate-limit enforcement",
                ],
            },
            "coverage": {
                "required_source_spec_ids": list(SOURCE_IDS),
                "missing_source_spec_ids": missing,
                "observed": {**common_observed, **model_observed, **event_observed},
            },
            "catalog": {
                "rpc": "model/list",
                "pagination": ["cursor", "limit", "includeHidden"],
                "identity_fields": ["id", "model", "displayName", "isDefault"],
                "selection_fields": [
                    "supportedReasoningEfforts",
                    "defaultReasoningEffort",
                    "inputModalities",
                    "multiAgentVersion",
                    "serviceTiers",
                    "defaultServiceTier",
                    "availableAccessPrograms",
                ],
                "lifecycle_fields": ["upgrade", "upgradeInfo", "availabilityNux", "hidden"],
            },
            "provider_capabilities": {
                "rpc": "modelProvider/capabilities/read",
                "fields": ["namespaceTools", "imageGeneration", "webSearch"],
            },
            "notifications": {
                "model/rerouted": ["threadId", "turnId", "fromModel", "toModel", "reason"],
                "model/verification": ["threadId", "turnId", "verifications"],
                "turn/moderationMetadata": ["threadId", "turnId", "metadata"],
                "model/safetyBuffering/updated": [
                    "threadId",
                    "turnId",
                    "model",
                    "useCases",
                    "reasons",
                    "showBufferingUi",
                    "fasterModel",
                ],
            },
            "model_identity_boundary": {
                "requested_model": "client-to-server request selection",
                "catalog_model": "app-server model/list item and capabilities",
                "effective_model": "server-to-client OpenAI-Model / ResponseEvent::ServerModel",
                "rerouted_model": "explicit model/rerouted transition from fromModel to toModel",
                "safety_faster_model": "optional recommendation in model/safetyBuffering/updated; not an implicit reroute",
            },
            "evidence": {
                key: _evidence(source, "model control-plane observation")
                for key, source in sorted(sources.items())
                if source is not None
            },
            "semantic_complete": complete,
        }
        body["semantic_digest"] = hashlib.sha256(_canonical(body)).hexdigest()
        return ExtractorResult(EXTRACTOR_ID, SCHEMA_VERSION, body, complete, SOURCE_IDS)


@register_extractor(EXTRACTOR_ID)
def _factory() -> ModelControlPlaneExtractor:
    return ModelControlPlaneExtractor()
'''

MODEL_SCHEMA = r'''{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://schemas.codex-system-contract.invalid/model/model-control-plane-v1.schema.json",
  "title": "Codex model control plane",
  "type": "object",
  "additionalProperties": false,
  "required": ["$schema", "schema_version", "ownership", "coverage", "catalog", "provider_capabilities", "notifications", "model_identity_boundary", "evidence", "semantic_complete", "semantic_digest"],
  "properties": {
    "$schema": {"const": "https://schemas.codex-system-contract.invalid/model/model-control-plane-v1.schema.json"},
    "schema_version": {"const": "1.0.0"},
    "ownership": {"type": "object", "required": ["owns", "does_not_own"], "additionalProperties": false, "properties": {"owns": {"type": "array", "items": {"type": "string"}}, "does_not_own": {"type": "array", "items": {"type": "string"}}}},
    "coverage": {"type": "object", "required": ["required_source_spec_ids", "missing_source_spec_ids", "observed"], "additionalProperties": false, "properties": {"required_source_spec_ids": {"type": "array", "minItems": 3, "items": {"type": "string"}, "uniqueItems": true}, "missing_source_spec_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": true}, "observed": {"type": "object", "minProperties": 18, "additionalProperties": {"type": "boolean"}}}},
    "catalog": {"type": "object", "minProperties": 5, "additionalProperties": true},
    "provider_capabilities": {"type": "object", "minProperties": 2, "additionalProperties": true},
    "notifications": {"type": "object", "minProperties": 4, "additionalProperties": {"type": "array", "items": {"type": "string"}}},
    "model_identity_boundary": {"type": "object", "minProperties": 5, "additionalProperties": {"type": "string"}},
    "evidence": {"type": "object", "additionalProperties": {"type": "object"}},
    "semantic_complete": {"type": "boolean"},
    "semantic_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
  },
  "allOf": [{"if": {"properties": {"semantic_complete": {"const": true}}, "required": ["semantic_complete"]}, "then": {"properties": {"coverage": {"properties": {"missing_source_spec_ids": {"maxItems": 0}, "observed": {"additionalProperties": {"const": true}}}}}}}]
}
'''

MODEL_TESTS = r"""from __future__ import annotations

from codex_wire_audit.diagnostics import DiagnosticCollector
from codex_wire_audit.extractors import create_extractors
from codex_wire_audit.extractors.model_control_plane import ModelControlPlaneExtractor
from codex_wire_audit.models import SourceFile, SourceGroup, SourceRevision, SourceSnapshot, SourceSpec


def _file(spec_id: str, path: str, text: str) -> SourceFile:
    spec = SourceSpec(id=spec_id, legacy_key=spec_id.rsplit(".", 1)[-1], group=SourceGroup.EXTRA, path_candidates=(path,), required=False)
    return SourceFile.create(spec=spec, selected_path=path, raw_bytes=text.encode())


def _snapshot(*, break_model: bool = False) -> SourceSnapshot:
    common = '''
ModelList => "model/list" {}
ModelProviderCapabilitiesRead => "modelProvider/capabilities/read" {}
ModelRerouted => "model/rerouted" (v2::ModelReroutedNotification)
ModelVerification => "model/verification" (v2::ModelVerificationNotification)
ModelSafetyBufferingUpdated => "model/safetyBuffering/updated" (v2::ModelSafetyBufferingUpdatedNotification)
'''
    model = '''
pub struct ModelProviderCapabilitiesReadResponse { pub namespace_tools: bool, pub image_generation: bool, pub web_search: bool }
pub input_modalities: Vec<InputModality>
pub multi_agent_version: Option<MultiAgentVersion>
pub service_tiers: Vec<ModelServiceTier>
pub default_service_tier: Option<String>
pub available_access_programs: Option<ModelAccessPrograms>
pub struct ModelReroutedNotification {}
pub struct ModelVerificationNotification {}
pub struct ModelSafetyBufferingUpdatedNotification {}
'''
    if break_model:
        model = model.replace("pub service_tiers: Vec<ModelServiceTier>", "")
    events = '''
EventMsg::ModelReroute(event) => { let notification = ModelReroutedNotification {}; }
EventMsg::SafetyBuffering(event) => { let notification = ModelSafetyBufferingUpdatedNotification {}; }
'''
    rows = [
        _file("source_spec.extra.app_server_common", "common.rs", common),
        _file("source_spec.extra.app_server_model", "model.rs", model),
        _file("source_spec.extra.app_server_bespoke_events", "bespoke_event_handling.rs", events),
    ]
    files = {row.spec_id: row for row in rows}
    revision = SourceRevision("fixture", "openai/codex", "fixture", "2" * 40, SourceSnapshot.digest_files(files), False)
    return SourceSnapshot(revision, files)


def test_model_control_plane_is_complete_and_registered() -> None:
    result = ModelControlPlaneExtractor().extract(_snapshot(), DiagnosticCollector())
    assert result.semantic_complete
    assert result.data["model_identity_boundary"]["requested_model"].startswith("client-to-server")
    assert "extractor.model_control_plane" in {item.extractor_id for item in create_extractors()}


def test_model_control_plane_fails_closed_on_field_drift() -> None:
    diagnostics = DiagnosticCollector()
    result = ModelControlPlaneExtractor().extract(_snapshot(break_model=True), diagnostics)
    assert not result.semantic_complete
    assert "model_service_tiers_missing" in result.data["coverage"]["observed"]
    assert "MODEL_SERVICE_TIERS_MISSING" in {item.code for item in diagnostics.values()}
"""

APP_SERVER_INVENTORY = '"""Complete app-server method and notification inventory with explicit scope classification."""\n\nfrom __future__ import annotations\n\nimport hashlib\nimport json\nimport re\nfrom typing import Any\n\nfrom ..diagnostics import DiagnosticCollector\nfrom ..models import SourceFile, SourceSnapshot\nfrom .registry import ExtractorResult, register_extractor\n\nEXTRACTOR_ID = "extractor.app_server_inventory"\nSCHEMA_VERSION = "1.0.0"\nSCHEMA_ID = "https://schemas.codex-system-contract.invalid/app-server/full-inventory-v1.schema.json"\nSOURCE_SPEC_ID = "source_spec.extra.app_server_common"\n\n_HEADER = re.compile(\n    r\'(?m)^\\s*(?P<variant>[A-Za-z][A-Za-z0-9_]*)\\s*=>\\s*"(?P<method>[^\"]+)"\\s*(?P<open>[{(])\'\n)\n\n\ndef _canonical(value: object) -> bytes:\n    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()\n\n\ndef _block(text: str, marker: str) -> str | None:\n    start = text.find(marker)\n    if start < 0:\n        return None\n    opening = text.find("{", start + len(marker))\n    if opening < 0:\n        return None\n    closing = _matching(text, opening)\n    if closing is None:\n        return None\n    return text[opening + 1 : closing]\n\n\ndef _matching(text: str, opening: int) -> int | None:\n    pairs = {"{": "}", "(": ")", "[": "]"}\n    opener = text[opening]\n    closer = pairs.get(opener)\n    if closer is None:\n        return None\n    depth = 0\n    quote: str | None = None\n    escaped = False\n    line_comment = False\n    block_comment = 0\n    index = opening\n    while index < len(text):\n        char = text[index]\n        nxt = text[index + 1] if index + 1 < len(text) else ""\n        if line_comment:\n            if char == "\\n":\n                line_comment = False\n            index += 1\n            continue\n        if block_comment:\n            if char == "/" and nxt == "*":\n                block_comment += 1\n                index += 2\n                continue\n            if char == "*" and nxt == "/":\n                block_comment -= 1\n                index += 2\n                continue\n            index += 1\n            continue\n        if quote is not None:\n            if escaped:\n                escaped = False\n            elif char == "\\\\":\n                escaped = True\n            elif char == quote:\n                quote = None\n            index += 1\n            continue\n        if char == "/" and nxt == "/":\n            line_comment = True\n            index += 2\n            continue\n        if char == "/" and nxt == "*":\n            block_comment = 1\n            index += 2\n            continue\n        if char in {\'"\', "\'"}:\n            quote = char\n            index += 1\n            continue\n        if char == opener:\n            depth += 1\n        elif char == closer:\n            depth -= 1\n            if depth == 0:\n                return index\n        index += 1\n    return None\n\n\ndef _entries(text: str, marker: str, *, request: bool) -> tuple[list[dict[str, Any]], int]:\n    block = _block(text, marker)\n    if block is None:\n        return [], 0\n    matches = list(_HEADER.finditer(block))\n    rows: list[dict[str, Any]] = []\n    previous_end = 0\n    for match in matches:\n        opening = match.start("open")\n        closing = _matching(block, opening)\n        if closing is None:\n            continue\n        prefix = block[previous_end : match.start()]\n        previous_end = closing + 1\n        method = match.group("method")\n        body = block[opening + 1 : closing]\n        common = {\n            "variant": match.group("variant"),\n            "method": method,\n            "namespace": method.split("/", 1)[0],\n            "experimental": "#[experimental(" in prefix,\n        }\n        if request:\n            serialization = re.search(\n                r"(?m)^\\s*serialization:\\s*(?P<value>.+?),\\s*$", body\n            )\n            common["serialization"] = (\n                serialization.group("value").strip() if serialization else "unknown"\n            )\n        else:\n            common["payload"] = body.strip()\n        rows.append(common)\n    return rows, len(matches)\n\n\ndef _group(rows: list[dict[str, Any]]) -> dict[str, int]:\n    result: dict[str, int] = {}\n    for row in rows:\n        result[row["namespace"]] = result.get(row["namespace"], 0) + 1\n    return dict(sorted(result.items()))\n\n\ndef _duplicates(rows: list[dict[str, Any]]) -> list[str]:\n    counts: dict[str, int] = {}\n    for row in rows:\n        method = str(row["method"])\n        counts[method] = counts.get(method, 0) + 1\n    return sorted(method for method, count in counts.items() if count > 1)\n\n\nclass AppServerInventoryExtractor:\n    extractor_id = EXTRACTOR_ID\n    source_spec_ids = (SOURCE_SPEC_ID,)\n    required_source_spec_ids = (SOURCE_SPEC_ID,)\n\n    def extract(self, snapshot: SourceSnapshot, diagnostics: DiagnosticCollector) -> ExtractorResult:\n        source = snapshot.files.get(SOURCE_SPEC_ID)\n        if source is None:\n            diagnostics.emit(\n                code="APP_SERVER_INVENTORY_SOURCE_UNAVAILABLE",\n                severity="error",\n                category="app_server_inventory",\n                message="App-server protocol common source is unavailable.",\n                extractor_id=EXTRACTOR_ID,\n                entity_id="app_server_inventory.source",\n                source_refs=[],\n                details={"source_spec_id": SOURCE_SPEC_ID},\n                recoverable=False,\n                strict_failure=True,\n            )\n            return ExtractorResult(EXTRACTOR_ID, SCHEMA_VERSION, {}, False, self.source_spec_ids)\n\n        requests, request_headers = _entries(\n            source.text, "client_request_definitions!", request=True\n        )\n        notifications, notification_headers = _entries(\n            source.text, "server_notification_definitions!", request=False\n        )\n        duplicate_requests = _duplicates(requests)\n        duplicate_notifications = _duplicates(notifications)\n        parse_complete = (\n            bool(requests)\n            and bool(notifications)\n            and len(requests) == request_headers\n            and len(notifications) == notification_headers\n        )\n        complete = parse_complete and not duplicate_requests and not duplicate_notifications\n        if not parse_complete:\n            diagnostics.emit(\n                code="APP_SERVER_INVENTORY_PARSE_INCOMPLETE",\n                severity="error",\n                category="app_server_inventory",\n                message="App-server macro headers and parsed entries disagree.",\n                extractor_id=EXTRACTOR_ID,\n                entity_id="app_server_inventory.parse",\n                source_refs=[SOURCE_SPEC_ID],\n                details={\n                    "request_headers": request_headers,\n                    "requests": len(requests),\n                    "notification_headers": notification_headers,\n                    "notifications": len(notifications),\n                },\n                recoverable=False,\n                strict_failure=True,\n            )\n        if duplicate_requests or duplicate_notifications:\n            diagnostics.emit(\n                code="APP_SERVER_INVENTORY_DUPLICATE_WIRE_METHOD",\n                severity="error",\n                category="app_server_inventory",\n                message="App-server wire inventory contains duplicate methods.",\n                extractor_id=EXTRACTOR_ID,\n                entity_id="app_server_inventory.methods",\n                source_refs=[SOURCE_SPEC_ID],\n                details={\n                    "requests": duplicate_requests,\n                    "notifications": duplicate_notifications,\n                },\n                recoverable=False,\n                strict_failure=True,\n            )\n\n        request_namespaces = _group(requests)\n        notification_namespaces = _group(notifications)\n        namespaces = set(request_namespaces) | set(notification_namespaces)\n        deeply_modeled = {"thread", "turn", "item", "model"}\n        body: dict[str, Any] = {\n            "$schema": SCHEMA_ID,\n            "schema_version": SCHEMA_VERSION,\n            "ownership": {\n                "owns": [\n                    "complete app-server request and notification name inventory",\n                    "namespace and experimental-surface classification",\n                ],\n                "does_not_own": [\n                    "deep payload semantics for every feature family",\n                    "handler implementation correctness",\n                ],\n            },\n            "parse_accounting": {\n                "request_headers": request_headers,\n                "parsed_requests": len(requests),\n                "notification_headers": notification_headers,\n                "parsed_notifications": len(notifications),\n            },\n            "requests": requests,\n            "notifications": notifications,\n            "namespace_counts": {\n                "requests": request_namespaces,\n                "notifications": notification_namespaces,\n            },\n            "coverage_boundary": {\n                "deeply_modeled_elsewhere": sorted(deeply_modeled & namespaces),\n                "inventory_only": sorted(namespaces - deeply_modeled),\n                "unclassified": [],\n            },\n            "duplicates": {\n                "requests": duplicate_requests,\n                "notifications": duplicate_notifications,\n            },\n            "evidence": {\n                "source_spec_id": source.spec_id,\n                "path": source.selected_path,\n                "sha256": source.content_sha256,\n                "git_blob_sha": source.git_blob_sha,\n                "symbol": "client_request_definitions/server_notification_definitions",\n            },\n            "semantic_complete": complete,\n        }\n        body["semantic_digest"] = hashlib.sha256(_canonical(body)).hexdigest()\n        return ExtractorResult(EXTRACTOR_ID, SCHEMA_VERSION, body, complete, self.source_spec_ids)\n\n\n@register_extractor(EXTRACTOR_ID)\ndef _factory() -> AppServerInventoryExtractor:\n    return AppServerInventoryExtractor()\n'

APP_SERVER_INVENTORY_SCHEMA = r'''{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://schemas.codex-system-contract.invalid/app-server/full-inventory-v1.schema.json",
  "title": "Complete Codex app-server wire inventory",
  "type": "object",
  "additionalProperties": false,
  "required": ["$schema", "schema_version", "ownership", "parse_accounting", "requests", "notifications", "namespace_counts", "coverage_boundary", "duplicates", "evidence", "semantic_complete", "semantic_digest"],
  "properties": {
    "$schema": {"const": "https://schemas.codex-system-contract.invalid/app-server/full-inventory-v1.schema.json"},
    "schema_version": {"const": "1.0.0"},
    "ownership": {"type": "object"},
    "parse_accounting": {"type": "object", "required": ["request_headers", "parsed_requests", "notification_headers", "parsed_notifications"], "additionalProperties": false, "properties": {"request_headers": {"type": "integer", "minimum": 1}, "parsed_requests": {"type": "integer", "minimum": 1}, "notification_headers": {"type": "integer", "minimum": 1}, "parsed_notifications": {"type": "integer", "minimum": 1}}},
    "requests": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/request"}},
    "notifications": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/notification"}},
    "namespace_counts": {"type": "object"},
    "coverage_boundary": {"type": "object", "required": ["deeply_modeled_elsewhere", "inventory_only", "unclassified"], "additionalProperties": false, "properties": {"deeply_modeled_elsewhere": {"type": "array", "items": {"type": "string"}}, "inventory_only": {"type": "array", "items": {"type": "string"}}, "unclassified": {"type": "array", "maxItems": 0, "items": {"type": "string"}}}},
    "duplicates": {"type": "object", "required": ["requests", "notifications"], "additionalProperties": false, "properties": {"requests": {"type": "array", "items": {"type": "string"}}, "notifications": {"type": "array", "items": {"type": "string"}}}},
    "evidence": {"type": "object"},
    "semantic_complete": {"type": "boolean"},
    "semantic_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
  },
  "$defs": {
    "request": {"type": "object", "additionalProperties": false, "required": ["variant", "method", "namespace", "experimental", "serialization"], "properties": {"variant": {"type": "string"}, "method": {"type": "string"}, "namespace": {"type": "string"}, "experimental": {"type": "boolean"}, "serialization": {"type": "string"}}},
    "notification": {"type": "object", "additionalProperties": false, "required": ["variant", "method", "namespace", "experimental", "payload"], "properties": {"variant": {"type": "string"}, "method": {"type": "string"}, "namespace": {"type": "string"}, "experimental": {"type": "boolean"}, "payload": {"type": "string"}}}
  }
}
'''

APP_SERVER_INVENTORY_TESTS = 'from __future__ import annotations\n\nfrom codex_wire_audit.diagnostics import DiagnosticCollector\nfrom codex_wire_audit.extractors.app_server_inventory import AppServerInventoryExtractor\nfrom codex_wire_audit.models import SourceFile, SourceGroup, SourceRevision, SourceSnapshot, SourceSpec\n\n\ndef _snapshot() -> SourceSnapshot:\n    text = \'\'\'\nclient_request_definitions! {\n    ThreadStart => "thread/start" {\n        params: ThreadStartParams,\n        serialization: None,\n        response: ThreadStartResponse,\n    },\n    /// Attachment lifecycle remains inventory-visible even when payload semantics are separate.\n    ThreadAttachmentAdd => "thread/attachment/add" {\n        params: Add,\n        serialization: thread_id(params.thread_id),\n        response: AddResponse,\n    },\n    #[experimental("remoteControl/enable")]\n    RemoteControlEnable => "remoteControl/enable" {\n        params: Enable,\n        serialization: global("remote"),\n        response: EnableResponse,\n    },\n}\nserver_notification_definitions! {\n    ThreadStarted => "thread/started" (ThreadStartedNotification),\n    ModelRerouted => "model/rerouted" (ModelReroutedNotification),\n    AccountUpdated => "account/updated" (AccountUpdatedNotification),\n}\n\'\'\'\n    spec = SourceSpec(\n        id="source_spec.extra.app_server_common",\n        legacy_key="app_server_common",\n        group=SourceGroup.EXTRA,\n        path_candidates=("common.rs",),\n        required=False,\n    )\n    source = SourceFile.create(spec=spec, selected_path="common.rs", raw_bytes=text.encode())\n    files = {spec.id: source}\n    revision = SourceRevision(\n        "fixture", "openai/codex", "fixture", "3" * 40,\n        SourceSnapshot.digest_files(files), False,\n    )\n    return SourceSnapshot(revision, files)\n\n\ndef test_complete_inventory_keeps_non_lifecycle_namespaces_visible() -> None:\n    result = AppServerInventoryExtractor().extract(_snapshot(), DiagnosticCollector())\n    assert result.semantic_complete\n    methods = {row["method"] for row in result.data["requests"]}\n    assert "thread/attachment/add" in methods\n    assert "remoteControl/enable" in methods\n    assert result.data["namespace_counts"]["notifications"]["model"] == 1\n    assert "remoteControl" in result.data["coverage_boundary"]["inventory_only"]\n    assert result.data["parse_accounting"]["request_headers"] == 3\n    assert result.data["requests"][2]["experimental"] is True\n'


write("toolchain/codex_wire_audit/extractors/history_identity.py", HISTORY_IDENTITY)
write("toolchain/codex_wire_audit/proof_schema_templates/history-identity-semantics-v1.schema.json", HISTORY_SCHEMA)
write("toolchain/tests/test_history_identity_fail_closed.py", HISTORY_TESTS)
write("toolchain/codex_wire_audit/extractors/model_control_plane.py", MODEL_CONTROL)
write("toolchain/codex_wire_audit/proof_schema_templates/model-control-plane-v1.schema.json", MODEL_SCHEMA)
write("toolchain/tests/test_model_control_plane_extractor.py", MODEL_TESTS)
write("toolchain/codex_wire_audit/extractors/app_server_inventory.py", APP_SERVER_INVENTORY)
write("toolchain/codex_wire_audit/proof_schema_templates/app-server-full-inventory-v1.schema.json", APP_SERVER_INVENTORY_SCHEMA)
write("toolchain/tests/test_app_server_inventory_extractor.py", APP_SERVER_INVENTORY_TESTS)

# Activate new extractors.
replace_once(
    "toolchain/codex_wire_audit/extractors/__init__.py",
    '    "app_server_rpc",\n    "runtime_behavior",\n    "history_identity",\n',
    '    "app_server_rpc",\n    "app_server_inventory",\n    "model_control_plane",\n    "runtime_behavior",\n    "history_identity",\n',
)

# Give analytics_enabled an explicit semantic domain.
replace_once(
    "toolchain/codex_wire_audit/extractors/turn_metadata.py",
    '    if field_name in {"turn_started_at_unix_ms", "history_ingest_requested"}:\n        return "timing_and_history"\n',
    '    if field_name in {"turn_started_at_unix_ms", "history_ingest_requested"}:\n        return "timing_and_history"\n    if field_name == "analytics_enabled":\n        return "analytics_state"\n',
)

# Make schema failures actionable.
replace_once(
    "toolchain/codex_wire_audit/system_contract_validation.py",
    'def _graph_references(graph: Mapping[str, Any]) -> None:\n',
    'def _validation_error_detail(error: Any) -> str:\n    path = "/".join(map(str, error.absolute_path)) or "<root>"\n    schema_path = "/".join(map(str, error.absolute_schema_path)) or "<root>"\n    return f"{path}: {error.message} [validator={error.validator}; schema={schema_path}]"\n\n\ndef _graph_references(graph: Mapping[str, Any]) -> None:\n',
)
replace_once(
    "toolchain/codex_wire_audit/system_contract_validation.py",
    '            if errors:\n                raise ValueError("extractor fragment schema violation: " + key)\n',
    '            if errors:\n                raise ValueError(\n                    "extractor fragment schema violation: "\n                    + key\n                    + " at "\n                    + _validation_error_detail(errors[0])\n                )\n',
)
replace_once(
    "toolchain/codex_wire_audit/system_contract_validation.py",
    '    if errors:\n        path = "/".join(map(str, errors[0].absolute_path))\n        raise ValueError("canonical schema violation at " + path)\n',
    '    if errors:\n        raise ValueError("canonical schema violation at " + _validation_error_detail(errors[0]))\n',
)

# Allow current-only extractors to declare profile and all-source activation without changing older extractors.
replace_once(
    "toolchain/codex_wire_audit/evolution.py",
    "    for extractor in create_extractors():\n        if extractor.source_spec_ids and (not any((source_id in snapshot.files for source_id in extractor.source_spec_ids))):\n            continue\n",
    "    for extractor in create_extractors():\n        coverage_profiles = getattr(extractor, \"coverage_profiles\", None)\n        if coverage_profiles is not None and coverage_profile not in coverage_profiles:\n            continue\n        required_source_spec_ids = getattr(extractor, \"required_source_spec_ids\", ())\n        if required_source_spec_ids:\n            if not all(source_id in snapshot.files for source_id in required_source_spec_ids):\n                continue\n        elif extractor.source_spec_ids and not any(\n            source_id in snapshot.files for source_id in extractor.source_spec_ids\n        ):\n            continue\n",
)

# Register shared source ownership for history identity, global app-server inventory, and model control plane.
source_registry = TOOLCHAIN / "codex_wire_audit/source_registry.py"
text = source_registry.read_text(encoding="utf-8")
marker = '''def _merge_app_server_domain_specs(specs: list[SourceSpec]) -> None:
    _merge_optional_specs(
        specs,
        _APP_SERVER_RPC_SPECS,
        role="app_server_rpc",
        extractor_id="extractor.app_server_rpc",
    )


'''
addition = marker + '''_HISTORY_IDENTITY_SPECS = (
    ("source_spec.base.core", "core", "codex-rs/core/src/client.rs", ()),
    ("source_spec.extra.responses_transport_session", "responses_transport_session", "codex-rs/core/src/session/session.rs", ()),
    ("source_spec.extra.app_server_thread_manager", "app_server_thread_manager", "codex-rs/core/src/thread_manager.rs", ()),
    ("source_spec.extra.app_server_thread_processor", "app_server_thread_processor", "codex-rs/app-server/src/request_processors/thread_processor.rs", ()),
    ("source_spec.extra.local_storage_tui_backtrack", "local_storage_tui_backtrack", "codex-rs/tui/src/app_backtrack.rs", ()),
    ("source_spec.extra.local_storage_revert_thread", "local_storage_revert_thread", "codex-rs/thread-store/src/local/revert_thread.rs", ()),
)

_MODEL_CONTROL_PLANE_SPECS = (
    ("source_spec.extra.app_server_common", "app_server_common", "codex-rs/app-server-protocol/src/protocol/common.rs", ()),
    ("source_spec.extra.app_server_model", "app_server_model", "codex-rs/app-server-protocol/src/protocol/v2/model.rs", ()),
    ("source_spec.extra.app_server_bespoke_events", "app_server_bespoke_events", "codex-rs/app-server/src/bespoke_event_handling.rs", ()),
)


def _merge_extended_contract_specs(specs: list[SourceSpec]) -> None:
    _merge_optional_specs(specs, _HISTORY_IDENTITY_SPECS, role="history_identity", extractor_id="extractor.history_identity")
    _merge_optional_specs(specs, _MODEL_CONTROL_PLANE_SPECS, role="model_control_plane", extractor_id="extractor.model_control_plane")
    _merge_optional_specs(specs, (_APP_SERVER_RPC_SPECS[0],), role="app_server_inventory", extractor_id="extractor.app_server_inventory")


'''

if text.count(marker) != 1:
    raise RuntimeError("source registry app-server marker changed")
text = text.replace(marker, addition, 1)
text = text.replace(
    '    _merge_app_server_domain_specs(specs)\n    return SourceRegistry(specs)\n',
    '    _merge_app_server_domain_specs(specs)\n    _merge_extended_contract_specs(specs)\n    return SourceRegistry(specs)\n',
    1,
)
source_registry.write_text(text, encoding="utf-8")

# Profiles: require hard identity and complete app-server inventory in broad profiles;
# add a current-main static profile for current-only surfaces.
profile_path = TOOLCHAIN / "codex_wire_audit/proof_profile_data/proof-profiles.v3.json"
profiles_doc = json.loads(profile_path.read_text(encoding="utf-8"))
profiles = profiles_doc["profiles"]
by_id = {item["id"]: item for item in profiles}
for profile_id in ("hybrid_v19", "codex_wire_full"):
    required = by_id[profile_id]["required_extractors"]
    for extractor_id in ("extractor.history_identity", "extractor.app_server_inventory"):
        if extractor_id not in required:
            required.append(extractor_id)
    required.sort()
for profile in profiles:
    if "metadata_history" in profile.get("required_dimensions", []):
        keys = profile["required_history_keys"]
        analytics_key = "key.turn_metadata.analytics_enabled"
        if analytics_key not in keys:
            keys.append(analytics_key)
            keys.sort()
new_profiles = [
    {
        "allow_legacy_reconstruction": False,
        "description": "Fail-closed source proof of fork/revert logical identity, physical rollout replacement, and Responses cache-routing identity.",
        "id": "history_identity_only",
        "required_dimensions": ["schema", "profile", "provenance"],
        "required_extractors": ["extractor.history_identity"],
        "required_history_keys": [],
        "required_runtime_scenarios": [],
        "version": "1.0.0",
    },
    {
        "allow_legacy_reconstruction": False,
        "description": "Complete app-server request and notification inventory with explicit deep-model versus inventory-only boundaries.",
        "id": "app_server_inventory_only",
        "required_dimensions": ["schema", "profile", "provenance"],
        "required_extractors": ["extractor.app_server_inventory"],
        "required_history_keys": [],
        "required_runtime_scenarios": [],
        "version": "1.0.0",
    },
    {
        "allow_legacy_reconstruction": False,
        "description": "Current Codex model catalog, provider capabilities, reroute, verification, moderation, and safety-buffering control plane.",
        "id": "model_control_plane_only",
        "required_dimensions": ["schema", "profile", "provenance"],
        "required_extractors": ["extractor.model_control_plane"],
        "required_history_keys": [],
        "required_runtime_scenarios": [],
        "version": "1.0.0",
    },
    {
        "allow_legacy_reconstruction": False,
        "description": "Current-main static contract requiring every source-derived wire, storage, identity, model-control, prompt, policy, plugin, environment, routing, and runtime-behavior extractor without runtime-observation claims.",
        "id": "current_main_static_full",
        "required_dimensions": ["schema", "profile", "rust_semantics", "provenance", "metadata_history"],
        "required_extractors": sorted(set(by_id["codex_wire_full"]["required_extractors"] + ["extractor.model_control_plane"])),
        "required_history_keys": sorted(set(by_id["codex_wire_full"]["required_history_keys"] + ["key.turn_metadata.analytics_enabled"])),
        "required_runtime_scenarios": [],
        "version": "1.0.0",
    },
]
existing_ids = set(by_id)
for profile in new_profiles:
    if profile["id"] not in existing_ids:
        profiles.append(profile)
profiles.sort(key=lambda item: item["id"])
profile_path.write_text(json.dumps(profiles_doc, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")

# Track analytics_enabled's real legacy-extra -> Core-owned transition.
catalog_path = TOOLCHAIN / "codex_wire_audit/metadata_history_data/metadata-key-history.v1.json"
catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
analytics_key = "key.turn_metadata.analytics_enabled"
legacy_state = "state.analytics_enabled.legacy_extra"
core_state = "state.analytics_enabled.core_owned"
version_id = "version.2026-09-10.analytics_enabled_core_owned"
evidence_id = "evidence.commit.9b033b46"
if analytics_key not in catalog["keys"]:
    catalog["keys"][analytics_key] = {
        "current_state_ref": core_state,
        "description": "Formerly usable as configured extra metadata; now a Core-owned optional boolean reporting the selected session analytics client's collection state while legacy input is accepted then filtered.",
        "id": analytics_key,
        "kind": "turn_metadata_key",
        "namespace": "codex_turn_metadata",
        "replacement_key_refs": [],
        "source_candidates": [
            "codex-rs/core/src/responses_metadata.rs",
            "codex-rs/core/src/session/session.rs",
        ],
        "state_refs": [legacy_state, core_state],
        "wire_name": "analytics_enabled",
    }
    catalog["states"][legacy_state] = {
        "assertions": {
            "backward_compatible_reserved": False,
            "constant_names": [],
            "payload_container": "flattened_extra_string",
            "reserved_extra_key": False,
        },
        "containers": {
            "compatibility_header_json": "emitted_conditionally",
            "config_input": "accepted",
            "flat_client_metadata": "absent",
            "internal_runtime": "absent",
            "mcp_request_meta": "emitted_conditionally",
            "nested_turn_metadata": "emitted_conditionally",
        },
        "description": "Before Core ownership, this valid extra-metadata name could be flattened as a caller-supplied string.",
        "evidence_refs": ["evidence.commit.ddf04ad2"],
        "id": legacy_state,
        "key_ref": analytics_key,
        "status": "legacy_input",
        "value_schema": {"type": "string"},
    }
    catalog["states"][core_state] = {
        "assertions": {
            "backward_compatible_reserved": True,
            "compatibility_header_container": "emitted_conditionally",
            "constant_names": ["ANALYTICS_ENABLED_KEY"],
            "mcp_container": "emitted_conditionally",
            "payload_container": "emitted_conditionally",
            "reserved_extra_key": True,
            "top_level_client_metadata": "absent",
            "wire_literal_present": True,
        },
        "containers": {
            "compatibility_header_json": "emitted_conditionally",
            "config_input": "accepted_filtered",
            "flat_client_metadata": "absent",
            "internal_runtime": "emitted_conditionally",
            "mcp_request_meta": "emitted_conditionally",
            "nested_turn_metadata": "emitted_conditionally",
        },
        "condition": {
            "op": "all",
            "operands": [
                {"path": "session.analytics_context", "operator": "exists", "value": True}
            ],
        },
        "description": "Core emits the selected session analytics client's collection state as an optional boolean. Absence means no initialized session analytics context, not disabled collection.",
        "evidence_refs": ["evidence.commit.ddf04ad2", evidence_id],
        "id": core_state,
        "key_ref": analytics_key,
        "status": "core_owned_legacy_input_filtered",
        "value_schema": {"type": "boolean"},
    }
    for version in catalog["versions"].values():
        version["state_refs"][analytics_key] = legacy_state
    previous = catalog["versions"][catalog["current_version_ref"]]
    state_refs = dict(previous["state_refs"])
    state_refs[analytics_key] = core_state
    ordinal = max(item["ordinal"] for item in catalog["versions"].values()) + 1
    catalog["versions"][version_id] = {
        "commit_sha": "9b033b46428440d4c413198819737c87b943960c",
        "committed_at": "2026-09-10T19:41:14Z",
        "event": "core_ownership_transition",
        "evidence": {
            "commit_sha": "9b033b46428440d4c413198819737c87b943960c",
            "committed_at": "2026-09-10T19:41:14Z",
            "id": evidence_id,
            "source_paths": [
                "codex-rs/core/src/responses_metadata.rs",
                "codex-rs/core/src/session/session.rs",
            ],
            "title": "Expose session analytics state in Responses turn metadata",
            "url": "https://github.com/openai/codex/commit/9b033b46428440d4c413198819737c87b943960c",
        },
        "exact_snapshot": True,
        "id": version_id,
        "ordinal": ordinal,
        "state_refs": state_refs,
        "title": "analytics_enabled becomes a Core-owned optional boolean",
    }
    catalog["transitions"].append({
        "at_version_ref": version_id,
        "classification": "core_ownership_transition",
        "description": "Convert analytics_enabled from a configurable flattened string into a typed Core-owned optional boolean while accepting then filtering legacy input.",
        "from_state_ref": legacy_state,
        "id": "transition.analytics_enabled.core_owned",
        "key_ref": analytics_key,
        "to_state_ref": core_state,
    })
    catalog["current_version_ref"] = version_id
    catalog["reviewed_through"] = {
        "commit_sha": "9b033b46428440d4c413198819737c87b943960c",
        "committed_at": "2026-09-10T19:41:14Z",
        "source_basis": "github_commit_history_and_source_diffs",
    }
    catalog["catalog_version"] = "1.1.0"

payload = dict(catalog)
payload.pop("integrity", None)
encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
catalog["integrity"] = {"algorithm": "sha256", "canonical_payload_sha256": hashlib.sha256(encoded).hexdigest()}
catalog_path.write_text(json.dumps(catalog, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")

# Strengthen and broaden the current-main canary.
canary = ROOT / ".github/workflows/codex-current-main-canary.yml"
canary_text = canary.read_text(encoding="utf-8")
canary_text = canary_text.replace(
    'on:\n  workflow_dispatch:\n  schedule:\n    - cron: "41 7 * * 1"\n',
    'on:\n  push:\n    branches: [main]\n    paths:\n      - "toolchain/**"\n      - ".github/workflows/codex-current-main-canary.yml"\n  pull_request:\n    paths:\n      - "toolchain/**"\n      - ".github/workflows/codex-current-main-canary.yml"\n  workflow_dispatch:\n  schedule:\n    - cron: "41 7 * * *"\n',
    1,
)
canary_text = canary_text.replace('--coverage-profile hybrid_v19 \\\n', '--coverage-profile current_main_static_full \\\n            --fail-on incomplete \\\n', 1)
canary.write_text(canary_text, encoding="utf-8")

print("proof hardening source patch applied")
