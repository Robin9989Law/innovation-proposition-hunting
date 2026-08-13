from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from tests.helpers import REPOSITORY_ROOT, load_json, run_script, write_json

sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import validate_literature_registry as literature_registry  # noqa: E402
from validation_common import ProjectContext, open_root_fd  # noqa: E402


def make_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "registry_id": "W-0001",
        "canonical_url": "https://arxiv.org/abs/2401.00001",
        "publication_status": "PREPRINT_ONLY",
        "terminal_rejection_eligibility": "NOT_QUALIFIED",
        "peer_review_status": "NON_PEER_REVIEWED",
    }
    record.update(overrides)
    return record


def build_registry_fixture(project: Path, records: list[dict[str, object]]) -> None:
    write_json(project / "workflow_state.json", {"current_year": 2026})
    write_json(
        project / "near_neighbor_registry.json",
        {
            "records": records,
            "peer_reviewed_published_count": 0,
            "search_mode": "SEARCH_OPEN",
            "synthesis_lock_threshold": 100,
        },
    )


class LiteratureRegistryTests(unittest.TestCase):
    def make_project(
        self, records: list[dict[str, object]] | None = None
    ) -> Path:
        temporary_directory = TemporaryDirectory(prefix="literature-registry-")
        self.addCleanup(temporary_directory.cleanup)
        project = Path(temporary_directory.name)
        build_registry_fixture(project, records if records is not None else [])
        return project

    @staticmethod
    def run_literature(project: Path, *extra_args: str):
        return run_script(
            "validate_literature_registry.py",
            project,
            (
                "--registry",
                str(project / "near_neighbor_registry.json"),
                *extra_args,
            ),
        )

    def test_valid_empty_registry_is_ready(self) -> None:
        project = self.make_project()

        result = self.run_literature(project)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("literature_registry_status=READY", result.stdout)
        self.assertIn("academic_url_occurrences=0", result.stdout)

    def test_validate_with_context_library_entry(self) -> None:
        project = self.make_project()

        with ProjectContext(project, project / "workflow_state.json") as ctx:
            issues = literature_registry.validate_with_context(ctx)

        self.assertEqual([], issues)

    def test_active_url_ledger_uses_state_pointer_and_preserves_old_version(self) -> None:
        project = self.make_project(records=[make_record()])
        old_ledger = project / "near_neighbor_url_ledger.csv"
        old_ledger.write_text("historical invalid ledger\n", encoding="utf-8")
        corrected = project / "near_neighbor_url_ledger.v2.csv"
        corrected.write_text("corrected active ledger\n", encoding="utf-8")
        state = load_json(project / "workflow_state.json")
        state["artifacts"] = {"url_ledger": corrected.name}
        write_json(project / "workflow_state.json", state)

        with ProjectContext(project, project / "workflow_state.json") as ctx:
            self.assertEqual(corrected.name, ctx.artifact_relative_path("url_ledger"))
            issues = literature_registry.validate_with_context(ctx)

        self.assertEqual([], issues)
        self.assertEqual("historical invalid ledger\n", old_ledger.read_text(encoding="utf-8"))

    def test_malformed_registry_json_is_validator_error_not_traceback(self) -> None:
        project = self.make_project()
        (project / "near_neighbor_registry.json").write_text(
            "not valid json\n", encoding="utf-8"
        )

        result = self.run_literature(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("VALIDATOR_ERROR", result.stdout)
        self.assertIn("literature_registry_status=INVALID", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_records_key_is_invalid_issue_not_keyerror(self) -> None:
        project = self.make_project()
        write_json(
            project / "near_neighbor_registry.json",
            {
                "peer_reviewed_published_count": 0,
                "search_mode": "SEARCH_OPEN",
                "synthesis_lock_threshold": 100,
            },
        )

        result = self.run_literature(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("records:missing_or_not_list", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_unregistered_academic_url_is_flagged(self) -> None:
        project = self.make_project()
        (project / "notes.md").write_text(
            "See https://arxiv.org/abs/2401.00001 for details.\n", encoding="utf-8"
        )

        result = self.run_literature(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("UNREGISTERED", result.stdout)
        self.assertIn("arxiv:2401.00001", result.stdout)
        self.assertIn("unregistered_url_keys=1", result.stdout)

    def test_arxiv_alias_is_matched_by_canonical_key(self) -> None:
        project = self.make_project(records=[make_record()])
        (project / "notes.md").write_text(
            "PDF at https://arxiv.org/pdf/2401.00001\n", encoding="utf-8"
        )

        result = self.run_literature(project)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("academic_url_occurrences=1", result.stdout)
        self.assertIn("unregistered_url_keys=0", result.stdout)

    def test_duplicate_registry_ids_are_flagged(self) -> None:
        project = self.make_project(
            records=[make_record(), make_record(canonical_url=None, url=None)]
        )

        result = self.run_literature(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("DUPLICATE_ID", result.stdout)
        self.assertIn("duplicate_registry_ids=1", result.stdout)

    def test_cross_record_url_conflict_is_flagged(self) -> None:
        project = self.make_project(
            records=[
                make_record(),
                make_record(
                    registry_id="W-0002",
                    canonical_url="https://arxiv.org/pdf/2401.00001",
                ),
            ]
        )

        result = self.run_literature(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("URL_CONFLICT", result.stdout)
        self.assertIn("cross_record_url_conflicts=1", result.stdout)

    def test_peer_reviewed_count_mismatch_uses_single_parse(self) -> None:
        project = self.make_project(
            records=[
                make_record(
                    publication_status="PUBLISHED",
                    terminal_rejection_eligibility="QUALIFIED",
                    publication_verification_url="https://doi.org/10.0000/x",
                    peer_review_status="PEER_REVIEWED_PUBLISHED",
                    peer_review_verification_url="https://doi.org/10.0000/x",
                )
            ]
        )

        result = self.run_literature(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        # declared=0、actual=1 均来自同一次解析（二次解析已消除）。
        self.assertIn("peer_reviewed_published_count:0;actual:1", result.stdout)
        self.assertIn("peer_reviewed_published_count=1", result.stdout)

    def test_preprint_url_cannot_verify_peer_reviewed_publication(self) -> None:
        project = self.make_project(
            records=[
                make_record(
                    publication_status="PUBLISHED",
                    terminal_rejection_eligibility="QUALIFIED",
                    publication_verification_url="https://dl.acm.org/doi/10.1145/3672553",
                    peer_review_status="PEER_REVIEWED_PUBLISHED",
                    peer_review_verification_url="https://arxiv.org/abs/2203.02399",
                )
            ]
        )
        registry = load_json(project / "near_neighbor_registry.json")
        registry["peer_reviewed_published_count"] = 1
        write_json(project / "near_neighbor_registry.json", registry)

        result = self.run_literature(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("preprint_cannot_verify_peer_review_status", result.stdout)

    def test_search_mode_must_match_peer_review_threshold(self) -> None:
        project = self.make_project()
        registry = load_json(project / "near_neighbor_registry.json")
        registry["search_mode"] = "SYNTHESIS_LOCK"
        write_json(project / "near_neighbor_registry.json", registry)

        result = self.run_literature(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("search_mode:SYNTHESIS_LOCK", result.stdout)

    def test_file_symlink_is_rejected_without_reading_target(self) -> None:
        project = self.make_project()
        with TemporaryDirectory(prefix="literature-outside-") as outside:
            outside_document = Path(outside) / "secret.md"
            outside_document.write_text(
                "https://arxiv.org/abs/9999.99999\n", encoding="utf-8"
            )
            (project / "escape.md").symlink_to(outside_document)

            result = self.run_literature(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("PATH_OUTSIDE_ROOT", result.stdout)
        self.assertNotIn("9999.99999", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_scan_depth_limit_is_invalid_not_crash(self) -> None:
        with TemporaryDirectory(prefix="literature-depth-") as directory:
            project = Path(directory)
            deep = project / "a" / "b" / "c"
            deep.mkdir(parents=True)
            (deep / "paper.md").write_text(
                "https://arxiv.org/abs/2401.00001\n", encoding="utf-8"
            )
            root_fd = open_root_fd(project)
            try:
                with mock.patch.object(literature_registry, "MAX_SCAN_DEPTH", 2):
                    rows, issues = literature_registry.scan(root_fd, set())
            finally:
                os.close(root_fd)

        self.assertEqual([], rows)
        self.assertTrue(
            any(issue.code == "SCAN_LIMIT" for issue in issues),
            f"expected SCAN_LIMIT issue, got {issues}",
        )
        self.assertTrue(
            any("max_depth_exceeded:2" in issue.detail for issue in issues)
        )

    def test_scan_file_count_limit_is_invalid_not_crash(self) -> None:
        with TemporaryDirectory(prefix="literature-count-") as directory:
            project = Path(directory)
            for index in range(4):
                (project / f"file{index}.txt").write_text("no urls\n")
            root_fd = open_root_fd(project)
            try:
                with mock.patch.object(literature_registry, "MAX_SCAN_FILES", 2):
                    rows, issues = literature_registry.scan(root_fd, set())
            finally:
                os.close(root_fd)

        self.assertEqual([], rows)
        self.assertTrue(
            any("max_files_exceeded:2" in issue.detail for issue in issues),
            f"expected SCAN_LIMIT issue, got {issues}",
        )

    def test_default_read_only_does_not_write_ledger(self) -> None:
        project = self.make_project()
        ledger = project / "near_neighbor_url_ledger.csv"

        result = self.run_literature(project, "--read-only")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(ledger.exists())

    def test_write_ledger_flag_writes_csv(self) -> None:
        project = self.make_project(records=[make_record()])
        (project / "notes.md").write_text(
            "https://arxiv.org/pdf/2401.00001\n", encoding="utf-8"
        )
        ledger = project / "near_neighbor_url_ledger.csv"

        result = self.run_literature(project, "--write-ledger")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(ledger.is_file())
        content = ledger.read_text(encoding="utf-8")
        self.assertIn("canonical_key", content)
        self.assertIn("arxiv:2401.00001", content)
        self.assertIn("YES", content)

    def test_standalone_run_without_workflow_state(self) -> None:
        with TemporaryDirectory(prefix="literature-standalone-") as directory:
            project = Path(directory)
            write_json(
                project / "near_neighbor_registry.json",
                {
                    "records": [],
                    "peer_reviewed_published_count": 0,
                    "search_mode": "SEARCH_OPEN",
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(
                        REPOSITORY_ROOT
                        / "scripts"
                        / "validate_literature_registry.py"
                    ),
                    "--root",
                    str(project),
                    "--registry",
                    str(project / "near_neighbor_registry.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("literature_registry_status=READY", result.stdout)


if __name__ == "__main__":
    unittest.main()
