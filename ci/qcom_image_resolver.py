#!/usr/bin/env python3

# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Validate qcom-deb-images workflow data for LAVA image selection."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


TRUSTED_REPOSITORY = "qualcomm-linux/qcom-deb-images"
TRUSTED_WORKFLOW_PATH = ".github/workflows/build.yml"
TRUSTED_EVENT = "workflow_run"
MAX_BUILD_AGE = timedelta(days=7)
SUPPORTED_SUITES = ("trixie", "forky")
BUILD_URL_RE = re.compile(
    r"https://qli-prod-artifacts\.qualcomm\.com/qcom-prd-gh-artifacts/"
    r"qualcomm-linux/qcom-deb-images/[1-9][0-9]*-[1-9][0-9]*/"
)


@dataclass(frozen=True)
class BuildRun:
    run_id: int
    run_attempt: int
    created_at: datetime
    html_url: str


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"Selected run has an invalid {field}")
    return value


def _parse_created_at(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Selected run has an invalid created_at timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError("Selected run has an invalid created_at timestamp") from error
    return parsed.replace(tzinfo=timezone.utc)


def _is_trusted_run(run: Any) -> bool:
    if not isinstance(run, dict):
        return False
    repository = run.get("head_repository")
    return (
        isinstance(repository, dict)
        and repository.get("full_name") == TRUSTED_REPOSITORY
        and run.get("event") == TRUSTED_EVENT
        and run.get("head_branch") == "main"
        and run.get("conclusion") == "success"
        and run.get("path") == TRUSTED_WORKFLOW_PATH
    )


def validate_run(run: Any, now: datetime) -> BuildRun:
    """Validate a selected run and return its immutable identity."""
    if not _is_trusted_run(run):
        raise ValueError(
            "Selected run does not match the trusted qcom-deb-images Build workflow"
        )

    run_id = _positive_integer(run.get("id"), "run ID")
    run_attempt = _positive_integer(run.get("run_attempt"), "run attempt")
    created_at = _parse_created_at(run.get("created_at"))
    if created_at > now:
        raise ValueError("Selected run has a created_at timestamp in the future")

    age = now - created_at
    if age > MAX_BUILD_AGE:
        raise ValueError(
            f"Selected qcom-deb-images build is older than seven days ({age.days} days)"
        )

    html_url = run.get("html_url")
    if not isinstance(html_url, str) or not html_url.startswith(
        "https://github.com/qualcomm-linux/qcom-deb-images/actions/runs/"
    ):
        raise ValueError("Selected run has an invalid GitHub Actions URL")
    return BuildRun(run_id, run_attempt, created_at, html_url)


def select_latest_run(runs: Iterable[Any], now: datetime) -> BuildRun:
    """Return the newest trusted successful run, rejecting stale selections."""
    candidates = []
    for run in runs:
        if not _is_trusted_run(run):
            continue
        try:
            candidates.append((_parse_created_at(run.get("created_at")), run))
        except ValueError:
            continue
    if not candidates:
        raise ValueError("No qualifying successful qcom-deb-images Build run was found")
    return validate_run(max(candidates, key=lambda candidate: candidate[0])[1], now)


def _flatten_artifacts(payload: Any) -> Iterable[Any]:
    if isinstance(payload, dict):
        artifacts = payload.get("artifacts")
        if isinstance(artifacts, list):
            yield from artifacts
        return
    if isinstance(payload, list):
        for page in payload:
            yield from _flatten_artifacts(page)


def _flatten_workflow_runs(payload: Any) -> Iterable[Any]:
    if isinstance(payload, dict):
        runs = payload.get("workflow_runs")
        if isinstance(runs, list):
            yield from runs
        return
    if isinstance(payload, list):
        for page in payload:
            yield from _flatten_workflow_runs(page)


def select_build_url_artifact(payload: Any) -> int:
    """Return a live build_url artifact ID."""
    for artifact in _flatten_artifacts(payload):
        if (
            isinstance(artifact, dict)
            and artifact.get("name") == "build_url"
            and artifact.get("expired") is False
        ):
            return _positive_integer(artifact.get("id"), "build_url artifact ID")
    raise ValueError("Selected run has no live build_url artifact")


def validate_suite_build(jobs_payload: Any, suite: str) -> None:
    """Ensure the image-producing matrix job for the requested suite succeeded."""
    if suite not in SUPPORTED_SUITES:
        raise ValueError(
            f"Suite {suite!r} is not built by the trusted qcom-deb-images workflow"
        )
    expected_name = (
        f"build ({suite}, default) / "
        f"Build and upload debos recipes ({suite}, default)"
    )
    if not isinstance(jobs_payload, (dict, list)):
        raise ValueError("Selected run has no readable jobs list")
    jobs = list(_flatten_jobs(jobs_payload))
    if not any(
        isinstance(job, dict)
        and job.get("name") == expected_name
        and job.get("conclusion") == "success"
        for job in jobs
    ):
        raise ValueError(
            f"Selected run has no successful {suite} default image build required "
            "by the LAVA templates"
        )


def _flatten_jobs(payload: Any) -> Iterable[Any]:
    if isinstance(payload, dict):
        jobs = payload.get("jobs")
        if isinstance(jobs, list):
            yield from jobs
        return
    if isinstance(payload, list):
        for page in payload:
            yield from _flatten_jobs(page)


def expected_build_url(run_id: int, run_attempt: int) -> str:
    return (
        "https://qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
        f"qualcomm-linux/qcom-deb-images/{run_id}-{run_attempt}/"
    )


def read_build_url_artifact(archive: Path, run: BuildRun) -> str:
    """Read and strictly validate the URL in a downloaded build_url artifact."""
    try:
        with zipfile.ZipFile(archive) as artifact:
            entries = artifact.infolist()
            if len(entries) != 1 or entries[0].filename != "build_url":
                raise ValueError("build_url artifact has an unexpected file layout")
            entry = entries[0]
            if entry.flag_bits & 0x1 or entry.file_size > 4096:
                raise ValueError("build_url artifact is not safely readable")
            content = artifact.read(entry).decode("ascii")
    except (OSError, RuntimeError, UnicodeDecodeError, zipfile.BadZipFile) as error:
        raise ValueError("build_url artifact is unavailable or unreadable") from error

    if content.count("\n") > 1 or (content and not content.endswith("\n")):
        raise ValueError("build_url artifact has invalid contents")
    build_url = content.strip()
    if build_url != expected_build_url(run.run_id, run.run_attempt):
        raise ValueError("build_url artifact does not match the selected immutable run")
    if not BUILD_URL_RE.fullmatch(build_url):
        raise ValueError("build_url artifact does not use the trusted URL format")
    return build_url


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read GitHub API data from {path}") from error


def _write_output(path: Path, **values: object) -> None:
    with path.open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def _current_time() -> datetime:
    return datetime.now(timezone.utc)


def resolve_run(args: argparse.Namespace) -> None:
    payload = _load_json(args.runs_json)
    runs = list(_flatten_workflow_runs(payload))
    if not runs:
        raise ValueError("GitHub API response has no workflow runs")
    run = select_latest_run(runs, _current_time())
    _write_output(
        args.github_output,
        run_id=run.run_id,
        run_attempt=run.run_attempt,
        created_at=run.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        html_url=run.html_url,
    )


def validate_requested_run(args: argparse.Namespace) -> None:
    run = validate_run(_load_json(args.run_json), _current_time())
    _write_output(
        args.github_output,
        run_id=run.run_id,
        run_attempt=run.run_attempt,
        created_at=run.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        html_url=run.html_url,
    )


def validate_suite(args: argparse.Namespace) -> None:
    validate_suite_build(_load_json(args.jobs_json), args.suite)


def extract_build_url(args: argparse.Namespace) -> None:
    run = BuildRun(args.run_id, args.run_attempt, _current_time(), "")
    print(read_build_url_artifact(args.archive, run))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    auto_parser = subparsers.add_parser("resolve-run")
    auto_parser.add_argument("--runs-json", required=True, type=Path)
    auto_parser.add_argument("--github-output", required=True, type=Path)
    auto_parser.set_defaults(handler=resolve_run)

    requested_parser = subparsers.add_parser("validate-requested-run")
    requested_parser.add_argument("--run-json", required=True, type=Path)
    requested_parser.add_argument("--github-output", required=True, type=Path)
    requested_parser.set_defaults(handler=validate_requested_run)

    suite_parser = subparsers.add_parser("validate-suite")
    suite_parser.add_argument("--jobs-json", required=True, type=Path)
    suite_parser.add_argument("--suite", required=True)
    suite_parser.set_defaults(handler=validate_suite)

    artifact_parser = subparsers.add_parser("extract-build-url")
    artifact_parser.add_argument("--archive", required=True, type=Path)
    artifact_parser.add_argument("--run-id", required=True, type=int)
    artifact_parser.add_argument("--run-attempt", required=True, type=int)
    artifact_parser.set_defaults(handler=extract_build_url)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
