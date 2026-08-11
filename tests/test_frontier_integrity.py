from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from tests.helpers import (
    REPOSITORY_ROOT,
    load_json,
    make_valid_project,
    run_all_validator,
    run_script,
    write_json,
)


class FrontierIntegrityTests(unittest.TestCase):
    def make_frontier_project(self) -> Path:
        temporary_directory, project = make_valid_project()
        self.addCleanup(temporary_directory.cleanup)
        write_json(
            project / "near_neighbor_registry.json",
            {
                "records": [
                    {
                        "registry_id": "W-0001",
                        "importance": "IMPORTANT",
                        "importance_history": [
                            {
                                "importance": "IMPORTANT",
                                "at": "2026-08-01T00:00:00Z",
                                "reason": "Direct near neighbor.",
                            }
                        ],
                        "download": {"status": "FULLTEXT_ARCHIVED"},
                        "reclassifications": [],
                    }
                ]
            },
        )
        write_json(
            project / "literature_claim_registry.json",
            {
                "records": [
                    {
                        "claim_id": "LC-0001",
                        "source_registry_id": "W-0001",
                        "evidence_level": "E2",
                        "source_artifact_id": "FT-W-0001",
                        "source_artifact_kind": "FULL_ARTICLE_PDF",
                        "locator": {"page": "7"},
                    }
                ]
            },
        )
        return project

    @staticmethod
    def snapshot(project: Path) -> dict[str, str]:
        return {
            path.relative_to(project).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in project.rglob("*")
            if path.is_file()
        }

    def run_frontier(self, project: Path):
        return run_script("validate_frontier_integrity.py", project)

    def test_minimal_frontier_is_ready_and_read_only(self) -> None:
        project = self.make_frontier_project()
        before = self.snapshot(project)

        result = self.run_frontier(project)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("frontier_integrity_status=READY", result.stdout)
        self.assertEqual(before, self.snapshot(project))

    def test_current_importance_must_equal_last_history_event(self) -> None:
        project = self.make_frontier_project()
        registry = load_json(project / "near_neighbor_registry.json")
        registry["records"][0]["importance"] = "CONTEXT"
        write_json(project / "near_neighbor_registry.json", registry)

        result = self.run_frontier(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("IMPORTANCE_HISTORY_MISMATCH", result.stdout)

    def test_critical_downgrade_requires_fulltext_and_independent_review(self) -> None:
        project = self.make_frontier_project()
        registry = load_json(project / "near_neighbor_registry.json")
        registry["records"][0]["importance"] = "CONTEXT"
        registry["records"][0]["importance_history"] = [
            {
                "importance": "CRITICAL",
                "at": "2026-08-01T00:00:00Z",
                "reason": "Direct neighbor.",
            },
            {
                "importance": "CONTEXT",
                "at": "2026-08-02T00:00:00Z",
                "reason": "Reclassified after full-text review.",
            },
        ]
        write_json(project / "near_neighbor_registry.json", registry)

        result = self.run_frontier(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("UNJUSTIFIED_IMPORTANCE_DOWNGRADE", result.stdout)

    def test_valid_downgrade_binds_fulltext_claim_and_audited_review(self) -> None:
        project = self.make_frontier_project()
        registry = load_json(project / "near_neighbor_registry.json")
        work = registry["records"][0]
        work["importance"] = "CONTEXT"
        work["importance_history"] = [
            {
                "importance": "CRITICAL",
                "at": "2026-08-01T00:00:00Z",
                "reason": "Direct neighbor.",
            },
            {
                "importance": "CONTEXT",
                "at": "2026-08-02T00:00:00Z",
                "reason": "Reclassified after full-text review.",
            },
        ]
        work["reclassifications"] = [
            {
                "from_importance": "CRITICAL",
                "to_importance": "CONTEXT",
                "at": "2026-08-02T00:00:00Z",
                "fulltext_artifact_id": "FT-W-0001",
                "evidence_level": "E2",
                "reviewer_agent_id": "agent-b",
                "reviewer_thread_id": "thread-frontier-b",
                "audited_artifact_sha256": "a" * 64,
            }
        ]
        write_json(project / "near_neighbor_registry.json", registry)

        result = self.run_frontier(project)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_download_blocked_can_never_justify_downgrade(self) -> None:
        project = self.make_frontier_project()
        registry = load_json(project / "near_neighbor_registry.json")
        work = registry["records"][0]
        work["importance"] = "CONTEXT"
        work["importance_history"] = [
            {"importance": "IMPORTANT", "at": "2026-08-01", "reason": "Near."},
            {"importance": "CONTEXT", "at": "2026-08-02", "reason": "Blocked."},
        ]
        work["download"] = {"status": "DOWNLOAD_BLOCKED"}
        work["reclassifications"] = [
            {
                "from_importance": "IMPORTANT",
                "to_importance": "CONTEXT",
                "at": "2026-08-02",
                "fulltext_artifact_id": "FT-W-0001",
                "evidence_level": "E2",
                "reviewer_agent_id": "agent-b",
                "reviewer_thread_id": "thread-frontier-b",
                "audited_artifact_sha256": "a" * 64,
            }
        ]
        write_json(project / "near_neighbor_registry.json", registry)

        result = self.run_frontier(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("DOWNLOAD_BLOCKED_CANNOT_DOWNGRADE", result.stdout)

    def test_artifact_kinds_are_closed_and_e2_requires_full_article(self) -> None:
        cases = (
            ("OFFICIAL_ABSTRACT", "E2_REQUIRES_FULLTEXT"),
            ("SCRAPED_SUMMARY", "INVALID_ARTIFACT_KIND"),
        )
        for artifact_kind, code in cases:
            with self.subTest(artifact_kind=artifact_kind):
                project = self.make_frontier_project()
                claims = load_json(project / "literature_claim_registry.json")
                claims["records"][0]["source_artifact_kind"] = artifact_kind
                write_json(project / "literature_claim_registry.json", claims)

                result = self.run_frontier(project)

                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn(code, result.stdout)

    def test_e4_requires_proof_artifact_or_fulltext_proof_locator(self) -> None:
        project = self.make_frontier_project()
        claims = load_json(project / "literature_claim_registry.json")
        claim = claims["records"][0]
        claim["evidence_level"] = "E4"
        claim["source_artifact_kind"] = "FULL_ARTICLE_HTML"
        write_json(project / "literature_claim_registry.json", claims)

        result = self.run_frontier(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("E4_REQUIRES_PROOF", result.stdout)

        claim["proof_locator"] = {"theorem": "Theorem 3", "proof": "Appendix B"}
        write_json(project / "literature_claim_registry.json", claims)
        result = self.run_frontier(project)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

        claim.pop("proof_locator")
        claim["source_artifact_kind"] = "PROOF_OR_APPENDIX"
        write_json(project / "literature_claim_registry.json", claims)
        result = self.run_frontier(project)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_missing_axis_is_invalid_not_blocked(self) -> None:
        project = self.make_frontier_project()
        coverage = load_json(project / "frontier_coverage.json")
        del coverage["axes"]["author_continuations"]
        write_json(project / "frontier_coverage.json", coverage)

        result = self.run_frontier(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("FRONTIER_AXIS_MISSING", result.stdout)
        self.assertIn("frontier_integrity_status=INVALID", result.stdout)

    def test_concrete_unavailable_axis_capability_is_blocked(self) -> None:
        project = self.make_frontier_project()
        coverage = load_json(project / "frontier_coverage.json")
        coverage["axes"]["forward_citations"] = {
            "status": "BLOCKED",
            "capability": {
                "name": "FORWARD_CITATION_INDEX",
                "available": False,
                "reason": "No citation-index capability is available in this runtime.",
            },
        }
        write_json(project / "frontier_coverage.json", coverage)

        result = self.run_frontier(project)

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("FRONTIER_CAPABILITY_UNAVAILABLE", result.stdout)
        self.assertIn("frontier_integrity_status=BLOCKED", result.stdout)

    def test_two_independent_routes_are_required(self) -> None:
        project = self.make_frontier_project()
        coverage = load_json(project / "frontier_coverage.json")
        coverage["routes"] = coverage["routes"][:1]
        write_json(project / "frontier_coverage.json", coverage)

        result = self.run_frontier(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("FRONTIER_ROUTES_INSUFFICIENT", result.stdout)

    def test_duplicate_json_keys_are_rejected_without_traceback(self) -> None:
        project = self.make_frontier_project()
        (project / "frontier_coverage.json").write_text(
            '{"schema_version":"2.0","axes":{},"axes":{},"routes":[]}',
            encoding="utf-8",
        )

        result = self.run_frontier(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("STRICT_JSON", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_validate_all_runs_frontier_when_gate_claims_completion(self) -> None:
        project = self.make_frontier_project()
        state = load_json(project / "workflow_state.json")
        state["gates"]["recent_frontier_complete"] = True
        write_json(project / "workflow_state.json", state)
        coverage = load_json(project / "frontier_coverage.json")
        del coverage["axes"]["theory_terms"]
        write_json(project / "frontier_coverage.json", coverage)

        result = run_all_validator(project)

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("=== frontier_integrity ===", result.stdout)
        self.assertIn("FRONTIER_AXIS_MISSING", result.stdout)


class HollowCoverageAxisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp, self.project = make_valid_project()
        write_json(
            self.project / "near_neighbor_registry.json",
            {
                "records": [
                    {
                        "registry_id": "W-0001",
                        "importance": "IMPORTANT",
                        "importance_history": [
                            {
                                "importance": "IMPORTANT",
                                "at": "2026-08-01T00:00:00Z",
                                "reason": "Direct near neighbor.",
                            }
                        ],
                        "download": {"status": "FULLTEXT_ARCHIVED"},
                        "reclassifications": [],
                    }
                ]
            },
        )
        write_json(
            self.project / "literature_claim_registry.json",
            {
                "records": [
                    {
                        "claim_id": "LC-0001",
                        "source_registry_id": "W-0001",
                        "evidence_level": "E2",
                        "source_artifact_id": "FT-W-0001",
                        "source_artifact_kind": "FULL_ARTICLE_PDF",
                        "locator": {"page": "7"},
                    }
                ]
            },
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_frontier(self, *extra: str):
        return run_script("validate_frontier_integrity.py", self.project, extra)

    def set_author_continuations(self, value) -> None:
        coverage = load_json(self.project / "frontier_coverage.json")
        coverage["axes"]["author_continuations"] = value
        write_json(self.project / "frontier_coverage.json", coverage)

    def test_structured_edges_with_shared_authors_are_clean(self) -> None:
        result = self.run_frontier()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("HOLLOW_COVERAGE_AXIS", result.stdout)

    def test_legacy_string_entries_warn_by_default(self) -> None:
        self.set_author_continuations(["碳感知链：A → B → C"])
        result = self.run_frontier()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("WARNING\tHOLLOW_COVERAGE_AXIS", result.stdout)
        self.assertIn("legacy_string_entry_without_shared_authors", result.stdout)

    def test_legacy_string_entries_invalid_in_strict(self) -> None:
        self.set_author_continuations(["碳感知链：A → B → C"])
        result = self.run_frontier("--strict-new-checks")
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("INVALID\tHOLLOW_COVERAGE_AXIS", result.stdout)

    def test_object_with_empty_shared_authors_is_hollow(self) -> None:
        self.set_author_continuations([{"edge": "W-1 → W-2", "shared_authors": []}])
        result = self.run_frontier()
        self.assertIn("WARNING\tHOLLOW_COVERAGE_AXIS", result.stdout)
        self.assertIn("shared_authors:[]", result.stdout)

    def test_object_missing_shared_authors_is_hollow(self) -> None:
        self.set_author_continuations([{"edge": "W-1 → W-2"}])
        result = self.run_frontier()
        self.assertIn("WARNING\tHOLLOW_COVERAGE_AXIS", result.stdout)
        self.assertIn("shared_authors:missing", result.stdout)

    def test_method_lineage_optional_axis(self) -> None:
        coverage = load_json(self.project / "frontier_coverage.json")
        coverage["axes"]["method_lineage"] = ["A → B → C（引用链）"]
        write_json(self.project / "frontier_coverage.json", coverage)
        result = self.run_frontier()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

        coverage["axes"]["method_lineage"] = {"not": "a list"}
        write_json(self.project / "frontier_coverage.json", coverage)
        result = self.run_frontier()
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("FRONTIER_AXIS_INVALID\tmethod_lineage", result.stdout)

    def test_incident_fixture_reports_three_hollow_edges(self) -> None:
        incident = REPOSITORY_ROOT / "tests" / "fixtures" / "incident-2026-08"
        result = run_script("validate_frontier_integrity.py", incident)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(3, result.stdout.count("WARNING\tHOLLOW_COVERAGE_AXIS"))
        strict = run_script(
            "validate_frontier_integrity.py", incident, ("--strict-new-checks",)
        )
        self.assertEqual(1, strict.returncode, strict.stdout + strict.stderr)


if __name__ == "__main__":
    unittest.main()
