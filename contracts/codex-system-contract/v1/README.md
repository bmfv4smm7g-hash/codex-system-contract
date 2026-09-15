# `codex-system-contract/v1`

The report emits exactly one machine representation for migrated Codex audit
semantics: `system_contract`. Its `model` owns source identity, source
inventory, extractor facts, completeness state, and graph relationships.

No configuration or local-storage aliases are emitted. Consumers use this
versioned contract directly and reject versions they do not understand. Schema
validation is supplemented by canonical-content integrity, source/reference
checks, required-source completeness, graph checks, secret safety, and optional
revalidation of every recorded source byte against a checkout.
