# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
#
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Tests for qcom-deb-images LAVA image selection validation."""

import importlib.util
import io
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


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
        "event": resolver.TRUSTED_EVENT,
        "head_branch": "main",
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
        with self.assertRaisesRegex(ValueError, "No qualifying successful"):
            resolver.select_latest_run([trusted_run(conclusion="failure")], NOW)

    def test_rejects_explicit_untrusted_run(self):
        with self.assertRaisesRegex(ValueError, "trusted qcom-deb-images"):
            resolver.validate_run(trusted_run(path=".github/workflows/other.yml"), NOW)

    def test_rejects_stale_run(self):
        stale = trusted_run(
            created_at=(NOW - timedelta(days=7, seconds=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        )
        with self.assertRaisesRegex(ValueError, "older than seven days"):
            resolver.validate_run(stale, NOW)

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
        self.assertIn("actions/workflows/build.yml/runs?branch=main&status=success", workflow)
        self.assertIn('REQUESTED_RUN_ID: ${{ inputs.run_id }}', workflow)


if __name__ == "__main__":
    unittest.main()
