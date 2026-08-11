from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from tests.helpers import (
    REPOSITORY_ROOT,
    load_json,
    make_valid_project,
    run_script,
    write_json,
)


INCIDENT = REPOSITORY_ROOT / "tests" / "fixtures" / "incident-2026-08"


def register_exploration(project: Path, relative: str, *, sha256: str | None = None) -> None:
    digest = sha256
    if digest is None:
        digest = hashlib.sha256((project / relative).read_bytes()).hexdigest()
    write_json(
        project / "exploration_registry.json",
        {
            "schema_version": "2.0",
            "explorations": [
                {
                    "id": "exp-001",
                    "path": relative,
                    "sha256": digest,
                    "registered_at": "2026-08-10T00:00:00Z",
                    "data_role": "EXPLORATION_PERMANENT",
                    "description": "synthetic exploration artifact",
                }
            ],
        },
    )


class IncidentLeakTests(unittest.TestCase):
    """事故 fixture：S0 数字 0.398 泄入 collision-round1 / output_claim_support 必报。"""

    def test_default_warning_exit_zero(self) -> None:
        result = run_script("validate_exploration_firewall.py", INCIDENT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WARNING\tEXPLORATION_LEAK", result.stdout)
        self.assertIn("token:0.398", result.stdout)
        self.assertIn("frozen_artifact:collision-round1.md", result.stdout)
        self.assertIn("frozen_artifact:output_claim_support.json", result.stdout)

    def test_strict_escalates_to_invalid(self) -> None:
        result = run_script(
            "validate_exploration_firewall.py", INCIDENT, ("--strict-new-checks",)
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("INVALID\tEXPLORATION_LEAK", result.stdout)

    def test_literature_numbers_not_flagged(self) -> None:
        # 15.6/54.6 等文献数字出现在 literature_claim_registry，享有 provenance 豁免。
        result = run_script("validate_exploration_firewall.py", INCIDENT)
        self.assertNotIn("token:15.6", result.stdout)
        self.assertNotIn("token:54.6", result.stdout)


class FirewallSyntheticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp, self.project = make_valid_project()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_firewall(self, *extra: str):
        return run_script("validate_exploration_firewall.py", self.project, extra)

    def test_no_registry_no_obligation(self) -> None:
        result = self.run_firewall()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("EXPLORATION_LEAK", result.stdout)

    def test_clean_registration(self) -> None:
        (self.project / "s0_notes.md").write_text(
            "# pilot\nresult 0.742 仅在探索中\n", encoding="utf-8"
        )
        register_exploration(self.project, "s0_notes.md")
        result = self.run_firewall()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("EXPLORATION_LEAK", result.stdout)

    def test_leak_into_markdown(self) -> None:
        (self.project / "s0_notes.md").write_text(
            "# pilot\nmeasured 0.742 here\n", encoding="utf-8"
        )
        register_exploration(self.project, "s0_notes.md")
        (self.project / "collision-round1.md").write_text(
            "# collision\n数字 0.742 被引用\n", encoding="utf-8"
        )
        result = self.run_firewall()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WARNING\tEXPLORATION_LEAK", result.stdout)
        self.assertIn("frozen_artifact:collision-round1.md", result.stdout)
        strict = self.run_firewall("--strict-new-checks")
        self.assertEqual(strict.returncode, 1, strict.stderr)

    def test_leak_unicode_minus_normalized(self) -> None:
        (self.project / "s0_notes.md").write_text(
            "correlation −0.398 observed\n", encoding="utf-8"
        )
        register_exploration(self.project, "s0_notes.md")
        (self.project / "novelty-audit.md").write_text(
            "audit cites r=−0.398\n", encoding="utf-8"
        )
        result = self.run_firewall()
        self.assertIn("token:0.398", result.stdout)
        self.assertIn("frozen_artifact:novelty-audit.md", result.stdout)

    def test_provenance_exemption_via_literature_registry(self) -> None:
        (self.project / "s0_notes.md").write_text(
            "literature reports 15.6 and my pilot also saw 15.6\n", encoding="utf-8"
        )
        register_exploration(self.project, "s0_notes.md")
        write_json(
            self.project / "near_neighbor_registry.json",
            {"works": [{"id": "W-1", "result": "-15.6%"}]},
        )
        (self.project / "collision-round1.md").write_text(
            "K1: 储能需求 −15.6%（文献引用）\n", encoding="utf-8"
        )
        result = self.run_firewall()
        self.assertNotIn("EXPLORATION_LEAK", result.stdout)

    def test_stale_registered_artifact(self) -> None:
        (self.project / "s0_notes.md").write_text("v1\n", encoding="utf-8")
        register_exploration(self.project, "s0_notes.md")
        (self.project / "s0_notes.md").write_text("v2 edited\n", encoding="utf-8")
        result = self.run_firewall()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("EXPLORATION_ARTIFACT_STALE", result.stdout)

    def test_missing_registered_artifact(self) -> None:
        (self.project / "s0_notes.md").write_text("v1\n", encoding="utf-8")
        register_exploration(self.project, "s0_notes.md")
        (self.project / "s0_notes.md").unlink()
        result = self.run_firewall()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("EXPLORATION_ARTIFACT_MISSING", result.stdout)

    def test_invalid_schema_version(self) -> None:
        write_json(
            self.project / "exploration_registry.json",
            {"schema_version": "1.0", "explorations": []},
        )
        result = self.run_firewall()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("INVALID_EXPLORATION_REGISTRY_SCHEMA", result.stdout)

    def test_weak_numbers_ignored(self) -> None:
        # 有效位 <3 的数字（0.5、2.0）不构成 token，不报。
        (self.project / "s0_notes.md").write_text(
            "weights 0.5 and 2.0\n", encoding="utf-8"
        )
        register_exploration(self.project, "s0_notes.md")
        (self.project / "collision-round1.md").write_text(
            "config 0.5 then 2.0\n", encoding="utf-8"
        )
        result = self.run_firewall()
        self.assertNotIn("EXPLORATION_LEAK", result.stdout)


class UnregisteredComputeArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp, self.project = make_valid_project()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_state(self, *extra: str):
        return run_script("validate_workflow_state.py", self.project, extra)

    def test_unregistered_s0_artifact_warns(self) -> None:
        (self.project / "s0_pilot.md").write_text("# pilot\n", encoding="utf-8")
        result = self.run_state("--current-year", "2026")
        self.assertIn("WARNING\tUNREGISTERED_COMPUTE_ARTIFACT", result.stdout)
        self.assertIn("path:s0_pilot.md", result.stdout)
        strict = self.run_state("--current-year", "2026", "--strict-new-checks")
        self.assertIn("INVALID\tUNREGISTERED_COMPUTE_ARTIFACT", strict.stdout)
        self.assertEqual(strict.returncode, 1, strict.stderr)

    def test_registered_artifact_silent(self) -> None:
        (self.project / "s0_pilot.md").write_text("# pilot\n", encoding="utf-8")
        register_exploration(self.project, "s0_pilot.md")
        result = self.run_state("--current-year", "2026")
        self.assertNotIn("UNREGISTERED_COMPUTE_ARTIFACT", result.stdout)

    def test_authorized_compute_not_scanned(self) -> None:
        state = load_json(self.project / "workflow_state.json")
        state["gates"]["compute_authorized"] = True
        write_json(self.project / "workflow_state.json", state)
        (self.project / "s0_pilot.md").write_text("# pilot\n", encoding="utf-8")
        result = self.run_state("--current-year", "2026")
        self.assertNotIn("UNREGISTERED_COMPUTE_ARTIFACT", result.stdout)


if __name__ == "__main__":
    unittest.main()
