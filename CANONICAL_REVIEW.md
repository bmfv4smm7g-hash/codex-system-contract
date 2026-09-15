# Canonical representation review

The reviewed `main` tree did not contain the claimed complete canonical
publication. This change establishes a bounded, source-derived
`codex-system-contract/v1` as the only machine representation emitted for the
migrated surfaces.

The report contains `system_contract` and no alternate configuration,
local-storage, graph, or construction-model paths. The API is deliberately
breaking: the package installs no adapter, alias, fallback reader, or duplicate
projection. New semantics enter through source specifications, extractor facts,
schema fragments, reference checks, and tests. A breaking semantic change
requires a contract-version change rather than a second representation.

Permanent CI is read-only and validates the exact committed tree across the
supported Python matrix, deterministic assets, maintainability, proof-critical
coverage, the pinned Codex checkout and source bytes, and an independently
rebuilt wheel/sdist closure.
