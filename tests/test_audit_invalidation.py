from __future__ import annotations

import hashlib
import os
import unittest
from pathlib import Path

from tests.helpers import (
    append_text,
    load_json,
    make_valid_project,
    run_script,
    run_validator,
    write_json,
)


MANIFEST = "audit_manifest.json"
AUDIT = "independent_audit.json"


class AuditInvalidationTests(unittest.TestCase):
    def make_project(
        self, *, claim_profile: str = "THEORY", validity_level: str = "V3"
    ) -> Path:
        temporary_directory, project = make_valid_project(
            claim_profile=claim_profile,
            validity_level=validity_level,
        )
        self.addCleanup(temporary_directory.cleanup)
        return project

    @staticmethod
    def snapshot_files(project: Path) -> dict[str, str]:
        return {
            path.relative_to(project).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(project.rglob("*"))
            if path.is_file()
        }

    def test_minimal_v3_bundle_and_audit_are_ready(self) -> None:
        result = run_validator(self.make_project())

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("artifact_hashes_status=READY", result.stdout)
        self.assertIn("audit_provenance_status=READY", result.stdout)

    def test_modified_theorem_invalidates_v3(self) -> None:
        project = self.make_project(claim_profile="THEORY", validity_level="V3")
        append_text(project / "manuscript.md", "A material theorem change.\n")

        result = run_validator(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("STALE_AUDIT", result.stdout)

    def test_audit_of_different_bundle_fails(self) -> None:
        project = self.make_project(claim_profile="MIXED", validity_level="V4")
        audit = load_json(project / AUDIT)
        audit["audited_bundle_sha256"] = "0" * 64
        write_json(project / AUDIT, audit)

        result = run_validator(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("AUDIT_BUNDLE_MISMATCH", result.stdout)

    def test_manifest_order_does_not_change_canonical_bundle(self) -> None:
        project = self.make_project()
        manifest = load_json(project / MANIFEST)
        manifest["entries"].reverse()
        write_json(project / MANIFEST, manifest)

        result = run_script("validate_artifact_hashes.py", project)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_manifest_rejects_duplicate_paths(self) -> None:
        project = self.make_project()
        manifest = load_json(project / MANIFEST)
        manifest["entries"].append(dict(manifest["entries"][0]))
        write_json(project / MANIFEST, manifest)

        result = run_script("validate_artifact_hashes.py", project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("DUPLICATE_MANIFEST_PATH", result.stdout)

    def test_manifest_rejects_empty_role(self) -> None:
        project = self.make_project()
        manifest = load_json(project / MANIFEST)
        manifest["entries"][0]["role"] = " "
        write_json(project / MANIFEST, manifest)

        result = run_script("validate_artifact_hashes.py", project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("INVALID_MANIFEST_ROLE", result.stdout)

    def test_manifest_rejects_unsafe_relative_path(self) -> None:
        project = self.make_project()
        manifest = load_json(project / MANIFEST)
        manifest["entries"][0]["path"] = "../outside.txt"
        write_json(project / MANIFEST, manifest)

        result = run_script("validate_artifact_hashes.py", project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("UNSAFE_ARTIFACT_PATH", result.stdout)

    def test_manifest_rejects_symlink_instead_of_regular_file(self) -> None:
        project = self.make_project()
        manuscript = project / "manuscript.md"
        outside = project.parent / f"{project.name}-outside.md"
        outside.write_text(manuscript.read_text(encoding="utf-8"), encoding="utf-8")
        self.addCleanup(outside.unlink, missing_ok=True)
        manuscript.unlink()
        os.symlink(outside, manuscript)

        result = run_script("validate_artifact_hashes.py", project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("UNSAFE_ARTIFACT_PATH", result.stdout)

    def test_manifest_epoch_and_state_epoch_must_agree(self) -> None:
        project = self.make_project()
        manifest = load_json(project / MANIFEST)
        manifest["validation_epoch"] = 2
        write_json(project / MANIFEST, manifest)

        result = run_validator(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("AUDIT_EPOCH_MISMATCH", result.stdout)

    def test_external_audit_epoch_and_state_epoch_must_agree(self) -> None:
        project = self.make_project()
        audit = load_json(project / AUDIT)
        audit["validation_epoch"] = 2
        write_json(project / AUDIT, audit)

        result = run_validator(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("AUDIT_EPOCH_MISMATCH", result.stdout)

    def test_external_audit_author_cannot_review_own_bundle(self) -> None:
        project = self.make_project()
        audit = load_json(project / AUDIT)
        audit["reviewer_agent_id"] = audit["author_agent_ids"][0]
        write_json(project / AUDIT, audit)

        result = run_validator(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("AUDITOR_NOT_INDEPENDENT", result.stdout)

    def test_v3_audit_requires_canonical_unique_author_ids(self) -> None:
        cases = (
            ([], "INVALID_AUDIT_AUTHORS"),
            (["agent-a", "agent-a"], "DUPLICATE_AUTHOR_AGENT_ID"),
            ([" agent-a"], "NONCANONICAL_AUDIT_ID"),
        )
        for author_ids, code in cases:
            with self.subTest(author_ids=author_ids):
                project = self.make_project()
                audit = load_json(project / AUDIT)
                audit["author_agent_ids"] = author_ids
                write_json(project / AUDIT, audit)

                result = run_script("validate_audit_provenance.py", project)

                self.assertEqual(
                    1, result.returncode, result.stdout + result.stderr
                )
                self.assertIn(code, result.stdout)

    def test_v3_audit_requires_reviewer_thread_and_pass_verdict(self) -> None:
        cases = (
            ("reviewer_thread_id", "", "INVALID_AUDIT_REVIEWER_THREAD"),
            ("verdict", "FAIL", "AUDIT_VERDICT_NOT_PASS"),
        )
        for field, value, code in cases:
            with self.subTest(field=field):
                project = self.make_project()
                audit = load_json(project / AUDIT)
                audit[field] = value
                write_json(project / AUDIT, audit)

                result = run_script("validate_audit_provenance.py", project)

                self.assertEqual(
                    1, result.returncode, result.stdout + result.stderr
                )
                self.assertIn(code, result.stdout)

    def test_pass_audit_requires_complete_review_answers(self) -> None:
        """review 实质四问：PASS 且能力可用时四键必须全部非空（R-N0-17）。"""
        cases = (
            ("missing_object", None, "review_answers:missing_object"),
            ("missing_key", {"data_authenticity": "ok"}, "review_answers.baseline_execution:missing_or_empty"),
            ("empty_value", {
                "data_authenticity": "ok",
                "baseline_execution": "ok",
                "claim_strength": "ok",
                "falsification_attempt": "  ",
            }, "review_answers.falsification_attempt:missing_or_empty"),
        )
        for label, value, detail in cases:
            with self.subTest(label=label):
                project = self.make_project()
                audit = load_json(project / AUDIT)
                if value is None:
                    audit.pop("review_answers", None)
                else:
                    audit["review_answers"] = value
                write_json(project / AUDIT, audit)

                result = run_script("validate_audit_provenance.py", project)

                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn("REVIEW_ANSWERS_INCOMPLETE", result.stdout)
                self.assertIn(detail, result.stdout)

    def test_complete_review_answers_pass(self) -> None:
        """四问齐全且非空时 audit provenance READY。"""
        project = self.make_project()
        audit = load_json(project / AUDIT)
        audit["review_answers"] = {
            "data_authenticity": "real",
            "baseline_execution": "real",
            "claim_strength": "real",
            "falsification_attempt": "real",
        }
        write_json(project / AUDIT, audit)
        result = run_script("validate_audit_provenance.py", project)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("REVIEW_ANSWERS_INCOMPLETE", result.stdout)

    def test_capability_unavailable_is_blocked_without_false_invalidity(self) -> None:
        project = self.make_project()
        state = load_json(project / "workflow_state.json")
        state["independent_audit"] = {"capability_available": False}
        write_json(project / "workflow_state.json", state)
        write_json(
            project / AUDIT,
            {
                "schema_version": "2.0",
                "capability_available": False,
            },
        )

        result = run_validator(project)

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("BLOCKED_CAPABILITY", result.stdout)
        self.assertNotIn("INVALID_AUDIT_AUTHORS", result.stdout)
        self.assertNotIn("AUDIT_BUNDLE_MISMATCH", result.stdout)

    def test_capability_unavailable_does_not_require_audit_artifact(self) -> None:
        project = self.make_project()
        state = load_json(project / "workflow_state.json")
        state["independent_audit"] = {"capability_available": False}
        write_json(project / "workflow_state.json", state)
        (project / AUDIT).unlink()

        result = run_validator(project)

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("BLOCKED_CAPABILITY", result.stdout)
        self.assertNotIn("VALIDATOR_ERROR", result.stdout)

    def test_capability_block_does_not_hide_malformed_existing_review(self) -> None:
        project = self.make_project()
        state = load_json(project / "workflow_state.json")
        state["independent_audit"]["capability_available"] = False
        state["independent_audit"]["reviewer_agent_id"] = "agent-a"
        write_json(project / "workflow_state.json", state)
        audit = load_json(project / AUDIT)
        audit["capability_available"] = False
        audit["reviewer_agent_id"] = "agent-a"
        write_json(project / AUDIT, audit)

        result = run_validator(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("BLOCKED_CAPABILITY", result.stdout)
        self.assertIn("AUDITOR_NOT_INDEPENDENT", result.stdout)

    def test_capability_block_does_not_skip_existing_artifact_hashes(self) -> None:
        project = self.make_project()
        state = load_json(project / "workflow_state.json")
        state["independent_audit"] = {"capability_available": False}
        write_json(project / "workflow_state.json", state)
        append_text(project / "manuscript.md", "A stale blocked artifact.\n")

        result = run_validator(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("BLOCKED_CAPABILITY", result.stdout)
        self.assertIn("STALE_AUDIT", result.stdout)

    def test_final_lock_uses_external_current_audit_not_only_nested_state(self) -> None:
        project = self.make_project(validity_level="V4")
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "FINAL_LOCK"
        state["resume_state"] = "FINAL_LOCK"
        write_json(project / "workflow_state.json", state)
        audit = load_json(project / AUDIT)
        audit["audited_bundle_sha256"] = "0" * 64
        write_json(project / AUDIT, audit)

        result = run_validator(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("AUDIT_BUNDLE_MISMATCH", result.stdout)

    def test_final_validity_audit_always_dispatches_current_bundle_validators(
        self,
    ) -> None:
        project = self.make_project(validity_level="V2")
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "FINAL_VALIDITY_AUDIT"
        state["resume_state"] = "FINAL_VALIDITY_AUDIT"
        state["validation_epoch"] = 2
        write_json(project / "workflow_state.json", state)

        result = run_validator(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("=== artifact_hashes ===", result.stdout)
        self.assertIn("AUDIT_EPOCH_MISMATCH", result.stdout)

    def test_audit_json_is_strict(self) -> None:
        project = self.make_project()
        raw = (project / AUDIT).read_text(encoding="utf-8")
        (project / AUDIT).write_text(
            raw.replace(
                '"schema_version": "2.0",',
                '"schema_version": "2.0",\n  "schema_version": "2.0",',
                1,
            ),
            encoding="utf-8",
        )

        result = run_script("validate_audit_provenance.py", project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("VALIDATOR_ERROR", result.stdout)
        self.assertIn("DUPLICATE_KEY", result.stdout)

    def test_audit_validation_is_read_only(self) -> None:
        project = self.make_project()
        before = self.snapshot_files(project)

        result = run_validator(project)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(before, self.snapshot_files(project))


class AuditManifestRoleSetTests(unittest.TestCase):
    """templates.md §8 的 profile→必需 role 集合校验（AUDIT_MANIFEST_ROLE_MISSING）。"""

    def make_algorithm_project_with_theory_manifest(self) -> Path:
        temporary_directory, project = make_valid_project(claim_profile="THEORY")
        self.addCleanup(temporary_directory.cleanup)
        state = load_json(project / "workflow_state.json")
        state["claim_profile"] = "ALGORITHM"
        write_json(project / "workflow_state.json", state)
        return project

    def test_missing_roles_warn_by_default(self) -> None:
        project = self.make_algorithm_project_with_theory_manifest()
        result = run_script("validate_artifact_hashes.py", project)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("WARNING\tAUDIT_MANIFEST_ROLE_MISSING", result.stdout)
        self.assertIn("missing_role:BASELINE_CONTRACT", result.stdout)
        self.assertIn("missing_role:PROTOCOL_CONTRACT", result.stdout)

    def test_missing_roles_invalid_in_strict(self) -> None:
        project = self.make_algorithm_project_with_theory_manifest()
        result = run_script(
            "validate_artifact_hashes.py", project, ("--strict-new-checks",)
        )
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("INVALID\tAUDIT_MANIFEST_ROLE_MISSING", result.stdout)

    def test_theory_profile_manifest_is_clean(self) -> None:
        temporary_directory, project = make_valid_project(claim_profile="THEORY")
        self.addCleanup(temporary_directory.cleanup)
        result = run_script("validate_artifact_hashes.py", project)
        self.assertNotIn("AUDIT_MANIFEST_ROLE_MISSING", result.stdout)


if __name__ == "__main__":
    unittest.main()
