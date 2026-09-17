# Codex System Contract

Source-derived, evidence-bound contracts for the OpenAI Codex system: protocol,
configuration, prompt/context composition, tools, plugins, policy, execution
environment, storage, routing, agents, host integration, and runtime behavior.

The generator parses exact Codex source revisions and emits one versioned machine
contract with provenance. Human architecture documents explain ownership and
boundaries; generated JSON owns exact current facts for its pinned source.

- Active source/tooling line: **v19 / package 12.0.0**
- Evolution migration anchor: `openai/codex@6af345407d9c2a568da9d01b6c4b81a9e61495c0`
- Checked-in published release snapshot: **v18 / package 11.0.0**
- Current machine contract: **`codex-system-contract/v1`**

The repository name and product scope are broader than the historical Python
package name `codex-wire-audit`. Package/import/CLI renaming is intentionally a
separate migration from semantic ownership; compatibility aliases are not added
implicitly.

## Core rule

```text
exact Codex source / bounded evidence
              ↓
      domain-owned extractor
              ↓
   one versioned system contract
              ↓
 domain compatibility classification
              ↓
       release/evolution
```

A claimed fact must have provenance. Missing evidence remains missing; prose,
fallbacks, old adapters, and runtime observations cannot silently impersonate a
stronger evidence class.

## Layout

- [`toolchain/`](toolchain/) — generator, schemas, profiles, tests, and deterministic release closure
- [`contracts/`](contracts/) — versioned system-contract definitions
- [`release/`](release/) — currently published v18 wheel, sdist, checksums, validation, and attestations
- [`docs/RELEASE_EVOLUTION.md`](docs/RELEASE_EVOLUTION.md) — exact Codex commit-to-commit release authorization
- [`docs/MIGRATION_V2.md`](docs/MIGRATION_V2.md) — domain ownership and branch boundaries for the broader migration
- [`ARCHITECTURE_DOCS_REVIEW.md`](ARCHITECTURE_DOCS_REVIEW.md) — evidence classes, source pins, review status, and known boundaries
- [`toolchain/CONFIG_SURFACE_ARCHITECTURE.md`](toolchain/CONFIG_SURFACE_ARCHITECTURE.md) — generated configuration and config-to-surface graph ownership
- [`PROMPT_ASSEMBLY_AND_CONFIG.md`](PROMPT_ASSEMBLY_AND_CONFIG.md) — prompt/world-state/config layering research
- [`RESPONSES_TRANSPORT_SESSION_HISTORY.md`](RESPONSES_TRANSPORT_SESSION_HISTORY.md) — Responses HTTP/WS turn semantics, prewarm, resume, retry, routing state, Git metadata, and fork/reset behavior
- [`CHATGPT_HOSTED_SERVICES_ARCHITECTURE.md`](CHATGPT_HOSTED_SERVICES_ARCHITECTURE.md) — plugins, Apps, connectors, and hosted MCP planes
- [`LOCAL_STORAGE_AND_ROLLOUT_LAYOUT.md`](LOCAL_STORAGE_AND_ROLLOUT_LAYOUT.md) — `CODEX_HOME`, SQLite, rollout and storage semantics
- [`DESKTOP_ARCHITECTURE.md`](DESKTOP_ARCHITECTURE.md) — Desktop process/bridge ownership and observation boundaries
- [`CODE_MODE_TOOL_ARCHITECTURE.md`](CODE_MODE_TOOL_ARCHITECTURE.md) — tool exposure and Code Mode ownership
- [`SESSION_THREAD_TURN_LIFECYCLE_SLIDES.md`](SESSION_THREAD_TURN_LIFECYCLE_SLIDES.md) — session/thread/turn lifecycle model
- [`FORK_PAGINATION_AND_AGENT_TOPOLOGY_SLIDES.md`](FORK_PAGINATION_AND_AGENT_TOPOLOGY_SLIDES.md) — lineage, pagination, subagent control, and residency

The architecture notes intentionally do not copy rapidly changing setting or API
catalogs. Use generated machine artifacts for exact names, types, defaults,
constraints, source identity, and graph links.

## Domain-owned migration

Migration toward the next contract keeps branch and semantic ownership aligned:

```text
<domain-path>/<type>/<description>
```

Examples:

```text
release/evolution/feat/exact-codex
contract/prompt/feat/context-instructions
contract/policy/feat/execution-authority
contract/plugin/feat/runtime-capabilities
contract/environment/feat/execution-context
contract/routing/feat/proxy-network
```

The complete prefix before the final two segments is one domain. Slash spelling
never creates Git ancestry. See [`docs/MIGRATION_V2.md`](docs/MIGRATION_V2.md).

## Install for development

```bash
python -m pip install --constraint toolchain/ci/constraints.txt \
  -e './toolchain[test]'
```

## Generate the system report

```bash
codex-wire-audit --json \
  --repo-root /path/to/codex \
  --coverage-profile hybrid_v19 \
  --output report.json \
  --emit-system-contract system-contract.json \
  --emit-config-schema config-schema.json \
  --emit-surface-graph config-surface-graph.json
```

Run the focused config/schema integration with:

```bash
python toolchain/tools/check_config_surface.py \
  --codex-root /path/to/codex \
  --output config-surface-result.json \
  --schema-output config-schema.json \
  --graph-output config-surface-graph.json
```

## Machine-readable authority

- `report.json` contains diagnostics plus one canonical `system_contract`.
- Local-storage facts live at `report.system_contract.model.extractors["extractor.local_storage"].data`.
- Configuration facts and their graph live at `report.system_contract.model.extractors["extractor.config_effects"].data`.
- Standalone config/schema files are explicit exports, not alternate report authorities.
- Upstream app-server protocol JSON schemas remain field-level authority for session, thread, turn, item, fork, and pagination RPC shape until their native system-contract domain is complete.

The current v1 contract remains explicitly hybrid. Repository/product renaming
does not claim that prompt, plugin, policy, environment, routing, MCP, Responses,
app-server, and runtime-conformance domains have all been canonicalized.

## Exact Codex evolution releases

New release decisions must be based on an exact Codex commit interval, not on a
generator edit alone.

```bash
python toolchain/tools/codex_evolution_release.py plan \
  --from-codex-root /work/codex-before \
  --to-codex-root /work/codex-after \
  --previous-version 12.0.0 \
  --plan-output release-plan.json
```

The planner rejects dirty/shallow evidence, proves ancestry, generates both
contracts with the same generator/profile, computes semantic evolution, and
produces an integrity-bound SemVer recommendation. The same exact evidence can
then authorize the existing deterministic closure builder:

```bash
python toolchain/tools/codex_evolution_release.py release \
  --from-codex-root /work/codex-before \
  --to-codex-root /work/codex-after \
  --previous-version 12.0.0 \
  --plan-output release-plan.json \
  --output-dir release_next
```

Publication is allowed only when the package release spec names the same exact
Codex target commit and the same evolution-derived package version. See
[`docs/RELEASE_EVOLUTION.md`](docs/RELEASE_EVOLUTION.md).

`toolchain/tools/release_pipeline.py` remains the low-level deterministic build,
verification, assembly, and atomic publication engine. It does not own semantic
release authorization.

## Published artifacts versus source

The source tree and package metadata are v19 / 12.0.0. The checked-in
[`release/`](release/) directory is still the verified v18 / 11.0.0 release.
Do not treat source migration or passing CI as publication.

## Canonical migrated semantics

The generated `codex-system-contract/v1` model owns migrated extractor facts.
The API deliberately avoids duplicate configuration/storage representations.
See the [contract guide](contracts/codex-system-contract/v1/README.md) and
[baseline review](CANONICAL_REVIEW.md). Source, schema, coverage, exact-byte
pinned integration, and release closure are checked by the root-level read-only
`canonical-proof` workflow.
