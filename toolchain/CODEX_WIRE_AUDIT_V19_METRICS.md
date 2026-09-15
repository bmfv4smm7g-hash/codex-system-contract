# Codex wire audit v19 maintainability metrics

The enforced scope now includes both the installable package and the release scripts. This closes the former blind spot where an oversized or highly coupled publisher could pass while package-only metrics remained green.

| Metric | Frozen v10 baseline | Active package | Active release tools | Combined enforced scope |
| --- | ---: | ---: | ---: | ---: |
| Python modules | 3 | 68 | 12 | 80 |
| Physical Python lines | 12,671 | 15,877 | 3,347 | 19,224 |
| Largest module | 5,016 | 581 | 496 | 581 |
| Largest function | 1,254 | 199 | 174 | 199 |
| Highest complexity | not measured | 41 | 36 | 41 |
| Maximum module fan-out | not measured | 10 | 8 | 10 |
| Internal import cycles | not measured | 0 | 0 | 0 |

Largest combined module: **`codex_wire_audit/metadata_history.py`** (581 lines). Largest combined function: **`build_attestation`** (199 lines).

## Generated maintenance assets

- Source registry entries: **142** (16 required, 126 optional).
- Strict schemas: **29**, including **1** release-spec schema.
- Metadata history: **7 keys**, **19 states**, **10 versions**, **9 transitions**.
- Regression test methods: **287**.
- Combined source digest: `1dec940e4e9e30337d3ff44f1bce80d5cfa9cb0e1edcc12ace2a359d4f3adcad`.

## Enforced budgets

- Module ≤ 600 lines: **true**.
- Function ≤ 200 lines: **true**.
- Complexity ≤ 45: **true**.
- Module fan-out ≤ 10: **true**.
- Internal import cycles forbidden: **true**.
