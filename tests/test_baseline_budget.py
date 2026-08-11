from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from tests.helpers import (
    REPOSITORY_ROOT,
    load_json,
    make_valid_project,
    run_script,
    write_json,
)


BASELINES = "baseline_budget.json"


class BaselineBudgetTests(unittest.TestCase):
    """validate_baseline_budget：去 trigger 门控的 baseline 预算硬校验。

    只要 inventory 存在 ALGORITHM 类 claim，baseline_budget.json 就必须存在
    且每个 comparator 绑定到至少一个 algorithm claim、全部 algorithm claims
    被覆盖；不再依赖 manuscript/claim 文本中的 "strong baseline" 等触发词。
    """

    def make_project(self, claim_profile: str = "ALGORITHM") -> Path:
        temporary_directory, project = make_valid_project(claim_profile=claim_profile)
        self.addCleanup(temporary_directory.cleanup)
        return project

    def run_baselines(
        self, project: Path, extra_args: tuple[str, ...] = ()
    ) -> subprocess.CompletedProcess[str]:
        return run_script("validate_baseline_budget.py", project, extra_args)

    def rewrite_inventory_without_budget_language(self, project: Path) -> None:
        inventory = load_json(project / "claim_inventory.json")
        algorithm_claim = inventory["claims"][1]
        algorithm_claim["statement"] = "Algorithm 1 follows the frozen protocol."
        algorithm_claim["risk_terms"] = ["protocol"]
        write_json(project / "claim_inventory.json", inventory)

    def test_valid_project_is_ready(self) -> None:
        completed = self.run_baselines(self.make_project())

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("baseline_budget_status=READY", completed.stdout)

    def test_budget_required_without_any_trigger_language(self) -> None:
        # 无 trigger 词也强制：事故项目靠回避触发词绕过基线预算。
        project = self.make_project()
        self.rewrite_inventory_without_budget_language(project)
        (project / BASELINES).unlink()

        completed = self.run_baselines(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("BASELINE_BUDGET_INCOMPLETE", completed.stdout)
        self.assertIn("baseline_budget.json:missing", completed.stdout)

    def test_missing_budget_file_reports_every_algorithm_claim(self) -> None:
        project = self.make_project()
        (project / BASELINES).unlink()

        completed = self.run_baselines(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("C-ALGORITHM-1\tbaseline_budget.json:missing", completed.stdout)

    def test_comparator_without_claim_ids_is_invalid(self) -> None:
        project = self.make_project()
        budgets = load_json(project / BASELINES)
        del budgets["comparators"][0]["claim_ids"]
        write_json(project / BASELINES, budgets)

        completed = self.run_baselines(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("claim_ids:expected_nonempty_unique_string_list", completed.stdout)

    def test_comparator_empty_claim_ids_is_invalid(self) -> None:
        project = self.make_project()
        budgets = load_json(project / BASELINES)
        budgets["comparators"][0]["claim_ids"] = []
        write_json(project / BASELINES, budgets)

        completed = self.run_baselines(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("claim_ids:expected_nonempty_unique_string_list", completed.stdout)

    def test_comparator_claim_ids_without_algorithm_intersection_is_invalid(self) -> None:
        # comparator 只绑定非 algorithm claim（C-THEOREM-1 是 THEOREM）。
        project = self.make_project()
        budgets = load_json(project / BASELINES)
        budgets["comparators"][0]["claim_ids"] = ["C-THEOREM-1"]
        write_json(project / BASELINES, budgets)

        completed = self.run_baselines(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("claim_ids:no_algorithm_claim_intersection", completed.stdout)
        self.assertIn("no_comparator_covers_algorithm_claim", completed.stdout)

    def test_uncovered_algorithm_claim_is_invalid(self) -> None:
        project = self.make_project()
        inventory = load_json(project / "claim_inventory.json")
        extra = dict(inventory["claims"][1])
        extra["claim_id"] = "C-ALGORITHM-2"
        inventory["claims"].append(extra)
        write_json(project / "claim_inventory.json", inventory)

        completed = self.run_baselines(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn(
            "C-ALGORITHM-2\tno_comparator_covers_algorithm_claim", completed.stdout
        )

    def test_comparator_fields_enforced_without_trigger_language(self) -> None:
        # comparator 字段契约不再由 trigger_claims 门控。
        project = self.make_project()
        self.rewrite_inventory_without_budget_language(project)
        budgets = load_json(project / BASELINES)
        del budgets["comparators"][0]["regularization_search_space"]
        write_json(project / BASELINES, budgets)

        completed = self.run_baselines(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn(
            "regularization_search_space:missing_or_invalid", completed.stdout
        )

    def test_comparator_with_bad_seeds_is_invalid(self) -> None:
        project = self.make_project()
        budgets = load_json(project / BASELINES)
        budgets["comparators"][0]["seeds"] = [11, 11]
        write_json(project / BASELINES, budgets)

        completed = self.run_baselines(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("seeds:missing_or_invalid", completed.stdout)

    def test_duplicate_comparator_id_is_invalid(self) -> None:
        project = self.make_project()
        budgets = load_json(project / BASELINES)
        budgets["comparators"].append(dict(budgets["comparators"][0]))
        write_json(project / BASELINES, budgets)

        completed = self.run_baselines(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("duplicate_comparator_id:count:2", completed.stdout)

    def test_schema_version_still_checked(self) -> None:
        project = self.make_project()
        budgets = load_json(project / BASELINES)
        budgets["schema_version"] = "1.0"
        write_json(project / BASELINES, budgets)

        completed = self.run_baselines(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("schema_version:1.0", completed.stdout)

    def test_validation_epoch_still_checked(self) -> None:
        project = self.make_project()
        budgets = load_json(project / BASELINES)
        budgets["validation_epoch"] = 99
        write_json(project / BASELINES, budgets)

        completed = self.run_baselines(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("validation_epoch:99;state:1", completed.stdout)

    def test_comparators_must_be_a_list(self) -> None:
        project = self.make_project()
        budgets = load_json(project / BASELINES)
        budgets["comparators"] = "B-COMPARATOR-A"
        write_json(project / BASELINES, budgets)

        completed = self.run_baselines(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("comparators:expected_list", completed.stdout)

    def test_theory_profile_has_no_baseline_obligation(self) -> None:
        project = self.make_project(claim_profile="THEORY")
        (project / BASELINES).unlink()

        completed = self.run_baselines(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("baseline_budget_status=READY", completed.stdout)

    def test_incident_fixture_missing_budget_is_reported(self) -> None:
        # 事故负例：fixture 无 baseline_budget.json 且有 algorithm claims
        # （C-MODEL-1=METHOD、C-COMPLEX-1=COMPLEXITY），去门控后必须报缺失。
        completed = self.run_baselines(REPOSITORY_ROOT / "tests" / "fixtures" / "incident-2026-08")

        self.assertEqual(1, completed.returncode)
        self.assertIn("C-MODEL-1\tbaseline_budget.json:missing", completed.stdout)
        self.assertIn("C-COMPLEX-1\tbaseline_budget.json:missing", completed.stdout)

    def test_baseline_only_forwarding_in_protocol_cli_still_works(self) -> None:
        # 兼容入口：validate_protocol_contract.py --baseline-only 转发新模块。
        project = self.make_project()
        budgets = load_json(project / BASELINES)
        del budgets["comparators"][0]["seeds"]
        write_json(project / BASELINES, budgets)

        completed = run_script(
            "validate_protocol_contract.py", project, ["--baseline-only"]
        )

        self.assertEqual(1, completed.returncode)
        self.assertIn("BASELINE_BUDGET_INCOMPLETE", completed.stdout)
        self.assertIn("seeds:missing_or_invalid", completed.stdout)


if __name__ == "__main__":
    unittest.main()
