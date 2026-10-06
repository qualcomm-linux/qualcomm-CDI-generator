# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
#
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Tests for qcom-deb-images LAVA image selection validation."""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)
LAVA_HARDWARE_WORKFLOW = REPO_ROOT / ".github/workflows/lava-hardware.yml"
RESOLVER_WORKFLOW = REPO_ROOT / ".github/workflows/resolve-qcom-image.yml"


def _load_resolver_module():
    script = REPO_ROOT / "ci/qcom_image_resolver.py"
    spec = importlib.util.spec_from_file_location("qcom_image_resolver", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


resolver = _load_resolver_module()


def trusted_run(**overrides):
    run = {
        "id": 123,
        "run_attempt": 2,
        "created_at": "2026-09-02T12:00:00Z",
        "html_url": "https://github.com/qualcomm-linux/qcom-deb-images/actions/runs/123",
        "head_repository": {"full_name": resolver.TRUSTED_REPOSITORY},
        "event": "workflow_run",
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "path": resolver.TRUSTED_WORKFLOW_PATH,
    }
    run.update(overrides)
    return run


class QcomImageRunTests(unittest.TestCase):
    def test_selects_newest_qualifying_run(self):
        older = trusted_run(id=1, created_at="2026-09-01T12:00:00Z")
        newest = trusted_run(id=2, created_at="2026-09-02T12:00:00Z")
        untrusted = trusted_run(
            id=3,
            created_at="2026-09-03T00:00:00Z",
            head_branch="feature",
        )

        selected = resolver.select_latest_run([older, untrusted, newest], NOW)

        self.assertEqual(selected.run_id, 2)

    def test_rejects_missing_qualifying_run(self):
        with self.assertRaisesRegex(ValueError, "No qualifying completed"):
            resolver.select_latest_run([trusted_run(status="in_progress")], NOW)

    def test_accepts_completed_runs_independently_of_board_test_results(self):
        for event in resolver.TRUSTED_EVENTS:
            for conclusion in ("success", "failure", "cancelled"):
                with self.subTest(event=event, conclusion=conclusion):
                    selected = resolver.validate_run(
                        trusted_run(event=event, conclusion=conclusion), NOW
                    )
                    self.assertEqual(selected.conclusion, conclusion)

    def test_rejects_runs_that_violate_trust_requirements(self):
        for field, value in (
            ("head_repository", {"full_name": "example/qcom-deb-images"}),
            ("event", "push"),
            ("event", "workflow_dispatch"),
            ("head_branch", "feature"),
            ("status", "in_progress"),
            ("status", "queued"),
            ("path", ".github/workflows/other.yml"),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "trusted qcom-deb-images"):
                    resolver.validate_run(trusted_run(**{field: value}), NOW)

    def test_accepts_run_at_ninety_day_freshness_boundary(self):
        self.assertEqual(resolver.MAX_BUILD_AGE, timedelta(hours=2160))
        run = trusted_run(
            created_at=(NOW - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
        )

        self.assertEqual(resolver.validate_run(run, NOW).run_id, run["id"])

    def test_accepts_run_one_second_within_ninety_day_window(self):
        run = trusted_run(
            created_at=(NOW - timedelta(days=90) + timedelta(seconds=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        )

        self.assertEqual(resolver.validate_run(run, NOW).run_id, run["id"])

    def test_rejects_run_one_second_beyond_ninety_day_window(self):
        run = trusted_run(
            created_at=(NOW - timedelta(days=90, seconds=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        )

        with self.assertRaisesRegex(ValueError, "older than three months"):
            resolver.validate_run(run, NOW)

    def test_rejects_invalid_run_metadata(self):
        for field, value in (
            ("id", True),
            ("run_attempt", 0),
            ("created_at", "yesterday"),
            ("html_url", "https://example.com/run/123"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    resolver.validate_run(trusted_run(**{field: value}), NOW)


class QcomImageArtifactTests(unittest.TestCase):
    def test_selects_only_live_build_url_artifact(self):
        payload = {
            "artifacts": [
                {"id": 1, "name": "build_url", "expired": True},
                {"id": 2, "name": "build_url", "expired": False},
            ]
        }
        self.assertEqual(resolver.select_build_url_artifact(payload), 2)

    def test_rejects_missing_live_build_url_artifact(self):
        with self.assertRaisesRegex(ValueError, "no live build_url artifact"):
            resolver.select_build_url_artifact({"artifacts": []})

    def test_rejects_invalid_live_artifact_id(self):
        with self.assertRaisesRegex(ValueError, "invalid build_url artifact ID"):
            resolver.select_build_url_artifact(
                {"artifacts": [{"id": 0, "name": "build_url", "expired": False}]}
            )

    def test_reads_valid_build_url_artifact(self):
        run = resolver.validate_run(trusted_run(), NOW)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("build_url", resolver.expected_build_url(123, 2) + "\n")

        with tempfile.NamedTemporaryFile() as artifact:
            artifact.write(archive.getvalue())
            artifact.flush()
            self.assertEqual(
                resolver.read_build_url_artifact(Path(artifact.name), run),
                resolver.expected_build_url(run.run_id, run.run_attempt),
            )

    def test_rejects_untrusted_build_url_artifact(self):
        run = resolver.validate_run(trusted_run(), NOW)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("build_url", "https://example.com/not-trusted/\n")

        with tempfile.NamedTemporaryFile() as artifact:
            artifact.write(archive.getvalue())
            artifact.flush()
            with self.assertRaisesRegex(ValueError, "does not match"):
                resolver.read_build_url_artifact(Path(artifact.name), run)

    def test_rejects_unexpected_build_url_artifact_layout(self):
        run = resolver.validate_run(trusted_run(), NOW)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("unexpected", resolver.expected_build_url(123, 2))

        with tempfile.NamedTemporaryFile() as artifact:
            artifact.write(archive.getvalue())
            artifact.flush()
            with self.assertRaisesRegex(ValueError, "unexpected file layout"):
                resolver.read_build_url_artifact(Path(artifact.name), run)


class QcomImageSuiteTests(unittest.TestCase):
    def test_accepts_current_matrix_only_for_default_profile_and_kernel(self):
        for suite in resolver.SUPPORTED_SUITES:
            name = (
                f"build ({suite}, default, default, "
                "linux-image-qcom-next,linux-headers-qcom-next) / "
                f"Build and upload debos recipes ({suite}, default)"
            )
            resolver.validate_suite_build(
                {"jobs": [{"name": name, "conclusion": "success"}]}, suite
            )
            for invalid_name in (
                name.replace("default, default,", "default, performance,"),
                name.replace("default, default,", "default, debug,"),
                name.replace("linux-image-qcom-next,", "linux-image-qcom-next-debug,"),
            ):
                with self.subTest(suite=suite, name=invalid_name):
                    with self.assertRaisesRegex(ValueError, "default image build"):
                        resolver.validate_suite_build(
                            {"jobs": [{"name": invalid_name, "conclusion": "success"}]},
                            suite,
                        )

    def test_accepts_successful_default_suite_build(self):
        resolver.validate_suite_build(
            {
                "jobs": [
                    {
                        "name": (
                            "build (trixie, default) / "
                            "Build and upload debos recipes (trixie, default)"
                        ),
                        "conclusion": "success",
                    }
                ]
            },
            "trixie",
        )

    def test_rejects_missing_or_failed_suite_build(self):
        with self.assertRaisesRegex(ValueError, "trixie default image build"):
            resolver.validate_suite_build({"jobs": []}, "trixie")
        with self.assertRaisesRegex(ValueError, "trixie default image build"):
            resolver.validate_suite_build(
                {
                    "jobs": [
                        {
                            "name": (
                                "build (trixie, default) / "
                                "Build and upload debos recipes (trixie, default)"
                            ),
                            "conclusion": "failure",
                        }
                    ]
                },
                "trixie",
            )

    def test_rejects_unsupported_suite(self):
        with self.assertRaisesRegex(ValueError, "not built"):
            resolver.validate_suite_build({"jobs": []}, "unstable")


class QcomImageWorkflowTests(unittest.TestCase):
    def test_lava_workflow_resolves_a_run_id_after_schema_validation(self):
        workflow = LAVA_HARDWARE_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("run_id:", workflow)
        self.assertIn("needs: schema-check", workflow)
        self.assertIn("uses: ./.github/workflows/resolve-qcom-image.yml", workflow)
        self.assertIn("needs: [schema-check, resolve-image]", workflow)
        self.assertIn(
            "build_download_url: ${{ needs.resolve-image.outputs.build_url }}",
            workflow,
        )
        self.assertNotIn("CDI_TEST_BUILD_DOWNLOAD_URL", workflow)
        self.assertNotIn("secrets: inherit", workflow)

    def test_resolver_workflow_uses_read_only_pinned_dependencies(self):
        workflow = RESOLVER_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("actions: read", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
            workflow,
        )
        self.assertIn("ci/qcom_image_resolver.py resolve-image", workflow)
        self.assertIn('--suite "$SUITE"', workflow)
        self.assertIn('--github-output "$GITHUB_OUTPUT"', workflow)
        self.assertIn('--github-summary "$GITHUB_STEP_SUMMARY"', workflow)
        self.assertIn('REQUESTED_RUN_ID: ${{ inputs.run_id }}', workflow)


class QcomImagePublicationTests(unittest.TestCase):
    @staticmethod
    def publication_api(missing=None, failed_suite=None, bad_pointer=None):
        def api(endpoint, paginate=False):
            if "/jobs?" in endpoint:
                run_id = int(endpoint.split("/runs/")[1].split("/")[0])
                return json.dumps([{
                    "jobs": [{
                        "name": (
                            "build (trixie, default, default, "
                            "linux-image-qcom-next,linux-headers-qcom-next) / "
                            "Build and upload debos recipes (trixie, default)"
                        ),
                        "conclusion": "failure" if run_id == failed_suite else "success",
                    }]
                }]).encode()
            if "/artifacts?" in endpoint:
                run_id = int(endpoint.split("/runs/")[1].split("/")[0])
                return json.dumps([{
                    "artifacts": [] if run_id == missing else [
                        {"id": run_id, "name": "build_url", "expired": False}
                    ]
                }]).encode()
            run_id = int(endpoint.split("/artifacts/")[1].split("/")[0])
            archive = io.BytesIO()
            pointer = resolver.expected_build_url(run_id, 2)
            if run_id == bad_pointer:
                pointer = resolver.expected_build_url(run_id, 1)
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("build_url", pointer + "\n")
            return archive.getvalue()
        return api

    def test_resolves_failed_scheduled_run_with_published_suite(self):
        calls = []
        api = self.publication_api()

        def recording_api(endpoint, paginate=False):
            calls.append(endpoint)
            return api(endpoint, paginate)

        run, url = resolver.resolve_publication(
            [trusted_run(event="schedule", conclusion="failure")],
            "trixie", NOW, recording_api,
        )
        self.assertEqual(run.run_id, 123)
        self.assertEqual(url, resolver.expected_build_url(123, 2))
        self.assertIn("/attempts/2/jobs?", calls[0])

    def test_falls_back_to_fresh_publication_with_diagnostics(self):
        runs = [
            trusted_run(id=1, created_at="2026-09-01T12:00:00Z"),
            trusted_run(id=2, event="schedule", conclusion="failure"),
        ]
        for kwargs in ({"missing": 2}, {"failed_suite": 2}, {"bad_pointer": 2}):
            with self.subTest(kwargs=kwargs):
                diagnostics = io.StringIO()
                with redirect_stderr(diagnostics):
                    run, _ = resolver.resolve_publication(
                        runs, "trixie", NOW, self.publication_api(**kwargs)
                    )
                self.assertEqual(run.run_id, 1)
                self.assertIn("Skipping run 2:", diagnostics.getvalue())

    def test_explicit_selection_never_falls_back(self):
        with self.assertRaisesRegex(ValueError, "no live build_url"):
            resolver.resolve_publication(
                [trusted_run()], "trixie", NOW,
                self.publication_api(missing=123), requested=True,
            )

    def test_rejects_stale_and_untrusted_publications_before_api_calls(self):
        runs = [
            trusted_run(created_at="2026-05-01T00:00:00Z"),
            trusted_run(event="workflow_dispatch"),
            trusted_run(status="in_progress"),
        ]
        with redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "No qualifying fresh"):
                resolver.resolve_publication(
                    runs, "trixie", NOW,
                    lambda *_args: self.fail("must not request untrusted publications"),
                )

    def test_api_errors_are_not_hidden_by_fallback(self):
        def failed_api(*_args):
            raise RuntimeError("GitHub API unavailable")

        with self.assertRaisesRegex(RuntimeError, "GitHub API unavailable"):
            resolver.resolve_publication(
                [trusted_run()], "trixie", NOW, failed_api
            )

    def test_cli_selects_completed_runs_and_writes_validated_outputs(self):
        for requested in ("", "123"):
            with self.subTest(requested=requested):
                calls = []
                publication_api = self.publication_api()

                def api(endpoint, paginate=False):
                    calls.append((endpoint, paginate))
                    run = trusted_run(event="schedule", conclusion="failure")
                    if "/workflows/" in endpoint:
                        return json.dumps([{"workflow_runs": [run]}]).encode()
                    if endpoint.endswith("/runs/123"):
                        return json.dumps(run).encode()
                    return publication_api(endpoint, paginate)

                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "outputs"
                    summary = Path(directory) / "summary"
                    args = resolver.build_parser().parse_args([
                        "resolve-image", "--run-id", requested, "--suite", "trixie",
                        "--github-output", str(output),
                        "--github-summary", str(summary),
                    ])
                    with patch.object(resolver, "_github_api", side_effect=api):
                        with patch.object(resolver, "_current_time", return_value=NOW):
                            args.handler(args)
                    self.assertEqual(
                        output.read_text(),
                        "run_id=123\n"
                        f"build_url={resolver.expected_build_url(123, 2)}\n",
                    )
                    self.assertIn(
                        "Upstream workflow conclusion: failure", summary.read_text()
                    )
                    if not requested:
                        self.assertIn("status=completed", calls[0][0])
                        self.assertTrue(calls[0][1])

    def test_cli_failed_publication_writes_no_success_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            summary = Path(directory) / "summary"
            args = resolver.build_parser().parse_args([
                "resolve-image", "--run-id", "123", "--suite", "trixie",
                "--github-output", str(output), "--github-summary", str(summary),
            ])
            publication_api = self.publication_api(missing=123)

            def api(endpoint, paginate=False):
                if endpoint.endswith("/runs/123"):
                    return json.dumps(trusted_run()).encode()
                return publication_api(endpoint, paginate)

            with patch.object(resolver, "_github_api", side_effect=api):
                with patch.object(resolver, "_current_time", return_value=NOW):
                    with self.assertRaisesRegex(ValueError, "no live build_url"):
                        args.handler(args)
            self.assertFalse(output.exists())
            self.assertFalse(summary.exists())

    def test_cli_rejects_invalid_requested_run_ids_before_api_calls(self):
        for run_id in ("0", "-1", "123/attempts/1", "1\n"):
            with self.subTest(run_id=run_id):
                args = resolver.build_parser().parse_args([
                    "resolve-image", "--run-id", run_id, "--suite", "trixie",
                    "--github-output", "unused", "--github-summary", "unused",
                ])
                with patch.object(resolver, "_github_api") as api:
                    with self.assertRaisesRegex(ValueError, "positive decimal"):
                        args.handler(args)
                    api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
