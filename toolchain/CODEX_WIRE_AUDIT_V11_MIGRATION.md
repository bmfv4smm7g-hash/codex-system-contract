# Migrating from v10 to v11

## Consumer compatibility

Existing v10 keys remain. Consumers that do not know v11 can continue reading the v10 report shape.

New consumers should prefer:

```text
/evolution_contract
/turn_metadata_semantics
/status/dimensions
/schema_identity
/semantic_diff
```

The top-level `versions.generator` becomes `5.0.0`, while the compatible report format remains `10.0.0`.

## CI migration

Start in observation mode:

```bash
codex-wire-audit \
  --repo-root "$CODEX_CHECKOUT" \
  --baseline-report last-success.json \
  --fail-on-semantic-change never \
  --fail-on error \
  --semantic-diff-output semantic-diff.json \
  --format canonical-json \
  --output report.json
```

After reviewing a few canary runs, enforce:

```text
--fail-on-semantic-change breaking
--fail-on incomplete
```

Treat `FIELD_EMISSION_EXPRESSION_UNCLASSIFIED`, `IDENTITY_GATE_EXPRESSION_UNCLASSIFIED`, `SOURCE_REQUIRED_UNAVAILABLE`, and schema-resolution errors as release blockers.

## Source moves

Prefer a registry overlay for a temporary or downstream path difference. Once an upstream move is stable, update the default source registry and retain the former path as a fallback candidate for a compatibility window.

## Report comparison

Do not compare pretty JSON text. Compare `evolution_contract` or use `semantic-diff.json`. Presentation wording, source line movement, and object order are intentionally excluded from stable semantic IDs.

## Current migration state

The static machine model is now composed from canonical, source-derived domain extractors. The frozen v10 report renderer remains available only for consumer compatibility and is excluded from `system_contract`; `migration.legacy_machine_reconstruction_remaining` is therefore `false` for the canonical model.

This does **not** make static source evidence equivalent to runtime observation. `codex_wire_full` still requires the `runtime_conformance` proof dimension and its bounded runtime scenarios. Until genuine report-bound observations are supplied, CI may continue using the transition profile rather than claiming full observed conformance.
