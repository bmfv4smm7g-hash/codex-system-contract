# Codex wire audit v19 maintainability metrics

The enforced scope now includes both the installable package and the release scripts. This closes the former blind spot where an oversized or highly coupled publisher could pass while package-only metrics remained green.

| Metric | Frozen v10 baseline | Active package | Active release tools | Combined enforced scope |
| --- | ---: | ---: | ---: | ---: |
| Python modules | 3 | 61 | 12 | 73 |
| Physical Python lines | 12,671 | 13,034 | 3,347 | 16,381 |
| Largest module | 5,016 | 581 | 496 | 581 |
| Largest function | 1,254 | 213 | 174 | 213 |
| Highest complexity | not measured | 41 | 36 | 41 |
| Maximum module fan-out | not measured | 10 | 8 | 10 |
| Internal import cycles | not measured | 0 | 0 | 0 |

Largest combined module: **`codex_wire_audit/metadata_history.py`** (581 lines). Largest combined function: **`from_legacy_maps`** (213 lines).

## Generated maintenance assets

- Source registry entries: **125** (16 required, 109 optional).
- Strict schemas: **20**, including **1** release-spec schema.
- Metadata history: **7 keys**, **19 states**, **10 versions**, **9 transitions**.
- Regression test methods: **238**.
- Combined source digest: `45ea70d2a2ac092532ad62ef63be0c8fd7a30b0abc57cc3de4aa407efcaea562`.

## Enforced budgets

- Module ≤ 600 lines: **true**.
- Function ≤ 200 lines: **false**.
- Complexity ≤ 45: **true**.
- Module fan-out ≤ 10: **true**.
- Internal import cycles forbidden: **true**.
