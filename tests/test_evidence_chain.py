from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.helpers import REPOSITORY_ROOT, load_json, run_script, write_json

sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import validate_evidence_chain as evidence_chain  # noqa: E402
from validation_common import ProjectContext  # noqa: E402


def build_evidence_fixture(project: Path) -> None:
    """构造一个完全合法的证据链三件套 + workflow_state。"""

    (project / "literature_archive").mkdir()
    pdf = b"%PDF-1.4 evidence-fixture\n"
    (project / "literature_archive" / "W-0001.pdf").write_bytes(pdf)
    sha = hashlib.sha256(pdf).hexdigest()
    write_json(project / "workflow_state.json", {"current_year": 2026})
    write_json(
        project / "near_neighbor_registry.json",
        {
            "current_year": 2026,
            "current_collision_round": 1,
            "recent_window": {
                "start_year": 2024,
                "end_year": 2026,
                "status": "COMPLETE",
                "completed_at": "2026-08-01T00:00:00Z",
                "queries": ["near neighbor search"],
            },
            "records": [
                {
                    "registry_id": "W-0001",
                    "canonical_title": "A near neighbor",
                    "authors": ["Alice"],
                    "year": 2024,
                    "identity_verification_url": "https://arxiv.org/abs/2401.00001",
                    "identity_verified_at": "2026-08-01T00:00:00Z",
                    "identity_status": "VERIFIED",
                    "search_phase": "RECENT_FRONTIER_PASS",
                    "importance": "IMPORTANT",
                    "download": {
                        "status": "FULLTEXT_ARCHIVED",
                        "source_url": "https://arxiv.org/pdf/2401.00001",
                        "downloaded_at": "2026-08-01T00:00:00Z",
                        "verified_against_metadata": True,
                        "local_path": "literature_archive/W-0001.pdf",
                        "sha256": sha,
                    },
                    "claim_extraction_status": "COMPLETE",
                }
            ],
        },
    )
    write_json(
        project / "literature_claim_registry.json",
        {
            "current_collision_round": 1,
            "records": [
                {
                    "claim_id": "LC-0001",
                    "source_registry_id": "W-0001",
                    "claim_type": "METHOD",
                    "normalized_statement": "The neighbor uses method M.",
                    "scope": "single-machine scheduling",
                    "conditions": [],
                    "evidence_level": "E2",
                    "source_artifact_kind": "FULL_ARTICLE_PDF",
                    "verification_status": "VERIFIED_FULLTEXT",
                    "locator": {"page": "3"},
                    "support_role": "SUPPORTS",
                    "importance": "IMPORTANT",
                    "discovered_round": 1,
                    "use_status": "USED",
                    "used_by_output_claim_ids": ["OC-0001"],
                }
            ],
        },
    )
    write_json(
        project / "output_claim_support.json",
        {
            "current_collision_round": 1,
            "output_claims": [
                {
                    "output_claim_id": "OC-0001",
                    "statement": "Our method differs from the neighbor.",
                    "output_location": "manuscript.md:S1",
                    "claim_kind": "FACT",
                    "inference_type": "DIRECT",
                    "supporting_claim_ids": ["LC-0001"],
                    "counter_claim_ids": [],
                    "trace_status": "VERIFIED",
                }
            ],
            "collision_gate": {
                "prior_round_claims_drained": True,
                "unused_prior_claim_ids": [],
                "checked_at": "2026-08-02T00:00:00Z",
            },
        },
    )


class EvidenceChainTests(unittest.TestCase):
    def make_project(self) -> Path:
        temporary_directory = TemporaryDirectory(prefix="evidence-chain-")
        self.addCleanup(temporary_directory.cleanup)
        project = Path(temporary_directory.name)
        build_evidence_fixture(project)
        return project

    @staticmethod
    def run_evidence(project: Path):
        return run_script(
            "validate_evidence_chain.py",
            project,
            (
                "--literature-registry",
                str(project / "near_neighbor_registry.json"),
                "--claim-registry",
                str(project / "literature_claim_registry.json"),
                "--output-support",
                str(project / "output_claim_support.json"),
                "--current-year",
                "2026",
            ),
        )

    def test_valid_project_is_ready(self) -> None:
        project = self.make_project()

        result = self.run_evidence(project)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("evidence_chain_status=READY", result.stdout)
        self.assertIn("evidence_chain_issues=0", result.stdout)

    def test_validate_with_context_library_entry(self) -> None:
        project = self.make_project()

        with ProjectContext(project, project / "workflow_state.json") as ctx:
            issues = evidence_chain.validate_with_context(ctx, current_year=2026)

        self.assertEqual([], issues)

    def test_malformed_literature_json_is_validator_error_not_traceback(self) -> None:
        project = self.make_project()
        (project / "near_neighbor_registry.json").write_text(
            "not valid json\n", encoding="utf-8"
        )

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("VALIDATOR_ERROR", result.stdout)
        self.assertIn("evidence_chain_status=INVALID", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_malformed_claim_json_is_validator_error_not_traceback(self) -> None:
        project = self.make_project()
        (project / "literature_claim_registry.json").write_text(
            "{broken\n", encoding="utf-8"
        )

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("VALIDATOR_ERROR", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_duplicate_json_key_is_rejected_without_traceback(self) -> None:
        project = self.make_project()
        (project / "near_neighbor_registry.json").write_text(
            '{"records": [], "records": []}', encoding="utf-8"
        )

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("VALIDATOR_ERROR", result.stdout)
        self.assertIn("DUPLICATE_KEY", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_registry_file_is_validator_error_not_traceback(self) -> None:
        project = self.make_project()
        (project / "output_claim_support.json").unlink()

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("VALIDATOR_ERROR", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_records_key_is_invalid_issue_not_crash(self) -> None:
        project = self.make_project()
        write_json(project / "near_neighbor_registry.json", {"current_year": 2026})

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("INVALID_RECORDS", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_output_claims_key_is_invalid_issue_not_crash(self) -> None:
        project = self.make_project()
        write_json(
            project / "output_claim_support.json", {"current_collision_round": 1}
        )

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("INVALID_RECORDS", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_download_sha256_mismatch(self) -> None:
        project = self.make_project()
        registry = load_json(project / "near_neighbor_registry.json")
        registry["records"][0]["download"]["sha256"] = "0" * 64
        write_json(project / "near_neighbor_registry.json", registry)

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("sha256_mismatch", result.stdout)

    def test_download_file_not_found(self) -> None:
        project = self.make_project()
        (project / "literature_archive" / "W-0001.pdf").unlink()

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("file_not_found", result.stdout)

    def test_download_path_escaping_root_is_rejected(self) -> None:
        project = self.make_project()
        registry = load_json(project / "near_neighbor_registry.json")
        registry["records"][0]["download"]["local_path"] = "../escape.pdf"
        write_json(project / "near_neighbor_registry.json", registry)

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("invalid_or_missing_local_path", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_download_symlink_is_not_followed(self) -> None:
        project = self.make_project()
        with TemporaryDirectory(prefix="evidence-chain-outside-") as outside:
            outside_pdf = Path(outside) / "secret.pdf"
            outside_pdf.write_bytes(b"%PDF-1.4 outside\n")
            (project / "literature_archive" / "W-0001.pdf").unlink()
            (project / "literature_archive" / "W-0001.pdf").symlink_to(outside_pdf)

            result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("unsafe_local_path", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_pre_k_states_defer_unselected_fulltext_and_claim_requirements(self) -> None:
        project = self.make_project()
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "PRIOR_CLAIM_DRAIN"
        state["resume_state"] = "PRIOR_CLAIM_DRAIN"
        write_json(project / "workflow_state.json", state)
        registry = load_json(project / "near_neighbor_registry.json")
        work = registry["records"][0]
        work["download"] = {"status": "NOT_ATTEMPTED"}
        work["claim_extraction_status"] = "NOT_STARTED"
        write_json(project / "near_neighbor_registry.json", registry)
        claims = load_json(project / "literature_claim_registry.json")
        claims["records"] = []
        write_json(project / "literature_claim_registry.json", claims)
        outputs = load_json(project / "output_claim_support.json")
        outputs["output_claims"] = []
        write_json(project / "output_claim_support.json", outputs)

        result = self.run_evidence(project)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("evidence_chain_status=READY", result.stdout)

    def test_k_fulltext_still_requires_archived_important_work(self) -> None:
        project = self.make_project()
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "K_FULLTEXT"
        state["resume_state"] = "K_FULLTEXT"
        write_json(project / "workflow_state.json", state)
        registry = load_json(project / "near_neighbor_registry.json")
        registry["records"][0]["download"]["status"] = "DOWNLOAD_BLOCKED"
        write_json(project / "near_neighbor_registry.json", registry)

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("important_not_archived:DOWNLOAD_BLOCKED", result.stdout)

    def test_k_fulltext_defers_atomic_claims_until_claim_registration(self) -> None:
        project = self.make_project()
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "K_FULLTEXT"
        state["resume_state"] = "K_FULLTEXT"
        write_json(project / "workflow_state.json", state)
        registry = load_json(project / "near_neighbor_registry.json")
        registry["records"][0]["claim_extraction_status"] = "NOT_STARTED"
        write_json(project / "near_neighbor_registry.json", registry)
        claims = load_json(project / "literature_claim_registry.json")
        claims["records"] = []
        write_json(project / "literature_claim_registry.json", claims)
        outputs = load_json(project / "output_claim_support.json")
        outputs["output_claims"] = []
        write_json(project / "output_claim_support.json", outputs)

        result = self.run_evidence(project)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_l3_scope_does_not_require_unselected_important_work(self) -> None:
        project = self.make_project()
        state = load_json(project / "workflow_state.json")
        state.update(
            {
                "active_state": "K_FULLTEXT",
                "resume_state": "K_FULLTEXT",
                "artifacts": {"current_evidence_scope": "current_evidence_scope.json"},
            }
        )
        write_json(project / "workflow_state.json", state)
        write_json(
            project / "current_evidence_scope.json",
            {"fulltext_registry_ids": ["W-0001"]},
        )
        registry = load_json(project / "near_neighbor_registry.json")
        registry["records"].append(
            {
                **registry["records"][0],
                "registry_id": "W-UNSELECTED",
                "download": {"status": "NOT_ATTEMPTED"},
                "claim_extraction_status": "NOT_STARTED",
            }
        )
        write_json(project / "near_neighbor_registry.json", registry)

        result = self.run_evidence(project)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_claim_with_unknown_source(self) -> None:
        project = self.make_project()
        claims = load_json(project / "literature_claim_registry.json")
        claims["records"][0]["source_registry_id"] = "W-9999"
        write_json(project / "literature_claim_registry.json", claims)

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("unknown_source:W-9999", result.stdout)

    def test_e2_claim_requires_fulltext_artifact(self) -> None:
        project = self.make_project()
        claims = load_json(project / "literature_claim_registry.json")
        claims["records"][0]["source_artifact_kind"] = "OFFICIAL_ABSTRACT"
        write_json(project / "literature_claim_registry.json", claims)

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("E2_REQUIRES_FULLTEXT", result.stdout)

    def test_contradictory_claim_cannot_support_output(self) -> None:
        project = self.make_project()
        claims = load_json(project / "literature_claim_registry.json")
        claims["records"][0]["support_role"] = "CONTRADICTS"
        write_json(project / "literature_claim_registry.json", claims)

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("contradictory_claim_used_as_support", result.stdout)

    def test_inconsistent_collision_rounds(self) -> None:
        project = self.make_project()
        claims = load_json(project / "literature_claim_registry.json")
        claims["current_collision_round"] = 2
        write_json(project / "literature_claim_registry.json", claims)

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("inconsistent_rounds", result.stdout)

    def test_undrained_prior_round_claims_trip_collision_gate(self) -> None:
        project = self.make_project()
        for name in (
            "near_neighbor_registry.json",
            "literature_claim_registry.json",
            "output_claim_support.json",
        ):
            payload = load_json(project / name)
            payload["current_collision_round"] = 2
            write_json(project / name, payload)
        claims = load_json(project / "literature_claim_registry.json")
        claim = claims["records"][0]
        claim["use_status"] = "UNUSED"
        claim["used_by_output_claim_ids"] = []
        write_json(project / "literature_claim_registry.json", claims)
        outputs = load_json(project / "output_claim_support.json")
        outputs["output_claims"] = []
        outputs["collision_gate"]["prior_round_claims_drained"] = False
        write_json(project / "output_claim_support.json", outputs)

        result = self.run_evidence(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("COLLISION_GATE", result.stdout)
        self.assertIn("unused_prior_claims:LC-0001", result.stdout)


if __name__ == "__main__":
    unittest.main()
