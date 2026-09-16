# Codex wire audit v19 maintainability metrics

The enforced scope now includes both the installable package and the release scripts. This closes the former blind spot where an oversized or highly coupled publisher could pass while package-only metrics remained green.

| Metric | Frozen v10 baseline | Active package | Active release tools | Combined enforced scope |
| --- | ---: | ---: | ---: | ---: |
| Python modules | 3 | 70 | 12 | 82 |
| Physical Python lines | 12,671 | 16,548 | 3,347 | 19,895 |
| Largest module | 5,016 | 581 | 496 | 581 |
| Largest function | 1,254 | 199 | 174 | 199 |
| Highest complexity | not measured | 41 | 36 | 41 |
| Maximum module fan-out | not measured | 10 | 8 | 10 |
| Internal import cycles | not measured | 0 | 0 | 0 |

Largest combined module: **`codex_wire_audit/metadata_history.py`** (581 lines). Largest combined function: **`LocalStorageExtractor.extract`** (199 lines).

## Generated maintenance assets

- Source registry entries: **155** (16 required, 139 optional).
- Strict schemas: **32**, including **1** release-spec schema.
- Metadata history: **7 keys**, **19 states**, **10 versions**, **9 transitions**.
- Regression test methods: **299**.
- Combined source digest: `88fae98a501ee6a9f071e25b22da49e302bfded788e43d291fc3997475589257`.

## Enforced budgets

- Module ≤ 600 lines: **true**.
- Function ≤ 200 lines: **true**.
- Complexity ≤ 45: **true**.
- Module fan-out ≤ 10: **true**.
- Internal import cycles forbidden: **true**.
