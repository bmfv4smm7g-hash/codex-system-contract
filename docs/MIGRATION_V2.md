# Codex System Contract migration boundaries

The repository product is **Codex System Contract**. Migration toward the next canonical contract remains domain-owned; do not create one giant “Codex everything” extractor.

## Branch grammar

Every migration branch uses the repository contract:

```text
<domain-path>/<type>/<description>
```

The complete prefix before the final two segments is one exact domain. Prefixes are classification, not ancestry branches.

The release-evolution work is therefore:

```text
release/evolution/feat/exact-codex
```

Future canonicalization work should stay in separate owning domains, for example:

```text
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
| `contract/prompt` | base/developer/user instruction sources, AGENTS, skills, memories, world-state composition and deltas | execution permissions or network routing |
| `contract/policy` | permission profile, approval policy, sandbox/trust/managed authority | shell/environment facts not used as policy |
| `contract/plugin` | plugin load/discovery, capability summaries, Apps/connectors and plugin-owned contributions | generic MCP transport mechanics |
| `contract/environment` | cwd/workspace, process/shell environment, PATH/terminal and environment selection | proxy routing policy |
| `contract/routing` | provider and ChatGPT endpoint planes, proxy selection, redirects, transport routing | plugin discovery semantics |
| `contract/mcp` | MCP server configuration, tool filtering/projection, model-visible MCP exposure | plugin marketplace/control plane |
| `contract/responses` | Responses/Lite request and event semantics | app-server RPC lifecycle |
| `contract/app-server` | app-server RPC requests/events/elicitation/thread-turn operations | model-provider wire semantics |
| `runtime/conformance` | bounded observed behavior tied to exact build/platform/account/conditions | converting observations into universal source facts |

## Shared rule

```text
source/evidence -> domain extractor -> versioned system contract -> domain compatibility classifier
                                                            -> release/evolution
```

Deterministic parsing, normalization, comparison, and release decisions belong in code. Skill/docs prose stays concise and explains ownership, evidence class, and failure boundaries.

The current `codex-system-contract/v1` remains the emitted machine contract until the new domains are actually canonical. The repository rename does not pretend v2 is complete.
