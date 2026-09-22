# Codex wire audit v19 maintainability metrics

The enforced scope now includes both the installable package and the release scripts. This closes the former blind spot where an oversized or highly coupled publisher could pass while package-only metrics remained green.

| Metric | Frozen v10 baseline | Active package | Active release tools | Combined enforced scope |
| --- | ---: | ---: | ---: | ---: |
| Python modules | 3 | 74 | 12 | 86 |
| Physical Python lines | 12,671 | 18,476 | 3,347 | 21,823 |
| Largest module | 5,016 | 595 | 496 | 595 |
| Largest function | 1,254 | 200 | 174 | 200 |
| Highest complexity | not measured | 41 | 36 | 41 |
| Maximum module fan-out | not measured | 10 | 8 | 10 |
| Internal import cycles | not measured | 0 | 0 | 0 |

Largest combined module: **`codex_wire_audit/extractors/responses_protocol.py`** (595 lines). Largest combined function: **`build_history_mutation`** (200 lines).

## Generated maintenance assets

- Source registry entries: **162** (16 required, 146 optional).
- Strict schemas: **33**, including **1** release-spec schema.
- Metadata history: **7 keys**, **19 states**, **10 versions**, **9 transitions**.
- Regression test methods: **319**.
- Combined source digest: `35fe8e0a24466d54502c921d4b49f3e4c8352e923871dc8143aa46685298f12e`.

## Enforced budgets

- Module ≤ 600 lines: **true**.
- Function ≤ 200 lines: **true**.
- Complexity ≤ 45: **true**.
- Module fan-out ≤ 10: **true**.
- Internal import cycles forbidden: **true**.
