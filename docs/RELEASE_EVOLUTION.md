# Exact Codex evolution release contract

This repository does not treat generator edits by themselves as a reason to publish a new Codex system-contract release. A release starts with two exact `openai/codex` commits and proves the semantic evolution between them.

## Inputs

The release owner consumes:

- a clean, complete-history checkout at the previous reviewed Codex commit;
- a clean, complete-history checkout at the candidate Codex commit;
- the previous stable package version;
- the current generator and its domain-owned semantic classifiers.

The planner verifies both full commit SHAs, rejects dirty or shallow evidence, and proves that the previous commit is an ancestor of the candidate commit. It then generates both contracts with the same generator and coverage profile. The candidate generation uses the previous report as its semantic baseline.

```text
exact Codex A
    -> deterministic contract A

exact Codex B
    -> deterministic contract B

A + B
    -> semantic diff
    -> release classification
    -> exact release plan
```

A release plan binds the exact commit pair, exact source-set hashes, canonical contract identities, semantic diff, extractor-level fallback classification, SemVer decision, and a canonical SHA-256 over the plan itself.

## SemVer policy

`exact-codex-semver/v1` is deliberately fail-closed.

| Evolution | Release level |
| --- | --- |
| Exact Codex commit changed, canonical semantics unchanged | patch |
| Domain-classified additive/attention change | minor |
| New or newly complete canonical extractor | minor |
| Domain-classified breaking change | major |
| Removed/regressed extractor | major |
| Existing extractor changed without a finer domain classifier | major |
| Contract schema or coverage-profile identity changed | major |
| Exact Codex commit did not change | no release |

An extractor owns its own compatibility semantics. The release layer does not reinterpret domain facts. Today the existing turn-metadata semantic classifier is trusted directly. Other existing extractors are conservative-major until their own classifiers are added.

## Migration anchor

The active source line remains package `12.0.0` at reviewed Codex commit:

```text
openai/codex@6af345407d9c2a568da9d01b6c4b81a9e61495c0
```

That pair is the migration anchor for future evolution-driven releases. The checked-in v18 / package 11.0.0 directory remains historical published evidence and is not rewritten.

## Plan

```bash
python toolchain/tools/codex_evolution_release.py plan \
  --from-codex-root /work/codex-before \
  --to-codex-root /work/codex-after \
  --from-commit 6af345407d9c2a568da9d01b6c4b81a9e61495c0 \
  --to-commit <reviewed-full-sha> \
  --previous-version 12.0.0 \
  --coverage-profile hybrid_v19 \
  --plan-output release-plan.json
```

The tool generates both reports itself. A caller cannot authorize a release by hand-editing only a semantic-diff file.

## Release

The same command can authorize and call the existing low-level release closure:

```bash
python toolchain/tools/codex_evolution_release.py release \
  --from-codex-root /work/codex-before \
  --to-codex-root /work/codex-after \
  --previous-version 12.0.0 \
  --plan-output release-plan.json \
  --output-dir release_next
```

Before publication it requires:

```text
release_spec.reviewed_codex_commit == plan.evolution.to.commit
release_spec.package_version        == plan.release.recommended_version
release_spec.generator_version      == release_spec.package_version
```

The existing `tools/release_pipeline.py` remains the deterministic closure builder. It does not own the decision that a release is semantically justified. New release automation should enter through `codex_evolution_release.py`.

## Boundary

This mechanism owns release authorization only. It does not own prompt, plugin, policy, environment, routing, MCP, storage, or protocol extraction. Those domains expose semantic evidence and compatibility classification; release/evolution consumes their outputs.
