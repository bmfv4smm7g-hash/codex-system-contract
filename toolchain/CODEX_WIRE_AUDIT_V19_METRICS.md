# Codex wire audit v19 maintainability metrics

The enforced scope now includes both the installable package and the release scripts. This closes the former blind spot where an oversized or highly coupled publisher could pass while package-only metrics remained green.

| Metric | Frozen v10 baseline | Active package | Active release tools | Combined enforced scope |
| --- | ---: | ---: | ---: | ---: |
| Python modules | 3 | 74 | 12 | 86 |
| Physical Python lines | 12,671 | 18,582 | 3,347 | 21,929 |
| Largest module | 5,016 | 595 | 496 | 595 |
| Largest function | 1,254 | 203 | 174 | 203 |
| Highest complexity | not measured | 41 | 36 | 41 |
| Maximum module fan-out | not measured | 10 | 8 | 10 |
| Internal import cycles | not measured | 0 | 0 | 0 |

Largest combined module: **`codex_wire_audit/extractors/responses_protocol.py`** (595 lines). Largest combined function: **`ResponsesRequestExtractor.extract`** (203 lines).

## Generated maintenance assets

- Source registry entries: **163** (16 required, 147 optional).
- Strict schemas: **33**, including **1** release-spec schema.
- Metadata history: **7 keys**, **19 states**, **10 versions**, **9 transitions**.
- Regression test methods: **321**.
- Combined source digest: `5a352cd1c936e2e028fd6d81d768374c0414d2e4c75e47f68f866c3cc971b88b`.

## Enforced budgets

- Module ≤ 600 lines: **true**.
- Function ≤ 200 lines: **false**.
- Complexity ≤ 45: **true**.
- Module fan-out ≤ 10: **true**.
- Internal import cycles forbidden: **true**.
