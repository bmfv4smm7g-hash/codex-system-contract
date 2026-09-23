# Codex wire audit v19 maintainability metrics

The enforced scope now includes both the installable package and the release scripts. This closes the former blind spot where an oversized or highly coupled publisher could pass while package-only metrics remained green.

| Metric | Frozen v10 baseline | Active package | Active release tools | Combined enforced scope |
| --- | ---: | ---: | ---: | ---: |
| Python modules | 3 | 74 | 12 | 86 |
| Physical Python lines | 12,671 | 18,592 | 3,347 | 21,939 |
| Largest module | 5,016 | 606 | 496 | 606 |
| Largest function | 1,254 | 205 | 174 | 205 |
| Highest complexity | not measured | 41 | 36 | 41 |
| Maximum module fan-out | not measured | 10 | 8 | 10 |
| Internal import cycles | not measured | 0 | 0 | 0 |

Largest combined module: **`codex_wire_audit/extractors/responses_protocol.py`** (606 lines). Largest combined function: **`ResponsesRequestExtractor.extract`** (205 lines).

## Generated maintenance assets

- Source registry entries: **163** (16 required, 147 optional).
- Strict schemas: **33**, including **1** release-spec schema.
- Metadata history: **7 keys**, **19 states**, **10 versions**, **9 transitions**.
- Regression test methods: **321**.
- Combined source digest: `b6b086bfcdd5f19d960c90993d77fb28083a027c9e0f39fa59c9f9ec74d7af10`.

## Enforced budgets

- Module ≤ 600 lines: **false**.
- Function ≤ 200 lines: **false**.
- Complexity ≤ 45: **true**.
- Module fan-out ≤ 10: **true**.
- Internal import cycles forbidden: **true**.
