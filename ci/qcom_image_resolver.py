#!/usr/bin/env python3

# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Validate qcom-deb-images workflow data for LAVA image selection."""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterable, Union


TRUSTED_REPOSITORY = "qualcomm-linux/qcom-deb-images"
TRUSTED_WORKFLOW_PATH = ".github/workflows/build.yml"
TRUSTED_EVENTS = ("schedule", "workflow_run")
MAX_BUILD_AGE = timedelta(days=90)
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
    conclusion: str = ""


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
        and run.get("event") in TRUSTED_EVENTS
        and run.get("head_branch") == "main"
        and run.get("status") == "completed"
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
            f"Selected qcom-deb-images build is older than three months "
            f"({age.days} days)"
        )

    html_url = run.get("html_url")
    if not isinstance(html_url, str) or not html_url.startswith(
        "https://github.com/qualcomm-linux/qcom-deb-images/actions/runs/"
    ):
        raise ValueError("Selected run has an invalid GitHub Actions URL")
    return BuildRun(run_id, run_attempt, created_at, html_url, run.get("conclusion", ""))


def select_latest_run(runs: Iterable[Any], now: datetime) -> BuildRun:
    """Return the newest trusted completed run, rejecting stale selections."""
    candidates = []
    for run in runs:
        if not _is_trusted_run(run):
            continue
        try:
            candidates.append((_parse_created_at(run.get("created_at")), run))
        except ValueError:
            continue
    if not candidates:
        raise ValueError("No qualifying completed qcom-deb-images Build run was found")
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
    legacy_name = (
        f"build ({suite}, default) / "
        f"Build and upload debos recipes ({suite}, default)"
    )
    current_name = (
        f"build ({suite}, default, default, "
        "linux-image-qcom-next,linux-headers-qcom-next) / "
        f"Build and upload debos recipes ({suite}, default)"
    )
    if not isinstance(jobs_payload, (dict, list)):
        raise ValueError("Selected run has no readable jobs list")
    jobs = list(_flatten_jobs(jobs_payload))
    if not any(
        isinstance(job, dict)
        and job.get("name") in (legacy_name, current_name)
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


def read_build_url_artifact(archive: Union[Path, BinaryIO], run: BuildRun) -> str:
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


def _github_api(endpoint: str, paginate: bool = False) -> bytes:
    command = ["gh", "api", endpoint]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(
            f"GitHub API request failed for {endpoint}: "
            f"{result.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return result.stdout


def resolve_publication(
    runs: Iterable[Any],
    suite: str,
    now: datetime,
    api: Callable[..., bytes] = _github_api,
    requested: bool = False,
) -> tuple[BuildRun, str]:
    """Select the newest fresh publication, not the newest passing board tests."""
    if suite not in SUPPORTED_SUITES:
        raise ValueError(f"Suite {suite!r} is not built by the trusted workflow")
    candidates = []
    for raw_run in runs:
        try:
            candidates.append(validate_run(raw_run, now))
        except ValueError as error:
            if requested:
                raise
            print(f"Skipping workflow run: {error}", file=sys.stderr)
    candidates.sort(key=lambda run: run.created_at, reverse=True)
    for run in candidates:
        try:
            prefix = f"repos/{TRUSTED_REPOSITORY}/actions/runs/{run.run_id}"
            # A rerun must not borrow a successful suite job from an earlier attempt.
            jobs = json.loads(
                api(f"{prefix}/attempts/{run.run_attempt}/jobs?per_page=100", True)
            )
            validate_suite_build(jobs, suite)
            artifacts = json.loads(api(f"{prefix}/artifacts?per_page=100", True))
            artifact_id = select_build_url_artifact(artifacts)
            archive = api(
                f"repos/{TRUSTED_REPOSITORY}/actions/artifacts/{artifact_id}/zip"
            )
            build_url = read_build_url_artifact(io.BytesIO(archive), run)
            return run, build_url
        except ValueError as error:
            if requested:
                raise
            print(f"Skipping run {run.run_id}: {error}", file=sys.stderr)
    raise ValueError(
        f"No qualifying fresh qcom-deb-images publication for {suite} was found"
    )


def resolve_image(args: argparse.Namespace) -> None:
    requested = bool(args.run_id)
    if requested:
        if not re.fullmatch(r"[1-9][0-9]*", args.run_id):
            raise ValueError("run_id must contain a positive decimal workflow run ID")
        runs = [
            json.loads(
                _github_api(
                    f"repos/{TRUSTED_REPOSITORY}/actions/runs/{args.run_id}"
                )
            )
        ]
    else:
        payload = json.loads(
            _github_api(
                f"repos/{TRUSTED_REPOSITORY}/actions/workflows/build.yml/"
                "runs?branch=main&status=completed&per_page=100",
                True,
            )
        )
        runs = list(_flatten_workflow_runs(payload))
    run, build_url = resolve_publication(
        runs, args.suite, _current_time(), api=_github_api, requested=requested
    )
    _write_output(args.github_output, run_id=run.run_id, build_url=build_url)
    with args.github_summary.open("a", encoding="utf-8") as summary:
        summary.write(
            "## qcom-deb-images input\n\n"
            f"- Run: [{run.run_id} attempt {run.run_attempt}]({run.html_url})\n"
            f"- Created: {run.created_at:%Y-%m-%dT%H:%M:%SZ}\n"
            f"- Upstream workflow conclusion: {run.conclusion}\n"
            f"- Artifact prefix: `{build_url}`\n"
        )


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

    image_parser = subparsers.add_parser("resolve-image")
    image_parser.add_argument("--run-id", default="")
    image_parser.add_argument("--suite", required=True, choices=SUPPORTED_SUITES)
    image_parser.add_argument("--github-output", required=True, type=Path)
    image_parser.add_argument("--github-summary", required=True, type=Path)
    image_parser.set_defaults(handler=resolve_image)

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
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
