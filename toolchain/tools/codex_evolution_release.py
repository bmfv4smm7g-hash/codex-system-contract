#!/usr/bin/env python3
"""Plan or build a release from exact openai/codex commit-to-commit evolution."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from codex_wire_audit.release_evolution import (
    ReleaseEvolutionError,
    build_release_plan,
    validate_plan_against_release_spec,
)
from tools.release_pipeline import release as build_release
from tools.release_spec import load_release_spec

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "openai/codex"


def _git(repo: Path, *args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    result = subprocess.run(
        ["git", "--no-pager", "-C", str(repo), *args],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=30,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    raise ReleaseEvolutionError(f"git {args[0]} failed for {repo}")


def _exact_checkout(repo: Path, expected: str | None, *, label: str) -> str:
    root = repo.resolve(strict=True)
    if not root.is_dir():
        raise ReleaseEvolutionError(f"{label} Codex root is not a directory")
    if _git(root, "rev-parse", "--is-shallow-repository") != "false":
        raise ReleaseEvolutionError(f"{label} Codex checkout must contain complete history")
    head = _git(root, "rev-parse", "HEAD")
    if expected is not None and head != expected:
        raise ReleaseEvolutionError(
            f"{label} Codex HEAD mismatch: expected {expected}, observed {head}"
        )
    if len(head) != 40 or any(character not in "0123456789abcdef" for character in head):
        raise ReleaseEvolutionError(f"{label} Codex HEAD is not a full lowercase SHA")
    if _git(root, "status", "--porcelain=v1"):
        raise ReleaseEvolutionError(f"{label} Codex checkout is dirty")
    _git(root, "cat-file", "-e", f"{head}^{{commit}}")
    return head


def _verify_ancestry(target_root: Path, before: str, after: str) -> None:
    _git(target_root, "cat-file", "-e", f"{before}^{{commit}}")
    _git(target_root, "cat-file", "-e", f"{after}^{{commit}}")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    result = subprocess.run(
        ["git", "--no-pager", "-C", str(target_root), "merge-base", "--is-ancestor", before, after],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode == 1:
        raise ReleaseEvolutionError("before Codex commit is not an ancestor of after Codex commit")
    if result.returncode != 0:
        raise ReleaseEvolutionError("Codex ancestry could not be proven from the target checkout")


def _generate_report(
    codex_root: Path,
    commit: str,
    output: Path,
    *,
    profile: str,
    baseline_report: Path | None = None,
) -> None:
    command = [
        sys.executable,
        "-m",
        "codex_wire_audit.cli",
        "--repo",
        REPOSITORY,
        "--repo-root",
        str(codex_root),
        "--ref",
        commit,
        "--source-commit",
        commit,
        "--coverage-profile",
        profile,
        "--format",
        "canonical-json",
        "--output",
        str(output),
        "--fail-on",
        "error",
        "--fail-on-semantic-change",
        "never",
        "--deterministic",
    ]
    if baseline_report is not None:
        command.extend(["--baseline-report", str(baseline_report)])
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONHASHSEED": "0",
            "LC_ALL": "C",
        }
    )
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseEvolutionError(
            "exact Codex contract generation failed: " + (result.stderr.strip() or "unknown error")
        )


def _load_object(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseEvolutionError(f"cannot read generated report {path}: {error}") from error
    if not isinstance(value, Mapping):
        raise ReleaseEvolutionError("generated report root is not an object")
    return value


def _plan(args: argparse.Namespace) -> dict[str, Any]:
    before_root = Path(args.from_codex_root).resolve(strict=True)
    after_root = Path(args.to_codex_root).resolve(strict=True)
    before = _exact_checkout(before_root, args.from_commit, label="before")
    after = _exact_checkout(after_root, args.to_commit, label="after")
    if before == after:
        raise ReleaseEvolutionError("release requires two distinct Codex commits")
    _verify_ancestry(after_root, before, after)

    with tempfile.TemporaryDirectory(prefix="codex-system-evolution-") as temporary_name:
        temporary = Path(temporary_name)
        before_report_path = temporary / "before.json"
        after_report_path = temporary / "after.json"
        _generate_report(before_root, before, before_report_path, profile=args.coverage_profile)
        _generate_report(
            after_root,
            after,
            after_report_path,
            profile=args.coverage_profile,
            baseline_report=before_report_path,
        )
        plan = build_release_plan(
            _load_object(before_report_path),
            _load_object(after_report_path),
            previous_version=args.previous_version,
        )
    if args.plan_output:
        output = Path(args.plan_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return plan


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subparsers = root.add_subparsers(dest="command", required=True)
    for name in ("plan", "release"):
        command = subparsers.add_parser(name)
        command.add_argument("--from-codex-root", required=True)
        command.add_argument("--to-codex-root", required=True)
        command.add_argument("--from-commit")
        command.add_argument("--to-commit")
        command.add_argument("--previous-version", required=True)
        command.add_argument("--coverage-profile", default="hybrid_v19")
        command.add_argument("--plan-output")
        if name == "release":
            command.add_argument("--output-dir")
            command.add_argument("--legacy-dir")
            command.add_argument("--review-diff")
            command.add_argument("--replace", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    plan = _plan(args)
    if args.command == "plan":
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    spec = load_release_spec(ROOT)
    validate_plan_against_release_spec(plan, spec)
    output = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else ROOT / f"release_{spec['release']['series']}"
    )
    log: list[str] = []
    phase = {"value": "evolution_authorized"}
    result = build_release(
        output=output,
        legacy_dir=Path(args.legacy_dir).resolve() if args.legacy_dir else None,
        review_diff=Path(args.review_diff).resolve() if args.review_diff else None,
        replace=args.replace,
        log=log,
        phase=phase,
    )
    print(json.dumps({"evolution_plan": plan, "release": result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ReleaseEvolutionError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
