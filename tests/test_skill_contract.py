import hashlib
from pathlib import Path
from shutil import copytree
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def read(self, name: str) -> str:
        return (ROOT / name).read_text(encoding="utf-8")

    def test_main_skill_exposes_schema_v2_hard_gates(self):
        text = self.read("SKILL.md")
        for required in (
            "schema_version = 3.0",
            "N0-4C",
            "V0",
            "V1",
            "V2",
            "V3",
            "V4",
            "THEORY",
            "ALGORITHM",
            "MIXED",
            "reviewer_agent_id",
            "material change",
            "READY = 0",
            "INVALID = 1",
            "BLOCKED_CAPABILITY",
            "BLOCKED = 2",
            "MIGRATION_REQUIRED = 3",
            "N0-4C AND V3 AND compute_authorized",
            "N0-4C AND V4 AND current independent audit",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)
        self.assertLessEqual(len(text.splitlines()), 500)

    def test_description_is_trigger_only(self):
        text = self.read("SKILL.md")
        frontmatter = text.split("---", 2)[1]
        self.assertIn("description: >-", frontmatter)
        self.assertIn("Use when defining, auditing, revising, computing", frontmatter)
        self.assertNotIn("Guides literature-constrained", frontmatter)

    def test_templates_cover_every_schema_v2_artifact(self):
        text = self.read("templates.md")
        for artifact in (
            "workflow_state.json",
            "claim_inventory.json",
            "theory_obligation_registry.json",
            "protocol_contract.json",
            "baseline_budget.json",
            "claim_code_trace.json",
            "frontier_coverage.json",
            "audit_manifest.json",
            "independent_audit.json",
            "compute_evidence.json",
        ):
            with self.subTest(artifact=artifact):
                self.assertIn(artifact, text)
        for claim_type in (
            "THEOREM",
            "LEMMA",
            "COROLLARY",
            "PROPOSITION",
            "DEFINITION",
            "ALGORITHM",
            "ALGORITHM_GUARANTEE",
            "ALGORITHM_PERFORMANCE",
            "ONLINE_ALGORITHM",
            "METHOD",
            "ONLINE",
            "PROTOCOL",
            "EMPIRICAL",
            "BASELINE",
            "COMPLEXITY",
        ):
            with self.subTest(claim_type=claim_type):
                self.assertIn(claim_type, text)

    def test_supporting_resources_bind_validity_and_compute_contracts(self):
        reference = self.read("reference.md")
        for required in (
            "G9",
            "theory audit",
            "protocol audit",
            "code audit",
            "V2",
            "V3",
            "V4",
        ):
            with self.subTest(resource="reference.md", required=required):
                self.assertIn(required, reference)

        evidence = self.read("evidence-pipeline.md")
        for required in (
            "OFFICIAL_METADATA",
            "OFFICIAL_ABSTRACT",
            "FULL_ARTICLE_HTML",
            "FULL_ARTICLE_PDF",
            "PROOF_OR_APPENDIX",
            "importance_history",
            "reclassifications",
            "DOWNLOAD_BLOCKED",
        ):
            with self.subTest(resource="evidence-pipeline.md", required=required):
                self.assertIn(required, evidence)

        compute = self.read("compute-funnel.md")
        for required in (
            "N0-4C",
            "V3",
            "POSTCOMPUTE_CLAIM_FREEZE",
            "FINAL_VALIDITY_AUDIT",
            "V4",
        ):
            with self.subTest(resource="compute-funnel.md", required=required):
                self.assertIn(required, compute)

    def test_case_lessons_capture_general_claim_integrity_failures(self):
        text = self.read("case-lessons.md")
        for required in (
            "exact claim",
            "nonzero nuisance",
            "empirical-to-theorem",
            "stale audit",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)
        self.assertNotIn("paper1-failure-case", text)

    def test_readme_and_tutorial_explain_immutable_innovation_path(self):
        readme = self.read("README.md")
        for required in (
            "路径一经确认",
            "`PRIMARY`",
            "`SUPPORTING`",
            "`INNOVATION_PATH_DRIFT`",
            "显式重启",
            "算法优化路径中发现的定理",
            "主创新路径：R2",
            "主创新形式：F4",
        ):
            with self.subTest(document="README.md", required=required):
                self.assertIn(required, readme)

        tutorial = self.read("docs/tutorial.md")
        for required in (
            "### 10.6 路径锁定贯穿全过程",
            "算法优化路径",
            "支持性理论",
            "不得转向理论创新",
            "用户明确确认",
            "新一代路径",
            "回到 `SCOPE_LOCK`",
            "INNOVATION_PATH_DRIFT",
        ):
            with self.subTest(document="docs/tutorial.md", required=required):
                self.assertIn(required, tutorial)

        forbidden = "发现更有潜力的创新形式时可以直接切换"
        self.assertNotIn(forbidden, readme)
        self.assertNotIn(forbidden, tutorial)

    def test_standalone_schema_v3_fixture_is_ready_and_read_only(self):
        source = ROOT / "tests" / "fixtures" / "minimal-valid-v3"

        def snapshot(directory: Path) -> dict[str, str]:
            return {
                path.relative_to(directory).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in directory.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts
            }

        source_before = snapshot(source)
        with TemporaryDirectory(prefix="standalone-schema-v3-") as temporary:
            project = Path(temporary) / "minimal-valid-v3"
            copytree(source, project, ignore=lambda _path, names: {
                name for name in names if name == "__pycache__"
            })
            project_before = snapshot(project)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "validate_all.py"),
                    "--root",
                    str(project),
                    "--state",
                    str(project / "workflow_state.json"),
                    "--current-year",
                    "2026",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("validation_suite_status=READY", result.stdout)
            self.assertEqual(snapshot(project), project_before)
        self.assertEqual(snapshot(source), source_before)


if __name__ == "__main__":
    unittest.main()
