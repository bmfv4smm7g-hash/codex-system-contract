# Codex System Contract migration boundaries

The repository product is **Codex System Contract**. Canonicalization is domain-owned; do not create one giant “Codex everything” extractor.

## Branch grammar

Every migration branch uses the repository contract:

```text
<domain-path>/<type>/<description>
```

The complete prefix before the final two segments is one exact domain. Prefixes are classification, not ancestry branches.

Representative domain work includes:

```text
release/evolution/feat/exact-codex
contract/config/feat/native-effect-closure
contract/prompt/feat/context-instructions
contract/policy/feat/execution-authority
contract/plugin/feat/runtime-capabilities
contract/environment/feat/execution-context
contract/routing/feat/proxy-network
contract/mcp/feat/tool-projection
contract/responses/feat/request-events
contract/app-server/feat/rpc-lifecycle
runtime/conformance/feat/observed-contracts
```

A branch may update shared schemas or graph composition only when required by its owned domain and must keep the domain facts in that domain's extractor/classifier.

## Ownership

| Domain | Owns | Does not own |
| --- | --- | --- |
| `release/evolution` | exact Codex commit pair, ancestry, semantic release classification, SemVer recommendation, release authorization | interpreting prompt/plugin/policy semantics |
| `contract/config` | generated config shape, config-to-surface effects, canonical config graph composition | runtime observation or unrelated domain semantics |
| `contract/prompt` | base/developer/user instruction sources, AGENTS, skills, memories, world-state composition and deltas | execution permissions or network routing |
| `contract/policy` | permission profile, approval policy, sandbox/trust/managed authority | shell/environment facts not used as policy |
| `contract/plugin` | plugin load/discovery, capability summaries, Apps/connectors and plugin-owned contributions | generic MCP transport mechanics |
| `contract/environment` | cwd/workspace, process/shell environment, PATH/terminal and environment selection | proxy routing policy |
| `contract/routing` | provider and ChatGPT endpoint planes, proxy selection, redirects, transport routing | plugin discovery semantics |
| `contract/mcp` | MCP server configuration, tool filtering/projection, model-visible MCP exposure | plugin marketplace/control plane |
| `contract/responses` | Responses/Lite request and event semantics | app-server RPC lifecycle |
| `contract/app-server` | app-server RPC requests/events/elicitation/thread-turn operations | model-provider wire semantics |
| `runtime/conformance` | bounded observed behavior tied to exact report/build/platform/account/conditions | converting observations into universal source facts |

## Shared rule

```text
source/evidence -> domain extractor -> versioned system contract -> domain compatibility classifier
                                                            -> release/evolution
```

Deterministic parsing, normalization, comparison, and release decisions belong in code. Skill/docs prose stays concise and explains ownership, evidence class, and failure boundaries.

## Current state

`codex-system-contract/v1` is the current emitted machine contract. Its **static model** is canonical: source-derived domain extractors compose the system contract, the frozen v10 renderer is compatibility-only, and `legacy_machine_reconstruction_remaining` is false.

Full observed proof is deliberately separate. `codex_wire_full` still requires bounded `runtime_conformance` evidence tied to the exact static report and source/build identity. Static source or fixture evidence must not be promoted into a runtime observation merely to make the profile complete.
