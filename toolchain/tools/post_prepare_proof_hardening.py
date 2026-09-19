from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one marker in {path}, found {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


history = ROOT / "toolchain/codex_wire_audit/extractors/history_identity.py"
replace_once(
    history,
    '''    ephemeral_observed = (
        persistent_observed
        and revision["mode"] == "root_cache_affinity_session_id"
        and ephemeral_cache_override
        and body_prompt_cache_key
    )
''',
    '''    current_ephemeral_observed = (
        persistent_observed
        and revision["mode"] == "root_cache_affinity_session_id"
        and ephemeral_cache_override
        and body_prompt_cache_key
    )
    legacy_ephemeral_observed = (
        persistent_observed
        and revision["mode"] == "logical_session_id"
        and not ephemeral_cache_override
    )
    ephemeral_observed = current_ephemeral_observed or legacy_ephemeral_observed
''',
)
replace_once(
    history,
    '''            "cache_key_source": "source SessionMeta.session_id" if ephemeral_observed else None,
            "responses_session_id": (
                "source SessionMeta.session_id for cache affinity" if ephemeral_observed else None
            ),
            "body_prompt_cache_key": "source SessionMeta.session_id" if ephemeral_observed else None,
            "actual_identity_still_in_client_metadata": body_prompt_cache_key if ephemeral_observed else None,
''',
    '''            "cache_key_source": (
                "source SessionMeta.session_id" if current_ephemeral_observed else None
            ),
            "responses_session_id": (
                "source SessionMeta.session_id for cache affinity"
                if current_ephemeral_observed
                else "actual fork session_id on revisions without the fork cache-routing override"
                if legacy_ephemeral_observed
                else None
            ),
            "body_prompt_cache_key": (
                "source SessionMeta.session_id"
                if current_ephemeral_observed
                else "actual fork session_id unless another override applies"
                if legacy_ephemeral_observed
                else None
            ),
            "actual_identity_still_in_client_metadata": (
                body_prompt_cache_key if ephemeral_observed else None
            ),
''',
)
replace_once(
    history,
    '''            "responses_routing_session": (
                "source session for cache affinity" if ephemeral else "unknown"
            ),
''',
    '''            "responses_routing_session": (
                "source session for cache affinity"
                if ephemeral
                and fork["ephemeral_root_fork"]["cache_routing_override_observed"]
                else "new session"
                if ephemeral
                else "unknown"
            ),
''',
)

metadata_tests = ROOT / "toolchain/tests/test_metadata_history_v13.py"
replace_once(
    metadata_tests,
    'pub(crate) const FORKED_FROM_ORDINAL_EXCLUSIVE_KEY: &str = "forked_from_ordinal_exclusive";\n',
    'pub(crate) const FORKED_FROM_ORDINAL_EXCLUSIVE_KEY: &str = "forked_from_ordinal_exclusive";\n'
    'pub(crate) const ANALYTICS_ENABLED_KEY: &str = "analytics_enabled";\n',
)
replace_once(
    metadata_tests,
    '''    WINDOW_NUMBER_KEY,
    FORKED_FROM_ORDINAL_EXCLUSIVE_KEY,
];
const BACKWARD_COMPATIBLE_RESERVED_METADATA_KEYS: &[&str] = &[
    WINDOW_NUMBER_KEY,
    FORKED_FROM_ORDINAL_EXCLUSIVE_KEY,
];
''',
    '''    WINDOW_NUMBER_KEY,
    FORKED_FROM_ORDINAL_EXCLUSIVE_KEY,
    ANALYTICS_ENABLED_KEY,
];
const BACKWARD_COMPATIBLE_RESERVED_METADATA_KEYS: &[&str] = &[
    WINDOW_NUMBER_KEY,
    FORKED_FROM_ORDINAL_EXCLUSIVE_KEY,
    ANALYTICS_ENABLED_KEY,
];
''',
)
replace_once(
    metadata_tests,
    '''    #[serde(default, skip_serializing_if = "Option::is_none")]
    tool_namespaces_info: Option<&'a BTreeMap<String, String>>,
''',
    '''    #[serde(default, skip_serializing_if = "Option::is_none")]
    analytics_enabled: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    tool_namespaces_info: Option<&'a BTreeMap<String, String>>,
''',
)
replace_once(
    metadata_tests,
    '''            forked_from_ordinal_exclusive: self.forked_from_ordinal_exclusive,
            tool_namespaces_info: self.tool_namespaces_info.as_ref(),
''',
    '''            forked_from_ordinal_exclusive: self.forked_from_ordinal_exclusive,
            analytics_enabled: self.analytics_enabled,
            tool_namespaces_info: self.tool_namespaces_info.as_ref(),
''',
)
text = metadata_tests.read_text(encoding="utf-8")
text = text.replace('assert len(catalog["versions"]) == 10', 'assert len(catalog["versions"]) == 11')
text = text.replace('assert len(catalog["keys"]) == 7', 'assert len(catalog["keys"]) == 8')
text = text.replace('assert len(list((first / "versions").glob("*.json"))) == 10', 'assert len(list((first / "versions").glob("*.json"))) == 11')
text = text.replace('assert len(list((first / "keys").glob("*.json"))) == 7', 'assert len(list((first / "keys").glob("*.json"))) == 8')
metadata_tests.write_text(text, encoding="utf-8")

print("post-generation proof hardening compatibility updates applied")
