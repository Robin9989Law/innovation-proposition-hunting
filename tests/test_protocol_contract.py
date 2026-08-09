from __future__ import annotations

import hashlib
import json
import os
import shlex
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

    def refresh_test_and_output_hashes(self, project: Path) -> None:
        test_path = project / "checks/check_online_chronology.py"
        output_path = project / "test_outputs/online_chronology_pass.json"
        test_hash = sha256(test_path)
        manifest = load_json(output_path)
        manifest["executable_test_sha256"] = test_hash
        write_json(output_path, manifest)
        output_hash = sha256(output_path)

        protocol = load_json(project / PROTOCOL)
        protocol["chronology_test"]["output_sha256"] = output_hash
        write_json(project / PROTOCOL, protocol)
        trace = load_json(project / TRACE)
        for binding in trace["traces"]:
            binding["executable_test_sha256"] = test_hash
            binding["pass_output_sha256"] = output_hash
        write_json(project / TRACE, trace)

    def refresh_implementation_hashes(self, project: Path) -> None:
        implementation_path = project / "implementation/online_algorithm.py"
        implementation_hash = sha256(implementation_path)
        protocol = load_json(project / PROTOCOL)
        protocol["chronology_test"]["implementation_sha256"] = implementation_hash
        write_json(project / PROTOCOL, protocol)
        trace = load_json(project / TRACE)
        trace["traces"][0]["implementation_sha256"] = implementation_hash
        write_json(project / TRACE, trace)
        output_path = project / "test_outputs/online_chronology_pass.json"
        output = load_json(output_path)
        output["implementation_sha256"] = implementation_hash
        write_json(output_path, output)
        self.refresh_test_and_output_hashes(project)

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

    def test_strong_comparison_risk_term_triggers_budget_contract(self) -> None:
        project = self.make_project()
        inventory = load_json(project / "claim_inventory.json")
        algorithm_claim = inventory["claims"][1]
        algorithm_claim["statement"] = "Algorithm 1 follows the frozen protocol."
        algorithm_claim["risk_terms"] = ["strong comparison"]
        write_json(project / "claim_inventory.json", inventory)
        (project / BASELINES).unlink()

        completed = self.run_protocol(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("BASELINE_BUDGET_INCOMPLETE", completed.stdout)

    def test_strong_comparison_statement_uses_ascii_word_boundary(self) -> None:
        project = self.make_project()
        inventory = load_json(project / "claim_inventory.json")
        algorithm_claim = inventory["claims"][1]
        algorithm_claim["statement"] = "Algorithm 1 makes a strong comparison."
        algorithm_claim["risk_terms"] = ["protocol"]
        write_json(project / "claim_inventory.json", inventory)
        (project / BASELINES).unlink()

        completed = self.run_protocol(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("BASELINE_BUDGET_INCOMPLETE", completed.stdout)

    def test_strongly_wording_does_not_trigger_budget_contract(self) -> None:
        variants = (
            ("Algorithm 1 is strongly regularized.", ["protocol"]),
            ("Algorithm 1 follows the frozen protocol.", ["strongly comparative"]),
        )
        for statement, risk_terms in variants:
            with self.subTest(statement=statement, risk_terms=risk_terms):
                project = self.make_project()
                inventory = load_json(project / "claim_inventory.json")
                algorithm_claim = inventory["claims"][1]
                algorithm_claim["statement"] = statement
                algorithm_claim["risk_terms"] = risk_terms
                write_json(project / "claim_inventory.json", inventory)
                (project / BASELINES).unlink()

                completed = self.run_protocol(project)

                self.assertEqual(
                    0, completed.returncode, completed.stdout + completed.stderr
                )

    def test_stronger_and_strongest_comparison_context_triggers_budget(self) -> None:
        variants = (
            ("Algorithm 1 makes a stronger comparison.", ["protocol"]),
            ("Algorithm 1 uses the strongest baseline.", ["protocol"]),
            ("Algorithm 1 follows the frozen protocol.", ["stronger baseline"]),
        )
        for statement, risk_terms in variants:
            with self.subTest(statement=statement, risk_terms=risk_terms):
                project = self.make_project()
                inventory = load_json(project / "claim_inventory.json")
                algorithm_claim = inventory["claims"][1]
                algorithm_claim["statement"] = statement
                algorithm_claim["risk_terms"] = risk_terms
                write_json(project / "claim_inventory.json", inventory)
                (project / BASELINES).unlink()

                completed = self.run_protocol(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("BASELINE_BUDGET_INCOMPLETE", completed.stdout)

    def test_stronger_without_comparison_context_does_not_trigger_budget(self) -> None:
        project = self.make_project()
        inventory = load_json(project / "claim_inventory.json")
        algorithm_claim = inventory["claims"][1]
        algorithm_claim["statement"] = "Algorithm 1 uses stronger regularization."
        algorithm_claim["risk_terms"] = ["protocol"]
        write_json(project / "claim_inventory.json", inventory)
        (project / BASELINES).unlink()

        completed = self.run_protocol(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

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

    def test_canonical_chinese_fair_risk_term_triggers_budget_contract(self) -> None:
        project = self.make_project()
        inventory = load_json(project / "claim_inventory.json")
        inventory["claims"][1]["statement"] = "算法遵循冻结协议。"
        inventory["claims"][1]["risk_terms"] = ["公平"]
        write_json(project / "claim_inventory.json", inventory)
        (project / BASELINES).unlink()

        completed = self.run_protocol(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("BASELINE_BUDGET_INCOMPLETE", completed.stdout)

    def test_chinese_fair_comparison_grammar_triggers_budget_contract(self) -> None:
        statements = (
            "我们进行公平的比较。",
            "我们公平地比较这些方法。",
            "本文报告公平性比较。",
            "我们作公平比较。",
        )
        for statement in statements:
            with self.subTest(statement=statement):
                project = self.make_project()
                inventory = load_json(project / "claim_inventory.json")
                inventory["claims"][1]["statement"] = statement
                inventory["claims"][1]["risk_terms"] = ["protocol"]
                write_json(project / "claim_inventory.json", inventory)
                (project / BASELINES).unlink()

                completed = self.run_protocol(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("BASELINE_BUDGET_INCOMPLETE", completed.stdout)

    def test_fairness_prose_without_comparison_does_not_trigger_budget(self) -> None:
        project = self.make_project()
        inventory = load_json(project / "claim_inventory.json")
        inventory["claims"][1]["statement"] = "本文讨论公平性约束及其社会含义。"
        inventory["claims"][1]["risk_terms"] = ["protocol"]
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

    def test_protocol_unit_and_order_matrix_accepts_matching_modes(self) -> None:
        variants = (
            ("SAMPLE", "SAMPLE", "PREDICT_THEN_UPDATE", "AFTER_EACH_PREDICTION"),
            ("BATCH", "BATCH", "BATCH_PREDICT_THEN_UPDATE", "AFTER_BATCH"),
            ("BLOCK", "BLOCK", "BLOCK_PREDICT_THEN_UPDATE", "AFTER_BLOCK"),
        )
        for prediction, update, order, label in variants:
            with self.subTest(prediction=prediction):
                project = self.make_project()
                protocol = load_json(project / PROTOCOL)
                protocol.update(
                    {
                        "prediction_unit": prediction,
                        "update_unit": update,
                        "predict_update_order": order,
                        "label_availability": label,
                    }
                )
                protocol["update_semantics"] = {
                    "uses_test_labels": True,
                    "supervised_online_adaptation": True,
                    "pre_update_scoring": True,
                    "operational_label_availability": True,
                    "evaluation_role": "NON_CONFIRMATORY",
                }
                write_json(project / PROTOCOL, protocol)

                completed = self.run_protocol(project)

                self.assertEqual(
                    0, completed.returncode, completed.stdout + completed.stderr
                )

    def test_sequence_contract_accepts_only_frozen_predict_only_mode(self) -> None:
        project = self.make_project()
        protocol = load_json(project / PROTOCOL)
        protocol.update(
            {
                "prediction_unit": "SEQUENCE",
                "update_unit": "NONE",
                "predict_update_order": "PREDICT_ONLY",
                "label_availability": "NEVER",
            }
        )
        protocol["update_semantics"].update(
            {
                "uses_test_labels": False,
                "supervised_online_adaptation": False,
                "operational_label_availability": False,
            }
        )
        write_json(project / PROTOCOL, protocol)

        completed = self.run_protocol(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_sequence_contract_rejects_updates_labels_and_adaptation(self) -> None:
        mutations: tuple[tuple[str, str, Any], ...] = (
            ("protocol", "update_unit", "BLOCK"),
            ("protocol", "update_unit", "BATCH"),
            ("protocol", "update_unit", "SAMPLE"),
            ("protocol", "predict_update_order", "BLOCK_PREDICT_THEN_UPDATE"),
            ("protocol", "label_availability", "AFTER_BLOCK"),
            ("protocol", "label_availability", "AFTER_BATCH"),
            ("protocol", "label_availability", "AFTER_EACH_PREDICTION"),
            ("semantics", "uses_test_labels", True),
            ("semantics", "supervised_online_adaptation", True),
            ("semantics", "operational_label_availability", True),
        )
        for target, field, value in mutations:
            with self.subTest(target=target, field=field, value=value):
                project = self.make_project()
                protocol = load_json(project / PROTOCOL)
                protocol.update(
                    {
                        "prediction_unit": "SEQUENCE",
                        "update_unit": "NONE",
                        "predict_update_order": "PREDICT_ONLY",
                        "label_availability": "NEVER",
                    }
                )
                protocol["update_semantics"].update(
                    {
                        "uses_test_labels": False,
                        "supervised_online_adaptation": False,
                        "operational_label_availability": False,
                    }
                )
                if target == "protocol":
                    protocol[field] = value
                    if field == "label_availability":
                        protocol["update_semantics"][
                            "operational_label_availability"
                        ] = True
                else:
                    protocol["update_semantics"][field] = value
                write_json(project / PROTOCOL, protocol)

                completed = self.run_protocol(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_PROTOCOL_MATRIX", completed.stdout)

    def test_protocol_unit_and_order_matrix_rejects_crossed_modes(self) -> None:
        variants = (
            ("SAMPLE", "BLOCK", "PREDICT_THEN_UPDATE"),
            ("SAMPLE", "SAMPLE", "BLOCK_PREDICT_THEN_UPDATE"),
            ("BATCH", "SAMPLE", "BATCH_PREDICT_THEN_UPDATE"),
            ("BLOCK", "BLOCK", "BATCH_PREDICT_THEN_UPDATE"),
        )
        for prediction, update, order in variants:
            with self.subTest(prediction=prediction, update=update, order=order):
                project = self.make_project()
                protocol = load_json(project / PROTOCOL)
                protocol["prediction_unit"] = prediction
                protocol["update_unit"] = update
                protocol["predict_update_order"] = order
                write_json(project / PROTOCOL, protocol)

                completed = self.run_protocol(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_PROTOCOL_MATRIX", completed.stdout)

    def test_supervised_adaptation_requires_test_labels_and_available_labels(self) -> None:
        variants = ((False, "AFTER_EACH_PREDICTION"), (True, "NEVER"))
        for uses_labels, availability in variants:
            with self.subTest(uses_labels=uses_labels, availability=availability):
                project = self.make_project()
                protocol = load_json(project / PROTOCOL)
                protocol["label_availability"] = availability
                protocol["update_semantics"] = {
                    "uses_test_labels": uses_labels,
                    "supervised_online_adaptation": True,
                    "pre_update_scoring": True,
                    "operational_label_availability": availability != "NEVER",
                    "evaluation_role": "NON_CONFIRMATORY",
                }
                write_json(project / PROTOCOL, protocol)

                completed = self.run_protocol(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_PROTOCOL_MATRIX", completed.stdout)

    def test_operational_label_flag_matches_top_level_availability(self) -> None:
        variants = (("AFTER_EACH_PREDICTION", False), ("NEVER", True))
        for availability, operational in variants:
            with self.subTest(availability=availability, operational=operational):
                project = self.make_project()
                protocol = load_json(project / PROTOCOL)
                protocol["label_availability"] = availability
                protocol["update_semantics"]["operational_label_availability"] = operational
                write_json(project / PROTOCOL, protocol)

                completed = self.run_protocol(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_PROTOCOL_MATRIX", completed.stdout)

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
        malicious_command = f"touch {marker}"
        protocol = load_json(project / PROTOCOL)
        protocol["chronology_test"]["command"] = malicious_command
        write_json(project / PROTOCOL, protocol)
        output_path = project / "test_outputs/online_chronology_pass.json"
        output = load_json(output_path)
        output["command"] = malicious_command
        write_json(output_path, output)
        output_hash = sha256(output_path)
        protocol = load_json(project / PROTOCOL)
        protocol["chronology_test"]["output_sha256"] = output_hash
        write_json(project / PROTOCOL, protocol)
        trace = load_json(project / TRACE)
        trace["traces"][0]["pass_output_sha256"] = output_hash
        write_json(project / TRACE, trace)

        completed = self.run_protocol(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertFalse(marker.exists())

    def test_protocol_and_trace_must_share_exact_output_evidence(self) -> None:
        project = self.make_project()
        original = project / "test_outputs/online_chronology_pass.json"
        alternate = project / "test_outputs/alternate_online_pass.json"
        alternate_manifest = load_json(original)
        alternate_manifest["evidence_variant"] = "different-current-artifact"
        write_json(alternate, alternate_manifest)
        trace = load_json(project / TRACE)
        trace["traces"][0]["pass_output_relative_path"] = (
            "test_outputs/alternate_online_pass.json"
        )
        trace["traces"][0]["pass_output_sha256"] = sha256(alternate)
        write_json(project / TRACE, trace)

        trace_result = self.run_trace(project)
        protocol_result = self.run_protocol(project)

        self.assertEqual(1, trace_result.returncode, trace_result.stdout)
        self.assertIn("ONLINE_CHRONOLOGY_UNVERIFIED", trace_result.stdout)
        self.assertEqual(1, protocol_result.returncode)
        self.assertIn("ONLINE_CHRONOLOGY_UNVERIFIED", protocol_result.stdout)

    def test_protocol_and_trace_must_share_exact_executable_test(self) -> None:
        project = self.make_project()
        original_test = project / "checks/check_online_chronology.py"
        alternate_test = project / "checks/alternate_online_chronology.py"
        alternate_test.write_text(
            original_test.read_text(encoding="utf-8") + "\n# alternate artifact\n",
            encoding="utf-8",
        )
        original_output = project / "test_outputs/online_chronology_pass.json"
        alternate_output = project / "test_outputs/alternate_online_pass.json"
        output = load_json(original_output)
        output["executable_test_relative_path"] = "checks/alternate_online_chronology.py"
        output["executable_test_sha256"] = sha256(alternate_test)
        write_json(alternate_output, output)
        trace = load_json(project / TRACE)
        binding = trace["traces"][0]
        binding["executable_test_relative_path"] = "checks/alternate_online_chronology.py"
        binding["executable_test_sha256"] = sha256(alternate_test)
        binding["pass_output_relative_path"] = "test_outputs/alternate_online_pass.json"
        binding["pass_output_sha256"] = sha256(alternate_output)
        write_json(project / TRACE, trace)

        trace_result = self.run_trace(project)
        protocol_result = self.run_protocol(project)

        self.assertEqual(1, trace_result.returncode, trace_result.stdout)
        self.assertIn("ONLINE_CHRONOLOGY_UNVERIFIED", trace_result.stdout)
        self.assertEqual(1, protocol_result.returncode)
        self.assertIn("ONLINE_CHRONOLOGY_UNVERIFIED", protocol_result.stdout)

    def test_protocol_command_must_equal_recorded_manifest_command(self) -> None:
        project = self.make_project()
        protocol = load_json(project / PROTOCOL)
        protocol["chronology_test"]["command"] = "python3 -m checks.different"
        write_json(project / PROTOCOL, protocol)

        completed = self.run_protocol(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("ONLINE_CHRONOLOGY_UNVERIFIED", completed.stdout)

    def test_protocol_and_trace_implementation_symbol_must_match(self) -> None:
        project = self.make_project()
        protocol = load_json(project / PROTOCOL)
        protocol["chronology_test"]["implementation_symbol"] = "evaluate_in_blocks"
        write_json(project / PROTOCOL, protocol)

        completed = self.run_protocol(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("ONLINE_CHRONOLOGY_UNVERIFIED", completed.stdout)

    def test_protocol_exit_codes_reject_booleans_with_explicit_code(self) -> None:
        for value in (False, True):
            with self.subTest(value=value):
                project = self.make_project()
                protocol = load_json(project / PROTOCOL)
                protocol["chronology_test"]["exit_code"] = value
                write_json(project / PROTOCOL, protocol)

                completed = self.run_protocol(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_EXIT_CODE_TYPE", completed.stdout)

    def test_pass_manifest_exit_codes_reject_booleans_in_both_validators(self) -> None:
        for value in (False, True):
            with self.subTest(value=value):
                project = self.make_project()
                output_path = project / "test_outputs/online_chronology_pass.json"
                manifest = load_json(output_path)
                manifest["exit_code"] = value
                write_json(output_path, manifest)
                output_hash = sha256(output_path)
                protocol = load_json(project / PROTOCOL)
                protocol["chronology_test"]["output_sha256"] = output_hash
                write_json(project / PROTOCOL, protocol)
                trace = load_json(project / TRACE)
                trace["traces"][0]["pass_output_sha256"] = output_hash
                write_json(project / TRACE, trace)

                protocol_result = self.run_protocol(project)
                trace_result = self.run_trace(project)

                self.assertEqual(1, protocol_result.returncode)
                self.assertEqual(1, trace_result.returncode)
                self.assertIn("INVALID_EXIT_CODE_TYPE", protocol_result.stdout)
                self.assertIn("INVALID_EXIT_CODE_TYPE", trace_result.stdout)

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

    def test_method_online_protocol_and_complexity_claims_route_as_algorithm(self) -> None:
        for claim_type in ("METHOD", "ONLINE", "PROTOCOL", "COMPLEXITY"):
            with self.subTest(claim_type=claim_type):
                project = self.make_project()
                inventory = load_json(project / "claim_inventory.json")
                inventory["claims"][1]["claim_type"] = claim_type
                write_json(project / "claim_inventory.json", inventory)
                trace = load_json(project / TRACE)
                trace["traces"] = []
                write_json(project / TRACE, trace)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("MISSING_CLAIM_CODE_TRACE", completed.stdout)

    def test_empirical_and_baseline_claims_do_not_route_as_algorithm(self) -> None:
        for claim_type in ("EMPIRICAL", "BASELINE"):
            with self.subTest(claim_type=claim_type):
                project = self.make_project()
                inventory = load_json(project / "claim_inventory.json")
                inventory["claims"][1]["claim_type"] = claim_type
                write_json(project / "claim_inventory.json", inventory)
                trace = load_json(project / TRACE)
                trace["traces"] = []
                write_json(project / TRACE, trace)

                completed = self.run_trace(project)

                self.assertEqual(
                    0, completed.returncode, completed.stdout + completed.stderr
                )

    def test_trace_collector_rejects_nonstring_claim_type(self) -> None:
        project = self.make_project()
        inventory = load_json(project / "claim_inventory.json")
        inventory["claims"][1]["claim_type"] = False
        write_json(project / "claim_inventory.json", inventory)
        trace = load_json(project / TRACE)
        trace["traces"] = []
        write_json(project / TRACE, trace)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("INVALID_CLAIM_TYPE", completed.stdout)

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

    def test_comment_claim_id_cannot_replace_machine_readable_test_targets(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            "# TARGET_CLAIM_IDS: C-ALGORITHM-1\n"
            "from implementation.online_algorithm import evaluate_online\n"
            "evaluate_online\n",
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("INVALID_TEST_TARGET_CONTRACT", completed.stdout)

    def test_test_target_contract_rejects_extra_or_dynamic_claim_ids(self) -> None:
        replacements = (
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1", "C-ORPHAN-1")',
            "TARGET_CLAIM_IDS = build_target_claim_ids()",
        )
        for declaration in replacements:
            with self.subTest(declaration=declaration):
                project = self.make_project()
                test_path = project / "checks/check_online_chronology.py"
                text = test_path.read_text(encoding="utf-8")
                text = text.replace(
                    'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)', declaration
                )
                test_path.write_text(text, encoding="utf-8")
                self.refresh_test_and_output_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_TEST_TARGET_CONTRACT", completed.stdout)

    def test_test_target_contract_requires_one_immutable_tuple(self) -> None:
        replacements = (
            'TARGET_CLAIM_IDS = ["C-ALGORITHM-1"]',
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\nTARGET_CLAIM_IDS = ("C-X",)',
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\nTARGET_CLAIM_IDS: tuple[str, ...] = ("C-X",)',
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\nTARGET_CLAIM_IDS += ("C-X",)',
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\ndel TARGET_CLAIM_IDS',
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\nTARGET_CLAIM_IDS[0] = "C-X"',
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\nTARGET_CLAIM_IDS.append("C-X")',
        )
        for declaration in replacements:
            with self.subTest(declaration=declaration):
                project = self.make_project()
                test_path = project / "checks/check_online_chronology.py"
                text = test_path.read_text(encoding="utf-8").replace(
                    'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)', declaration
                )
                test_path.write_text(text, encoding="utf-8")
                self.refresh_test_and_output_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_TEST_TARGET_CONTRACT", completed.stdout)

    def test_test_target_contract_rejects_every_module_level_binder(self) -> None:
        binders = (
            "import fake as TARGET_CLAIM_IDS",
            "from fake import value as TARGET_CLAIM_IDS",
            "from fake import *",
            "def TARGET_CLAIM_IDS():\n    pass",
            "async def TARGET_CLAIM_IDS():\n    pass",
            "class TARGET_CLAIM_IDS:\n    pass",
            "try:\n    pass\nexcept Exception as TARGET_CLAIM_IDS:\n    pass",
            "with fake() as TARGET_CLAIM_IDS:\n    pass",
            "for TARGET_CLAIM_IDS in []:\n    pass",
            "[value for TARGET_CLAIM_IDS in []]",
            "match value:\n    case TARGET_CLAIM_IDS:\n        pass",
            "(TARGET_CLAIM_IDS := ('C-X',))",
        )
        for binder in binders:
            with self.subTest(binder=binder):
                project = self.make_project()
                test_path = project / "checks/check_online_chronology.py"
                text = test_path.read_text(encoding="utf-8").replace(
                    'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)',
                    'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n' + binder,
                )
                test_path.write_text(text, encoding="utf-8")
                self.refresh_test_and_output_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_TEST_TARGET_CONTRACT", completed.stdout)

    def test_class_global_target_binding_is_a_module_rebind(self) -> None:
        class_bodies = (
            'TARGET_CLAIM_IDS = ("C-X",)',
            "del TARGET_CLAIM_IDS",
            "import fake as TARGET_CLAIM_IDS",
            "def TARGET_CLAIM_IDS():\n        pass",
        )
        for class_body in class_bodies:
            with self.subTest(class_body=class_body):
                project = self.make_project()
                test_path = project / "checks/check_online_chronology.py"
                addition = (
                    "\nclass RebindTarget:\n"
                    "    global TARGET_CLAIM_IDS\n"
                    f"    {class_body}\n"
                )
                test_path.write_text(
                    test_path.read_text(encoding="utf-8") + addition,
                    encoding="utf-8",
                )
                self.refresh_test_and_output_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_TEST_TARGET_CONTRACT", completed.stdout)

    def test_nested_reachable_class_global_target_binding_is_rejected(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            test_path.read_text(encoding="utf-8")
            + "\nif True:\n"
            + "    class RebindTarget:\n"
            + "        global TARGET_CLAIM_IDS\n"
            + '        TARGET_CLAIM_IDS = ("C-X",)\n',
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("INVALID_TEST_TARGET_CONTRACT", completed.stdout)

    def test_arbitrarily_nested_class_global_target_binding_is_rejected(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            test_path.read_text(encoding="utf-8")
            + "\nclass Outer:\n"
            + "    class Middle:\n"
            + "        class Inner:\n"
            + "            global TARGET_CLAIM_IDS\n"
            + '            TARGET_CLAIM_IDS = ("C-X",)\n',
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("INVALID_TEST_TARGET_CONTRACT", completed.stdout)

    def test_dead_arbitrarily_nested_class_global_target_binding_is_ignored(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            test_path.read_text(encoding="utf-8")
            + "\nclass Outer:\n"
            + "    if 0:\n"
            + "        class Middle:\n"
            + "            class Inner:\n"
            + "                global TARGET_CLAIM_IDS\n"
            + '                TARGET_CLAIM_IDS = ("C-X",)\n',
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_statically_dead_class_global_target_binding_is_ignored(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            test_path.read_text(encoding="utf-8")
            + "\nif 0:\n"
            + "    class RebindTarget:\n"
            + "        global TARGET_CLAIM_IDS\n"
            + '        TARGET_CLAIM_IDS = ("C-X",)\n',
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_test_must_reference_bound_implementation_not_merely_claim_id(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
            "def test_placeholder():\n"
            "    return True\n",
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_block_trace_cannot_reuse_online_implementation_test(self) -> None:
        project = self.make_project()
        block_path = project / "implementation/block_algorithm.py"
        block_hash = sha256(block_path)
        protocol = load_json(project / PROTOCOL)
        chronology = protocol["chronology_test"]
        chronology["implementation_relative_path"] = "implementation/block_algorithm.py"
        chronology["implementation_sha256"] = block_hash
        write_json(project / PROTOCOL, protocol)
        trace = load_json(project / TRACE)
        binding = trace["traces"][0]
        binding["implementation_relative_path"] = "implementation/block_algorithm.py"
        binding["implementation_symbol"] = "evaluate_in_blocks"
        binding["implementation_sha256"] = block_hash
        write_json(project / TRACE, trace)
        output_path = project / "test_outputs/online_chronology_pass.json"
        manifest = load_json(output_path)
        manifest["implementation_relative_path"] = "implementation/block_algorithm.py"
        manifest["implementation_sha256"] = block_hash
        write_json(output_path, manifest)
        output_hash = sha256(output_path)
        protocol = load_json(project / PROTOCOL)
        protocol["chronology_test"]["output_sha256"] = output_hash
        write_json(project / PROTOCOL, protocol)
        trace = load_json(project / TRACE)
        trace["traces"][0]["pass_output_sha256"] = output_hash
        write_json(project / TRACE, trace)

        protocol_result = self.run_protocol(project)
        trace_result = self.run_trace(project)

        self.assertEqual(1, protocol_result.returncode)
        self.assertEqual(1, trace_result.returncode)
        self.assertIn("ONLINE_CHRONOLOGY_UNVERIFIED", protocol_result.stdout)
        self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", trace_result.stdout)

    def test_bare_block_reference_cannot_hide_actual_online_call(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            "from implementation.block_algorithm import evaluate_in_blocks\n"
            "from implementation.online_algorithm import evaluate_online\n\n"
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n\n'
            "evaluate_in_blocks\n\n"
            "def call_the_other_implementation():\n"
            "    evaluate_online(None, [], [])\n",
            encoding="utf-8",
        )
        block_path = project / "implementation/block_algorithm.py"
        block_hash = sha256(block_path)
        output_path = project / "test_outputs/online_chronology_pass.json"
        manifest = load_json(output_path)
        manifest["implementation_relative_path"] = "implementation/block_algorithm.py"
        manifest["implementation_sha256"] = block_hash
        write_json(output_path, manifest)
        protocol = load_json(project / PROTOCOL)
        chronology = protocol["chronology_test"]
        chronology["implementation_relative_path"] = "implementation/block_algorithm.py"
        chronology["implementation_sha256"] = block_hash
        write_json(project / PROTOCOL, protocol)
        trace = load_json(project / TRACE)
        binding = trace["traces"][0]
        binding["implementation_relative_path"] = "implementation/block_algorithm.py"
        binding["implementation_symbol"] = "evaluate_in_blocks"
        binding["implementation_sha256"] = block_hash
        write_json(project / TRACE, trace)
        self.refresh_test_and_output_hashes(project)

        protocol_result = self.run_protocol(project)
        trace_result = self.run_trace(project)

        self.assertEqual(1, protocol_result.returncode)
        self.assertEqual(1, trace_result.returncode)
        self.assertIn("ONLINE_CHRONOLOGY_UNVERIFIED", protocol_result.stdout)
        self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", trace_result.stdout)

    def test_bound_implementation_alias_call_is_accepted(self) -> None:
        variants = (
            (
                "from implementation.online_algorithm import evaluate_online as bound\n",
                "bound(None, [], [])",
            ),
            (
                "import implementation.online_algorithm as bound_module\n",
                "bound_module.evaluate_online(None, [], [])",
            ),
            (
                "import implementation.online_algorithm\n",
                "implementation.online_algorithm.evaluate_online(None, [], [])",
            ),
        )
        for import_line, call_line in variants:
            with self.subTest(import_line=import_line):
                project = self.make_project()
                test_path = project / "checks/check_online_chronology.py"
                test_path.write_text(
                    import_line
                    + '\nTARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n\n'
                    + "def prove_binding():\n"
                    + f"    {call_line}\n",
                    encoding="utf-8",
                )
                self.refresh_test_and_output_hashes(project)

                protocol_result = self.run_protocol(project)
                trace_result = self.run_trace(project)

                self.assertEqual(
                    0,
                    protocol_result.returncode,
                    protocol_result.stdout + protocol_result.stderr,
                )
                self.assertEqual(
                    0,
                    trace_result.returncode,
                    trace_result.stdout + trace_result.stderr,
                )

    def test_reachable_bound_call_inside_keyword_argument_is_accepted(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            "from implementation.online_algorithm import evaluate_online\n"
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
            "def prove_binding():\n"
            "    consume(result=evaluate_online(None, [], []))\n",
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_implementation_symbol_must_be_a_top_level_definition(self) -> None:
        project = self.make_project()
        implementation = project / "implementation/online_algorithm.py"
        implementation.write_text(
            '"ghost evaluate_online token"\n# def evaluate_online(): pass\n',
            encoding="utf-8",
        )
        self.refresh_implementation_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("IMPLEMENTATION_SYMBOL_NOT_FOUND", completed.stdout)

    def test_nested_or_dead_import_and_dead_call_do_not_prove_binding(self) -> None:
        programs = (
            (
                "if False:\n"
                "    from implementation.online_algorithm import evaluate_online\n"
                'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
                "evaluate_online(None, [], [])\n"
            ),
            (
                "from implementation.online_algorithm import evaluate_online\n"
                'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
                "if False:\n"
                "    evaluate_online(None, [], [])\n"
            ),
        )
        for program in programs:
            with self.subTest(program=program):
                project = self.make_project()
                (project / "checks/check_online_chronology.py").write_text(
                    program, encoding="utf-8"
                )
                self.refresh_test_and_output_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_statically_dead_or_terminated_calls_do_not_prove_binding(self) -> None:
        bodies = (
            "def proof():\n    if 0:\n        evaluate_online(None, [], [])\n",
            "def proof():\n    if []:\n        evaluate_online(None, [], [])\n",
            "def proof():\n    while 0:\n        evaluate_online(None, [], [])\n",
            "def proof():\n    return\n    evaluate_online(None, [], [])\n",
            "def proof():\n    raise RuntimeError\n    evaluate_online(None, [], [])\n",
            "def proof():\n    for item in [1]:\n        break\n        evaluate_online(None, [], [])\n",
            "def proof():\n    for item in [1]:\n        continue\n        evaluate_online(None, [], [])\n",
        )
        for body in bodies:
            with self.subTest(body=body):
                project = self.make_project()
                test_path = project / "checks/check_online_chronology.py"
                test_path.write_text(
                    "from implementation.online_algorithm import evaluate_online\n"
                    'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
                    + body,
                    encoding="utf-8",
                )
                self.refresh_test_and_output_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_infinite_while_with_terminal_body_makes_following_call_unreachable(self) -> None:
        for terminal in ("return", "raise RuntimeError"):
            with self.subTest(terminal=terminal):
                project = self.make_project()
                test_path = project / "checks/check_online_chronology.py"
                test_path.write_text(
                    "from implementation.online_algorithm import evaluate_online\n"
                    'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
                    "def proof():\n"
                    "    while True:\n"
                    f"        {terminal}\n"
                    "    evaluate_online(None, [], [])\n",
                    encoding="utf-8",
                )
                self.refresh_test_and_output_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_for_else_terminal_paths_make_following_call_unreachable(self) -> None:
        loop_headers = ("for item in values:", "async for item in values:")
        for loop_header in loop_headers:
            with self.subTest(loop_header=loop_header):
                project = self.make_project()
                test_path = project / "checks/check_online_chronology.py"
                function_header = (
                    "async def proof():" if loop_header.startswith("async") else "def proof():"
                )
                test_path.write_text(
                    "from implementation.online_algorithm import evaluate_online\n"
                    'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
                    f"{function_header}\n"
                    f"    {loop_header}\n"
                    "        return\n"
                    "    else:\n"
                    "        return\n"
                    "    evaluate_online(None, [], [])\n",
                    encoding="utf-8",
                )
                self.refresh_test_and_output_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_for_else_break_keeps_following_call_reachable(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            "from implementation.online_algorithm import evaluate_online\n"
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
            "def proof():\n"
            "    for item in values:\n"
            "        break\n"
            "    else:\n"
            "        return\n"
            "    evaluate_online(None, [], [])\n",
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_exhaustive_match_terminal_case_makes_following_call_unreachable(self) -> None:
        patterns = ("_", "captured")
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                project = self.make_project()
                test_path = project / "checks/check_online_chronology.py"
                test_path.write_text(
                    "from implementation.online_algorithm import evaluate_online\n"
                    'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
                    "def proof():\n"
                    "    match value:\n"
                    f"        case {pattern}:\n"
                    "            return\n"
                    "    evaluate_online(None, [], [])\n",
                    encoding="utf-8",
                )
                self.refresh_test_and_output_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_nonexhaustive_or_guarded_match_keeps_following_call_reachable(self) -> None:
        cases = ("case 1:\n            return", "case _ if condition:\n            return")
        for case in cases:
            with self.subTest(case=case):
                project = self.make_project()
                test_path = project / "checks/check_online_chronology.py"
                test_path.write_text(
                    "from implementation.online_algorithm import evaluate_online\n"
                    'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
                    "def proof():\n"
                    "    match value:\n"
                    f"        {case}\n"
                    "    evaluate_online(None, [], [])\n",
                    encoding="utf-8",
                )
                self.refresh_test_and_output_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_break_from_infinite_while_keeps_following_call_reachable(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            "from implementation.online_algorithm import evaluate_online\n"
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
            "def proof():\n"
            "    while True:\n"
            "        break\n"
            "    evaluate_online(None, [], [])\n",
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_try_finally_preserves_or_overrides_terminal_control_flow(self) -> None:
        programs = (
            "try:\n        return\n    finally:\n        pass",
            "try:\n        raise RuntimeError\n    finally:\n        pass",
            "try:\n        pass\n    finally:\n        return",
            "try:\n        pass\n    finally:\n        raise RuntimeError",
        )
        for program in programs:
            with self.subTest(program=program):
                project = self.make_project()
                test_path = project / "checks/check_online_chronology.py"
                test_path.write_text(
                    "from implementation.online_algorithm import evaluate_online\n"
                    'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
                    "def proof():\n"
                    f"    {program}\n"
                    "    evaluate_online(None, [], [])\n",
                    encoding="utf-8",
                )
                self.refresh_test_and_output_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_try_except_fallthrough_keeps_following_call_reachable(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            "from implementation.online_algorithm import evaluate_online\n"
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
            "def proof():\n"
            "    try:\n"
            "        return\n"
            "    except Exception:\n"
            "        pass\n"
            "    evaluate_online(None, [], [])\n",
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_try_else_after_terminal_body_does_not_prove_binding(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            "from implementation.online_algorithm import evaluate_online\n"
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
            "def proof():\n"
            "    try:\n"
            "        return\n"
            "    except Exception:\n"
            "        raise\n"
            "    else:\n"
            "        evaluate_online(None, [], [])\n",
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_shadowed_import_binding_cannot_prove_target_call(self) -> None:
        bodies = (
            "def proof(evaluate_online):\n    evaluate_online(None, [], [])\n",
            "proof = lambda evaluate_online: evaluate_online(None, [], [])\n",
            "def proof():\n    evaluate_online = fake\n    evaluate_online(None, [], [])\n",
            "def proof():\n    evaluate_online: object = fake\n    evaluate_online(None, [], [])\n",
            "def proof():\n    evaluate_online += fake\n    evaluate_online(None, [], [])\n",
            "def proof():\n    (evaluate_online := fake)\n    evaluate_online(None, [], [])\n",
            "def proof():\n    del evaluate_online\n    evaluate_online(None, [], [])\n",
            "def proof():\n    def evaluate_online(*args): pass\n    evaluate_online(None, [], [])\n",
            "def proof():\n    class evaluate_online: pass\n    evaluate_online(None, [], [])\n",
            "def proof():\n    import fake as evaluate_online\n    evaluate_online(None, [], [])\n",
        )
        for body in bodies:
            with self.subTest(body=body):
                project = self.make_project()
                program = (
                    "from implementation.online_algorithm import evaluate_online\n"
                    'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
                    + body
                )
                (project / "checks/check_online_chronology.py").write_text(
                    program, encoding="utf-8"
                )
                self.refresh_test_and_output_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_reassigned_module_alias_cannot_prove_target_call(self) -> None:
        programs = (
            "import implementation.online_algorithm as bound\n"
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
            "bound = fake\n"
            "bound.evaluate_online(None, [], [])\n",
            "import implementation.online_algorithm as bound, fake as bound\n"
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
            "bound.evaluate_online(None, [], [])\n",
        )
        for program in programs:
            with self.subTest(program=program):
                project = self.make_project()
                test_path = project / "checks/check_online_chronology.py"
                test_path.write_text(program, encoding="utf-8")
                self.refresh_test_and_output_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_module_alias_attribute_mutation_invalidates_bound_call(self) -> None:
        mutations = (
            "bound.evaluate_online = fake",
            "bound.evaluate_online: object = fake",
            "bound.evaluate_online += fake",
            "del bound.evaluate_online",
            'setattr(bound, "evaluate_online", fake)',
            'delattr(bound, "evaluate_online")',
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                project = self.make_project()
                test_path = project / "checks/check_online_chronology.py"
                test_path.write_text(
                    "import implementation.online_algorithm as bound\n"
                    'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
                    + mutation
                    + "\nbound.evaluate_online(None, [], [])\n",
                    encoding="utf-8",
                )
                self.refresh_test_and_output_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_statically_dead_module_alias_rebinding_preserves_bound_call(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            "import implementation.online_algorithm as bound\n"
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
            "if 0:\n"
            "    bound = fake\n"
            "bound.evaluate_online(None, [], [])\n",
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_class_global_module_alias_rebinding_invalidates_bound_call(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            "import implementation.online_algorithm as bound\n"
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
            "class RebindAlias:\n"
            "    global bound\n"
            "    bound = fake\n"
            "bound.evaluate_online(None, [], [])\n",
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_nested_class_global_module_alias_rebinding_invalidates_bound_call(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            "import implementation.online_algorithm as bound\n"
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
            "class Outer:\n"
            "    class Middle:\n"
            "        class RebindAlias:\n"
            "            global bound\n"
            "            bound = fake\n"
            "bound.evaluate_online(None, [], [])\n",
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_enclosing_scope_shadow_cannot_prove_nested_call(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            "from implementation.online_algorithm import evaluate_online\n"
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
            "def outer():\n"
            "    evaluate_online = fake\n"
            "    def inner():\n"
            "        evaluate_online(None, [], [])\n",
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_fake_module_import_cannot_prove_binding(self) -> None:
        project = self.make_project()
        test_path = project / "checks/check_online_chronology.py"
        test_path.write_text(
            "import fake.online_algorithm as implementation\n"
            'TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)\n'
            "implementation.evaluate_online(None, [], [])\n",
            encoding="utf-8",
        )
        self.refresh_test_and_output_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("TRACE_TEST_IMPLEMENTATION_MISMATCH", completed.stdout)

    def test_async_function_and_class_are_valid_top_level_implementation_symbols(self) -> None:
        implementations = (
            "async def evaluate_online(*args):\n    return []\n",
            "class evaluate_online:\n    pass\n",
        )
        for source in implementations:
            with self.subTest(source=source):
                project = self.make_project()
                (project / "implementation/online_algorithm.py").write_text(
                    source, encoding="utf-8"
                )
                self.refresh_implementation_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(
                    0, completed.returncode, completed.stdout + completed.stderr
                )

    def test_implementation_symbol_must_remain_the_final_module_binding(self) -> None:
        suffixes = (
            "evaluate_online = fake\n",
            "evaluate_online: object = fake\n",
            "evaluate_online += fake\n",
            "(evaluate_online := fake)\n",
            "del evaluate_online\n",
            "import fake as evaluate_online\n",
            "from fake import *\n",
            "if condition:\n    evaluate_online = fake\n",
            "for evaluate_online in values:\n    pass\n",
            "with context() as evaluate_online:\n    pass\n",
            "try:\n    evaluate_online = fake\nexcept Exception:\n    pass\n",
        )
        for suffix in suffixes:
            with self.subTest(suffix=suffix):
                project = self.make_project()
                implementation = project / "implementation/online_algorithm.py"
                implementation.write_text(
                    "def evaluate_online(*args):\n    return []\n" + suffix,
                    encoding="utf-8",
                )
                self.refresh_implementation_hashes(project)

                completed = self.run_trace(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_IMPLEMENTATION_SYMBOL", completed.stdout)

    def test_final_top_level_definition_can_replace_an_earlier_binding(self) -> None:
        project = self.make_project()
        implementation = project / "implementation/online_algorithm.py"
        implementation.write_text(
            "evaluate_online = fake\n"
            "def evaluate_online(*args):\n"
            "    return []\n",
            encoding="utf-8",
        )
        self.refresh_implementation_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_statically_dead_override_preserves_final_implementation_binding(self) -> None:
        project = self.make_project()
        implementation = project / "implementation/online_algorithm.py"
        implementation.write_text(
            "def evaluate_online(*args):\n"
            "    return []\n"
            "if []:\n"
            "    evaluate_online = fake\n",
            encoding="utf-8",
        )
        self.refresh_implementation_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_class_global_implementation_rebinding_invalidates_final_symbol(self) -> None:
        project = self.make_project()
        implementation = project / "implementation/online_algorithm.py"
        implementation.write_text(
            "def evaluate_online(*args):\n"
            "    return []\n"
            "class RebindImplementation:\n"
            "    global evaluate_online\n"
            "    evaluate_online = fake\n",
            encoding="utf-8",
        )
        self.refresh_implementation_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("INVALID_IMPLEMENTATION_SYMBOL", completed.stdout)

    def test_nested_class_global_implementation_rebinding_invalidates_final_symbol(self) -> None:
        project = self.make_project()
        implementation = project / "implementation/online_algorithm.py"
        implementation.write_text(
            "def evaluate_online(*args):\n"
            "    return []\n"
            "class Outer:\n"
            "    class Middle:\n"
            "        class RebindImplementation:\n"
            "            global evaluate_online\n"
            "            evaluate_online = fake\n",
            encoding="utf-8",
        )
        self.refresh_implementation_hashes(project)

        completed = self.run_trace(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("INVALID_IMPLEMENTATION_SYMBOL", completed.stdout)

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

    def test_pass_manifest_requires_exact_v2_schema_in_both_validators(self) -> None:
        schema_values: tuple[tuple[str, Any], ...] = (
            ("missing", None),
            ("old", "1.0"),
            ("number", 2.0),
        )
        for label, value in schema_values:
            with self.subTest(label=label, value=value):
                project = self.make_project()
                output_path = project / "test_outputs/online_chronology_pass.json"
                manifest = load_json(output_path)
                if label == "missing":
                    del manifest["schema_version"]
                else:
                    manifest["schema_version"] = value
                write_json(output_path, manifest)
                output_hash = sha256(output_path)
                protocol = load_json(project / PROTOCOL)
                protocol["chronology_test"]["output_sha256"] = output_hash
                write_json(project / PROTOCOL, protocol)
                trace = load_json(project / TRACE)
                trace["traces"][0]["pass_output_sha256"] = output_hash
                write_json(project / TRACE, trace)

                protocol_result = self.run_protocol(project)
                trace_result = self.run_trace(project)

                self.assertEqual(1, protocol_result.returncode)
                self.assertEqual(1, trace_result.returncode)
                self.assertIn("INVALID_EVIDENCE_SCHEMA", protocol_result.stdout)
                self.assertIn("INVALID_EVIDENCE_SCHEMA", trace_result.stdout)

    def test_manifest_targets_must_equal_trace_reference_set_without_orphans(self) -> None:
        project = self.make_project()
        output_path = project / "test_outputs/online_chronology_pass.json"
        manifest = load_json(output_path)
        manifest["target_claim_ids"] = ["C-ALGORITHM-1", "C-ORPHAN-1"]
        write_json(output_path, manifest)
        output_hash = sha256(output_path)
        protocol = load_json(project / PROTOCOL)
        protocol["chronology_test"]["output_sha256"] = output_hash
        write_json(project / PROTOCOL, protocol)
        trace = load_json(project / TRACE)
        trace["traces"][0]["pass_output_sha256"] = output_hash
        write_json(project / TRACE, trace)

        protocol_result = self.run_protocol(project)
        trace_result = self.run_trace(project)

        self.assertEqual(1, protocol_result.returncode)
        self.assertEqual(1, trace_result.returncode)
        self.assertIn("ONLINE_CHRONOLOGY_UNVERIFIED", protocol_result.stdout)
        self.assertIn("TRACE_TARGET_SET_MISMATCH", trace_result.stdout)

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

    def test_validate_all_checks_lone_early_baseline_without_missing_protocol_noise(self) -> None:
        project = self.make_project("ALGORITHM")
        (project / PROTOCOL).unlink()
        (project / TRACE).unlink()
        baseline_path = project / BASELINES
        baseline_path.write_text(
            '{"schema_version":"2.0","schema_version":"2.0","comparators":[]}\n',
            encoding="utf-8",
        )

        completed = run_all_validator(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("INVALID_BASELINE_BUDGET_JSON", completed.stdout)
        self.assertNotIn("PROTOCOL_CONTRACT_REQUIRED", completed.stdout)
        self.assertNotIn("CLAIM_CODE_TRACE_REQUIRED", completed.stdout)

    def test_fixture_recorded_chronology_command_runs_and_matches_manifest(self) -> None:
        project = self.make_project()
        protocol = load_json(project / PROTOCOL)
        command = protocol["chronology_test"]["command"]

        completed = subprocess.run(
            shlex.split(command),
            cwd=project,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("", completed.stderr)
        generated_manifest = json.loads(completed.stdout)
        recorded_manifest = load_json(
            project / protocol["chronology_test"]["output_file"]
        )
        self.assertEqual(recorded_manifest, generated_manifest)
        self.assertEqual(command, generated_manifest["command"])


if __name__ == "__main__":
    unittest.main()
