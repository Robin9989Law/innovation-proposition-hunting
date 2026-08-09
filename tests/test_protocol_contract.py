from __future__ import annotations

import hashlib
import os
import subprocess
import unittest
from pathlib import Path
from typing import Any

from tests.helpers import (
    load_json,
    make_valid_project,
    run_all_validator,
    run_script,
    write_json,
)


PROTOCOL = "protocol_contract.json"
BASELINES = "baseline_budget.json"
TRACE = "claim_code_trace.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProtocolContractTests(unittest.TestCase):
    def make_project(self, claim_profile: str = "ALGORITHM") -> Path:
        temporary_directory, project = make_valid_project(claim_profile=claim_profile)
        self.addCleanup(temporary_directory.cleanup)
        return project

    def run_protocol(self, project: Path) -> subprocess.CompletedProcess[str]:
        return run_script("validate_protocol_contract.py", project)

    def run_trace(self, project: Path) -> subprocess.CompletedProcess[str]:
        return run_script("validate_claim_code_trace.py", project)

    def test_minimal_algorithm_protocol_is_ready(self) -> None:
        completed = self.run_protocol(self.make_project())

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("protocol_contract_status=READY", completed.stdout)

    def test_minimal_algorithm_trace_is_ready(self) -> None:
        completed = self.run_trace(self.make_project())

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("claim_code_trace_status=READY", completed.stdout)

    def test_per_sample_online_claim_requires_passing_chronology_test(self) -> None:
        project = self.make_project()
        protocol = load_json(project / PROTOCOL)
        protocol["chronology_test"]["status"] = "MISSING"
        write_json(project / PROTOCOL, protocol)

        completed = self.run_protocol(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("ONLINE_CHRONOLOGY_UNVERIFIED", completed.stdout)

    def test_per_sample_claim_rejects_block_implementation_binding(self) -> None:
        project = self.make_project()
        trace = load_json(project / TRACE)
        binding = trace["traces"][0]
        block_path = project / "implementation/block_algorithm.py"
        binding["implementation_relative_path"] = "implementation/block_algorithm.py"
        binding["implementation_symbol"] = "evaluate_in_blocks"
        binding["implementation_sha256"] = sha256(block_path)
        write_json(project / TRACE, trace)

        completed = self.run_protocol(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("ONLINE_CHRONOLOGY_UNVERIFIED", completed.stdout)

    def test_strong_baseline_requires_common_tuning_contract(self) -> None:
        project = self.make_project()
        budgets = load_json(project / BASELINES)
        del budgets["comparators"][0]["regularization_search_space"]
        write_json(project / BASELINES, budgets)

        completed = self.run_protocol(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("BASELINE_BUDGET_INCOMPLETE", completed.stdout)

    def test_fair_budget_trigger_recognizes_approved_chinese_equivalents(self) -> None:
        project = self.make_project()
        inventory = load_json(project / "claim_inventory.json")
        algorithm_claim = inventory["claims"][1]
        algorithm_claim["statement"] = "算法一与强基线进行同预算的公平比较。"
        algorithm_claim["risk_terms"] = ["强基线", "同预算", "公平比较"]
        write_json(project / "claim_inventory.json", inventory)
        (project / BASELINES).unlink()

        completed = self.run_protocol(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("BASELINE_BUDGET_INCOMPLETE", completed.stdout)

    def test_bare_strong_comparison_language_triggers_budget_contract(self) -> None:
        project = self.make_project()
        inventory = load_json(project / "claim_inventory.json")
        algorithm_claim = inventory["claims"][1]
        algorithm_claim["statement"] = "Algorithm 1 is strong under the frozen protocol."
        algorithm_claim["risk_terms"] = ["strong"]
        write_json(project / "claim_inventory.json", inventory)
        (project / BASELINES).unlink()

        completed = self.run_protocol(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("BASELINE_BUDGET_INCOMPLETE", completed.stdout)

    def test_no_budget_language_does_not_require_baseline_contract(self) -> None:
        project = self.make_project()
        inventory = load_json(project / "claim_inventory.json")
        algorithm_claim = inventory["claims"][1]
        algorithm_claim["statement"] = "Algorithm 1 follows the frozen protocol."
        algorithm_claim["risk_terms"] = ["protocol"]
        write_json(project / "claim_inventory.json", inventory)
        (project / BASELINES).unlink()

        completed = self.run_protocol(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_each_required_protocol_field_is_strictly_required(self) -> None:
        fields = (
            "prediction_unit",
            "update_unit",
            "predict_update_order",
            "label_availability",
            "chronological_ordering",
            "split_strategy",
            "hyperparameter_selection_data",
            "development_data",
            "sealed_confirmation_data",
            "test_access_count",
            "update_semantics",
        )
        for field in fields:
            with self.subTest(field=field):
                project = self.make_project()
                protocol = load_json(project / PROTOCOL)
                del protocol[field]
                write_json(project / PROTOCOL, protocol)

                completed = self.run_protocol(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_PROTOCOL_FIELD", completed.stdout)
                self.assertIn(field, completed.stdout)

    def test_test_label_updates_require_all_four_adaptation_conditions(self) -> None:
        invalid_updates: tuple[tuple[str, Any], ...] = (
            ("supervised_online_adaptation", False),
            ("pre_update_scoring", False),
            ("operational_label_availability", False),
            ("evaluation_role", "CONFIRMATORY"),
        )
        for field, value in invalid_updates:
            with self.subTest(field=field):
                project = self.make_project()
                protocol = load_json(project / PROTOCOL)
                semantics = protocol["update_semantics"]
                semantics.update(
                    {
                        "uses_test_labels": True,
                        "supervised_online_adaptation": True,
                        "pre_update_scoring": True,
                        "operational_label_availability": True,
                        "evaluation_role": "NON_CONFIRMATORY",
                    }
                )
                semantics[field] = value
                write_json(project / PROTOCOL, protocol)

                completed = self.run_protocol(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_TEST_LABEL_UPDATE", completed.stdout)

    def test_explicit_nonconfirmatory_supervised_online_adaptation_is_allowed(self) -> None:
        project = self.make_project()
        protocol = load_json(project / PROTOCOL)
        protocol["update_semantics"] = {
            "uses_test_labels": True,
            "supervised_online_adaptation": True,
            "pre_update_scoring": True,
            "operational_label_availability": True,
            "evaluation_role": "NON_CONFIRMATORY",
        }
        write_json(project / PROTOCOL, protocol)

        completed = self.run_protocol(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_test_label_update_rejects_label_availability_contradiction(self) -> None:
        project = self.make_project()
        protocol = load_json(project / PROTOCOL)
        protocol["label_availability"] = "NEVER"
        protocol["update_semantics"] = {
            "uses_test_labels": True,
            "supervised_online_adaptation": True,
            "pre_update_scoring": True,
            "operational_label_availability": True,
            "evaluation_role": "NON_CONFIRMATORY",
        }
        write_json(project / PROTOCOL, protocol)

        completed = self.run_protocol(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("INVALID_TEST_LABEL_UPDATE", completed.stdout)

    def test_chronology_command_is_recorded_but_never_executed(self) -> None:
        project = self.make_project()
        marker = project / "must-not-exist"
        protocol = load_json(project / PROTOCOL)
        protocol["chronology_test"]["command"] = f"touch {marker}"
        write_json(project / PROTOCOL, protocol)

        completed = self.run_protocol(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertFalse(marker.exists())

    def test_current_chronology_output_hash_is_required(self) -> None:
        project = self.make_project()
        (project / "test_outputs/online_chronology_pass.json").write_text(
            "{}\n", encoding="utf-8"
        )

        completed = self.run_protocol(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("ONLINE_CHRONOLOGY_UNVERIFIED", completed.stdout)

    def test_every_algorithm_claim_requires_exactly_one_trace(self) -> None:
        project = self.make_project()
        trace = load_json(project / TRACE)
        trace["traces"] = []
        write_json(project / TRACE, trace)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("MISSING_CLAIM_CODE_TRACE", completed.stdout)

    def test_trace_rejects_missing_symbols(self) -> None:
        for field in ("pseudocode_symbol", "implementation_symbol"):
            with self.subTest(field=field):
                project = self.make_project()
                trace = load_json(project / TRACE)
                trace["traces"][0][field] = ""
                write_json(project / TRACE, trace)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_TRACE_FIELD", completed.stdout)
                self.assertIn(field, completed.stdout)

    def test_trace_test_must_list_target_claim_id(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            test_path.read_text(encoding="utf-8").replace(
                "C-ALGORITHM-1", "C-UNRELATED-1"
            ),
            encoding="utf-8",
        )
        trace = load_json(project / TRACE)
        trace["traces"][0]["executable_test_sha256"] = sha256(test_path)
        write_json(project / TRACE, trace)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("TRACE_TEST_CLAIM_ID_MISSING", completed.stdout)

    def test_pass_manifest_must_list_target_claim_and_pass(self) -> None:
        project = self.make_project()
        output_path = project / "test_outputs/online_chronology_pass.json"
        manifest = load_json(output_path)
        manifest["target_claim_ids"] = ["C-UNRELATED-1"]
        write_json(output_path, manifest)
        trace = load_json(project / TRACE)
        trace["traces"][0]["pass_output_sha256"] = sha256(output_path)
        write_json(project / TRACE, trace)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("TRACE_OUTPUT_CLAIM_ID_MISSING", completed.stdout)

    def test_trace_rejects_current_file_hash_mismatch(self) -> None:
        project = self.make_project()
        implementation = project / "implementation/online_algorithm.py"
        implementation.write_text(
            implementation.read_text(encoding="utf-8") + "\n# changed\n",
            encoding="utf-8",
        )

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("IMPLEMENTATION_HASH_MISMATCH", completed.stdout)

    def test_trace_rejects_duplicate_and_orphan_bindings(self) -> None:
        cases = ("duplicate", "orphan")
        for case in cases:
            with self.subTest(case=case):
                project = self.make_project()
                trace = load_json(project / TRACE)
                extra = dict(trace["traces"][0])
                if case == "orphan":
                    extra["claim_id"] = "C-ORPHAN-1"
                trace["traces"].append(extra)
                write_json(project / TRACE, trace)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn(
                    "DUPLICATE_CLAIM_CODE_TRACE" if case == "duplicate" else "ORPHAN_CLAIM_CODE_TRACE",
                    completed.stdout,
                )

    def test_trace_rejects_symlink_and_fifo_references_without_blocking(self) -> None:
        cases = ("symlink", "fifo")
        for case in cases:
            with self.subTest(case=case):
                project = self.make_project()
                unsafe = project / f"implementation/{case}.py"
                if case == "symlink":
                    unsafe.symlink_to("online_algorithm.py")
                else:
                    os.mkfifo(unsafe)
                trace = load_json(project / TRACE)
                trace["traces"][0]["implementation_relative_path"] = (
                    f"implementation/{case}.py"
                )
                write_json(project / TRACE, trace)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("UNSAFE_TRACE_PATH", completed.stdout)

    def test_trace_uses_strict_json_and_strict_types(self) -> None:
        project = self.make_project()
        trace_path = project / TRACE
        text = trace_path.read_text(encoding="utf-8")
        trace_path.write_text(
            text.replace(
                '  "schema_version": "2.0",\n',
                '  "schema_version": "2.0",\n  "schema_version": "2.0",\n',
            ),
            encoding="utf-8",
        )

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("DUPLICATE_KEY:$.schema_version", completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)

    def test_trace_claim_id_type_error_is_stable(self) -> None:
        for malformed in ([], {}):
            with self.subTest(malformed=malformed):
                project = self.make_project()
                trace = load_json(project / TRACE)
                trace["traces"][0]["claim_id"] = malformed
                write_json(project / TRACE, trace)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_TRACE_FIELD", completed.stdout)
                self.assertNotIn("VALIDATOR_ERROR", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_protocol_and_trace_validators_are_read_only(self) -> None:
        project = self.make_project()
        before = {
            path.relative_to(project).as_posix(): sha256(path)
            for path in project.rglob("*")
            if path.is_file()
        }

        protocol = self.run_protocol(project)
        trace = self.run_trace(project)

        after = {
            path.relative_to(project).as_posix(): sha256(path)
            for path in project.rglob("*")
            if path.is_file()
        }
        self.assertEqual(0, protocol.returncode, protocol.stdout + protocol.stderr)
        self.assertEqual(0, trace.returncode, trace.stdout + trace.stderr)
        self.assertEqual(before, after)

    def test_validate_all_routes_algorithm_gates_for_algorithm_and_mixed(self) -> None:
        for profile in ("ALGORITHM", "MIXED"):
            with self.subTest(profile=profile):
                project = self.make_project(profile)
                state = load_json(project / "workflow_state.json")
                state["active_state"] = "VALIDITY_AUDIT"
                state["resume_state"] = "VALIDITY_AUDIT"
                write_json(project / "workflow_state.json", state)
                (project / PROTOCOL).unlink()
                (project / TRACE).unlink()

                completed = run_all_validator(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("PROTOCOL_CONTRACT_REQUIRED", completed.stdout)
                self.assertIn("CLAIM_CODE_TRACE_REQUIRED", completed.stdout)

    def test_validate_all_does_not_require_algorithm_gates_for_theory(self) -> None:
        project = self.make_project("THEORY")
        state = load_json(project / "workflow_state.json")
        state["active_state"] = "VALIDITY_AUDIT"
        state["resume_state"] = "VALIDITY_AUDIT"
        write_json(project / "workflow_state.json", state)
        (project / PROTOCOL).unlink()
        (project / TRACE).unlink()
        (project / BASELINES).unlink()

        completed = run_all_validator(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
