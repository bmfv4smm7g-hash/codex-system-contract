# Responses transport, session state, retry, resume, and fork lifecycle

Source-review note for **`openai-codex-rust-v0.155.0-alpha.4`**.

This document collects end-to-end behaviors that are easy to miss when reading
individual protocol schemas or extractor outputs in isolation. It is intended to
complement the generated system contract, not replace it. Exact field/type facts
remain owned by the machine-readable contract for its pinned Codex revision.

The repository already captured several pieces of this behavior independently:

- WebSocket v2 startup prewarm with `generate=false`;
- `previous_response_id` incremental continuation and full-request fallback;
- `x-codex-turn-state` as server-owned, same-turn sticky routing state;
- `previous_response_not_found` as a retryable WebSocket error that poisons the
  current socket;
- user-fork versus subagent history topology.

The sections below tie those pieces together and add the missing edge cases:
non-Git workspace metadata omission, overload retry asymmetry, HTTPS turn/request
semantics, and the routing-state consequences of fork/rewind.

---

## 1. The four state layers

Do not collapse these into one “session” concept:

```text
thread / conversation history
    durable logical transcript and lineage

Codex turn
    one user-driven agent execution interval; may contain many model samplings

ModelClientSession
    turn-scoped network/routing state, including x-codex-turn-state

transport connection
    HTTP request/SSE connection or reusable Responses WebSocket
```

A single Codex turn can therefore look like:

```text
turn
  sampling #1 -> tool call
  local tool execution
  sampling #2 -> tool call
  local tool execution
  sampling #3 -> final assistant answer
```

The turn ends only when the agent loop ends. A Responses request is one sampling
step, not necessarily one Codex turn.

---

## 2. HTTPS: one turn can contain multiple `/responses` requests

The HTTPS/SSE path does not use `previous_response_id` continuation. The HTTP
request type contains the current model-visible `input`, and each later sampling
step rebuilds the prompt from committed session history.

Conceptually:

```text
Turn U

POST /responses              sampling #1
  input = history + user
  x-codex-turn-state absent initially
       ↓
SSE -> function_call
       ↓
server returns x-codex-turn-state = A
       ↓
execute tool locally
       ↓
POST /responses              sampling #2
  input = history + user + model tool call + tool result
  x-codex-turn-state = A
       ↓
SSE -> another tool call or final answer
```

`x-codex-turn-state` is therefore the application-level same-turn routing
continuity mechanism. It is not the definition of the turn and it is not a
thread/session identifier.

### HTTP transport construction

In this source snapshot, the Responses HTTP path builds a route-specific
`ReqwestTransport` through `build_api_transport()`, which calls
`create_client_for_route()`. The client factory owns proxy policy, while each
transport build creates an HTTP client for that request path. Do not model a
Codex turn as “one dedicated TCP connection kept alive until turn completion.”
The semantic contract is the turn-state token and rebuilt prompt/history, not a
particular socket.

---

## 3. `x-codex-turn-state` is turn-scoped, not thread-scoped

`ModelClient::new_session()` creates a fresh `ModelClientSession` for every turn
with:

```text
turn_state = empty OnceLock
```

A healthy WebSocket transport object may be taken from the model client's cached
WebSocket session and reused by the next turn, but the routing token itself is
fresh.

Therefore this is valid:

```text
same thread

Turn U1
  physical WS = W
  x-codex-turn-state = A

Turn U2
  physical WS may still be W
  x-codex-turn-state starts EMPTY
  server may assign B
```

Replaying `A` into `U2` would violate the client/server same-turn contract.

### HTTPS acquisition

For HTTP/SSE, the server supplies the token in response headers. Codex stores it
and sends the same value on subsequent Responses requests in that turn.

### WebSocket acquisition

For Responses WebSocket requests, Codex places the stored token into
`response.create.client_metadata["x-codex-turn-state"]`.

The general WebSocket API is capable of reading the token from the HTTP Upgrade
response, but the normal `ModelClient::connect_websocket()` path in this source
snapshot passes `turn_state = None` to the connector and builds handshake headers
without turn-state. The ordinary Codex path therefore learns turn-state from a
Responses metadata event, then replays it on later `response.create` frames.

---

## 4. Startup WebSocket prewarm

When Responses WebSocket is enabled, session startup schedules a model prewarm.
It constructs a startup turn context, builds tools/configuration, and builds a
prompt with:

```text
input = []
```

Then it creates a fresh `ModelClientSession` and sends a WebSocket
`response.create` warmup with `generate=false`. `prewarm_websocket()` waits until
`response.completed` before considering the prewarm ready.

The source comment states the immediate purpose precisely:

```text
Prewarm establishes the request baseline before the first turn can change effort.
```

Operationally this can move several costs off the first real inference path:

```text
open WS
+ establish request-property baseline
+ receive a reusable response id
+ allow server routing/turn metadata to be established
+ avoid model generation because generate=false
```

The initial prewarm cannot replay an already-known turn-state because the
turn-scoped cell begins empty. The server may return turn-state during prewarm
metadata, after which the first real request can already include that sticky
routing token.

---

## 5. Resume: prewarm happens before restored history is recorded

Startup prewarm uses empty input. Resume history is reconstructed separately.
Consequently, the first real request after resume can use the prewarm response as
its WebSocket baseline while adding the entire reconstructed model-visible
history as the incremental suffix.

Conceptually:

```text
resume thread
   ↓
WS prewarm
response.create
  generate = false
  input = []
   ↓
response.completed id = W0
   ↓
restore persisted/compacted model-visible history
   ↓
user sends new input
   ↓
response.create
  previous_response_id = W0
  input = restored history + new user item
```

This “entire history” means the history reconstructed for the model. It does not
necessarily mean every literal rollout record. Compaction, filtering, rollback,
and reconstruction rules can replace or omit older raw records.

The delta optimization is only legal when non-input request properties still
match and the current input extends the previous request plus server-returned
response items. Otherwise Codex omits `previous_response_id` and sends the full
current input.

---

## 6. Responses Lite / incremental continuation

The WebSocket request builder checks the previous completed response and the
previous request. If request properties match and the new logical input extends
the previous logical state, it sends:

```text
previous_response_id = previous completed response id
input = only the incremental suffix
```

Otherwise it sends a full request:

```text
previous_response_id omitted
input = full current model-visible input
```

The optimization is therefore an opportunistic compression of a logical request.
The logical agent state remains reconstructible by Codex from committed history.

---

## 7. `previous_response_not_found`: new WS, full retry, no second prewarm

A wrapped WebSocket error with code:

```text
previous_response_not_found
```

maps to `ApiError::Retryable`.

The failed WebSocket stream is terminal for that socket. The stream holder is
removed/dropped, which causes the next retry to open a new/reopened WebSocket.
The sampling loop then rebuilds the prompt from committed session history.
Because there is no completed `LastResponse` available from the failed attempt,
`prepare_websocket_request()` cannot produce an incremental continuation and the
retry becomes a full request.

Sequence:

```text
WS #1
  prewarm -> W0
  response.create(previous_response_id=W0, delta)
       ↓
  error: previous_response_not_found
       ↓
  failed WS discarded

WS #2
  response.create
    previous_response_id omitted
    input = FULL current prompt/history
    generate = normal
```

There is **no second `generate=false` startup prewarm** between the error and the
full retry. The full real request itself establishes the new response baseline.

After it completes with response id `R1`, later requests can again use Lite
continuation from `R1`.

---

## 8. Retryable stream failures versus terminal overload

Codex has two different retry layers that can make superficially similar
“upstream busy” failures behave differently.

### HTTP status-level request retry

The provider defaults in this snapshot are:

```text
request_max_retries = 4
stream_max_retries  = 5
```

The HTTP transport retry policy retries server-error status codes before the
higher-level Responses body is interpreted semantically. Therefore an HTTP 503
whose body says `server_is_overloaded` can exhaust configured HTTP request
retries first.

The source test demonstrates:

```text
request_max_retries = 2
HTTP 503 server_is_overloaded
=> 3 total POST attempts
=> one final ServerOverloaded error
```

### Streamed/SSE or WebSocket semantic overload

Once an established stream reports an error body/event whose code is:

```text
server_is_overloaded
slow_down
```

it maps to `ServerOverloaded`.

`CodexErrorDetails::ServerOverloaded` is explicitly **not retryable**, so the
sampling stream retry loop does not reconnect, retry, or fall back to HTTP for
that semantic error.

The WebSocket integration tests explicitly require:

```text
prewarm
+ one real request returning server_is_overloaded
= terminal turn error
```

Even nested retry advice does not currently change that behavior; the source has
a TODO to respect `Retry-After` for this case.

### Generic retryable stream failure

Other stream failures such as connection failures, ordinary unexpected statuses,
`previous_response_not_found`, or
`websocket_connection_limit_reached` can enter the sampling retry loop.

The loop:

```text
rebuilds prompt from committed history
waits with backoff
retries the sampling request
may create a new WS because the failed stream poisoned the old one
```

After configured WebSocket stream retries are exhausted, Codex can switch that
session to HTTPS fallback when fallback is available. The first WebSocket retry
notification is intentionally hidden in release builds to reduce transient UI
noise, which explains cases where a request appears to recover without visibly
showing “Reconnecting... 1/N”.

---

## 9. Non-Git working directory and `client_metadata`

A non-Git cwd does **not** suppress Responses `client_metadata` as a whole.

Git enrichment calls `git_workspaces()`. If no repository root is discovered:

```text
git_workspaces() -> empty BTreeMap
```

The enrichment state only stores a workspace map when it is non-empty. During
turn-metadata serialization, `non_empty_workspaces()` converts an empty map to
`None`, and the field uses `skip_serializing_if = Option::is_none`.

Therefore the wire behavior is:

```text
client_metadata exists
x-codex-turn-metadata exists
workspaces property is OMITTED
```

It is not:

```text
"workspaces": {}
"workspaces": null
"git": false
```

This means absence of `workspaces` alone does not prove “not a Git repo”; from the
wire alone it can also represent enrichment being skipped/unavailable/not yet
materialized.

Startup prewarm uses a startup turn context with Git enrichment skipped, whereas
regular local turns can request fresh Git enrichment.

---

## 10. User fork / rewind: fresh routing state with explicit lineage

A normal user-visible fork creates a fresh thread/root runtime rather than
continuing the parent's transport state. TUI rewind/backtrack follows the same
fork model.

For a source thread `A` and fork `B`:

```text
A
  thread_id  = A
  session_id = A

fork / rewind
       ↓

B
  thread_id  = B
  session_id = B       # new root tree
  forkedFrom = A
```

The fork does **not** inherit:

```text
parent x-codex-turn-state
parent ModelClientSession
parent cached WebSocket state
parent previous_response_id chain
```

Its first turn begins with a fresh turn-state cell and establishes its own
Responses transport/baseline.

However the fork is not semantically unrelated. Responses turn metadata can carry
lineage fields including:

```text
forked_from_thread_id
forked_from_ordinal_exclusive
```

so the server can know which thread and prefix boundary seeded the fork.

The important contract distinction is:

```text
lineage metadata != inherited sticky routing
```

The client does not require the fork to be routed to the same worker/shard as the
parent. A backend may choose to use lineage for cache/locality affinity, but that
would be a server-side optimization rather than inherited `x-codex-turn-state`.

---

## 11. Subagent forks are different from user forks

A user fork usually starts a new root session tree. A descendant subagent can
have a new thread identity while remaining inside the root's shared agent-control
session tree.

Conceptually:

```text
user fork:
  new thread_id
  new root session_id
  forked_from_thread_id = source
  fresh routing state

subagent:
  new thread_id
  shared root session_id
  parent_thread_id = control parent
  optional forked_from_thread_id = history source
  its own turn-scoped routing state
```

Do not use `session_id`, `parent_thread_id`, and `forked_from_thread_id`
interchangeably. They describe different graphs/scopes.

---

## 12. State reset matrix

| Transition | History | Thread ID | Root session ID | Physical WS | `previous_response_id` chain | `x-codex-turn-state` |
|---|---|---|---|---|---|---|
| next sampling in same turn | extends | same | same | normally reused | reused when eligible | same token |
| retryable WS stream failure | rebuilt from committed history | same | same | failed WS discarded/reopened | full request if no valid completed predecessor | turn token may survive unless ownership resets; new server state can be learned |
| next turn, same thread | retained | same | same | may be cached/reused | transport baseline may be reusable only if request rules allow | **fresh** |
| resume stored thread | reconstructed | same stored thread | same tree identity | startup WS is new for loaded runtime | prewarm can seed new chain | fresh for new turn |
| user fork / rewind | copied/referenced prefix | **new** | **new root** | **new** | **new** | **fresh** |
| descendant subagent | selected inherited/fresh context | new | shared root tree | independent runtime transport | independent chain | fresh per turn |

This matrix is the safest way to reason about apparent “session continuity”: each
state layer has its own lifetime.

---

## 13. Practical proxy/gateway implications

A compatible proxy should preserve these distinctions:

1. Do not treat a missing `workspaces` member as an explicit “not Git” boolean.
2. Do not replay `x-codex-turn-state` across Codex turns or user forks.
3. Do not assume a new physical WebSocket implies a new logical thread.
4. Do not forward an orphan Lite delta to a fresh upstream WS that lacks the
   referenced server-side response chain; recovery must become a full request.
5. `previous_response_not_found` should be allowed to trigger client recovery,
   not be converted into a fake successful continuation.
6. Distinguish HTTP transport-level 5xx retry from streamed semantic overload;
   Codex itself does.
7. Treat fork lineage fields as lineage/cache hints, not proof of routing
   stickiness.

---

## 14. Source map for this review

Primary source paths in `openai-codex-rust-v0.155.0-alpha.4`:

```text
codex-rs/core/src/client.rs
    ModelClientSession creation, turn-state lifetime, WS caching, prewarm,
    request-property matching, previous_response_id continuation, HTTP/WS paths

codex-rs/core/src/session_startup_prewarm.rs
    startup prewarm ordering, empty startup input, prewarm completion wait

codex-rs/core/src/session/turn.rs
    one-turn multi-sampling agent loop and prompt reconstruction on retry

codex-rs/core/src/responses_retry.rs
    stream retry/backoff, UI reconnect notification, WS -> HTTPS fallback

codex-rs/codex-api/src/endpoint/responses_websocket.rs
    wrapped WS error mapping, previous_response_not_found, turn-state metadata

codex-rs/codex-api/src/sse/responses.rs
    response.failed semantic error mapping, server_is_overloaded / slow_down

codex-rs/codex-api/src/api_bridge.rs
    ApiError -> CodexErr semantic mapping

codex-rs/protocol/src/error.rs
    Codex error retryability; ServerOverloaded is terminal

codex-rs/model-provider-info/src/lib.rs
    default request/stream retry counts

codex-rs/core/src/turn_metadata.rs
codex-rs/core/src/responses_metadata.rs
    Git workspace enrichment and omission of empty workspaces

codex-rs/core/src/thread_manager.rs
codex-rs/rollout/src/metadata.rs
    fork lineage and ordinal boundary metadata

codex-rs/core/tests/suite/retry_after.rs
    HTTP overload retry exhaustion and terminal SSE/WS overload tests
```

Related existing repository notes:

```text
PROMPT_ASSEMBLY_AND_CONFIG.md
SESSION_THREAD_TURN_LIFECYCLE_SLIDES.md
FORK_PAGINATION_AND_AGENT_TOPOLOGY_SLIDES.md
toolchain/codex_wire_audit/extractors/responses_transport.py
toolchain/codex_wire_audit/extractors/responses_protocol.py
toolchain/codex_wire_audit/extractors/turn_metadata.py
```
