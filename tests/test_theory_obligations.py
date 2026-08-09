from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from tests.helpers import (
    REPOSITORY_ROOT,
    load_json,
    make_valid_project,
    run_all_validator,
    run_script,
    write_json,
)


REGISTRY_NAME = "theory_obligation_registry.json"
CORE_WITNESS_KINDS = (
    "MINIMAL_POSITIVE",
    "NONZERO_NUISANCE",
    "BOUNDARY_OR_LIMIT",
    "PREMISE_REMOVAL",
)


def load_obligations(project: Path) -> dict[str, Any]:
    return load_json(project / REGISTRY_NAME)


def write_obligations(project: Path, payload: dict[str, Any]) -> None:
    write_json(project / REGISTRY_NAME, payload)


def first_obligation(payload: dict[str, Any]) -> dict[str, Any]:
    return payload["obligations"][0]


def find_witness(obligation: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(witness for witness in obligation["witnesses"] if witness["kind"] == kind)


class TheoryObligationTests(unittest.TestCase):
    def make_project(
        self, *, claim_profile: str = "THEORY", validity_level: str = "V3"
    ) -> Path:
        temporary_directory, project = make_valid_project(
            claim_profile=claim_profile, validity_level=validity_level
        )
        self.addCleanup(temporary_directory.cleanup)
        return project

    def run_theory(
        self, project: Path, *extra_args: str
    ) -> subprocess.CompletedProcess[str]:
        return run_script(
            "validate_theory_obligations.py", project, extra_args=extra_args
        )

    def test_minimal_theory_fixture_is_ready(self) -> None:
        project = self.make_project()

        completed = self.run_theory(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("theory_obligations_status=READY", completed.stdout)

    def test_each_theorem_lemma_and_corollary_requires_exactly_one_obligation(self) -> None:
        project = self.make_project()
        inventory = load_json(project / "claim_inventory.json")
        template = inventory["claims"][0]
        for index, claim_type in enumerate(("LEMMA", "COROLLARY"), start=2):
            inventory["claims"].append(
                {
                    **template,
                    "claim_id": f"C-{claim_type}-{index}",
                    "claim_type": claim_type,
                    "statement": f"Auxiliary statement {index}.",
                    "occurrence_ids": [],
                }
            )
        write_json(project / "claim_inventory.json", inventory)

        completed = self.run_theory(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual(2, completed.stdout.count("MISSING_THEORY_OBLIGATION"))

        obligations = load_obligations(project)
        obligations["obligations"].append(dict(first_obligation(obligations)))
        write_obligations(project, obligations)
        completed = self.run_theory(project)
        self.assertIn("DUPLICATE_THEORY_OBLIGATION", completed.stdout)

    def test_orphan_obligation_is_rejected(self) -> None:
        project = self.make_project()
        obligations = load_obligations(project)
        orphan = dict(first_obligation(obligations))
        orphan["claim_id"] = "C-NOT-IN-INVENTORY"
        obligations["obligations"].append(orphan)
        write_obligations(project, obligations)

        completed = self.run_theory(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("ORPHAN_THEORY_OBLIGATION", completed.stdout)
        self.assertIn("THEOREM_STATEMENT_STALE", completed.stdout)

    def test_required_obligation_fields_are_enforced(self) -> None:
        cases = (
            ("claim_id", "MISSING_OBLIGATION_CLAIM_ID"),
            ("exact_statement", "MISSING_EXACT_STATEMENT"),
            ("exact_statement_sha256", "MISSING_EXACT_STATEMENT_SHA256"),
            ("premises", "MISSING_PREMISES"),
            ("quantifiers", "MISSING_QUANTIFIERS"),
            ("proof_locator", "MISSING_PROOF_LOCATOR"),
            ("validation_epoch", "MISSING_OBLIGATION_VALIDATION_EPOCH"),
        )
        for field, code in cases:
            with self.subTest(field=field):
                project = self.make_project()
                obligations = load_obligations(project)
                del first_obligation(obligations)[field]
                write_obligations(project, obligations)

                completed = self.run_theory(project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn(code, completed.stdout)

    def test_statement_identity_and_epoch_mismatches_are_stale(self) -> None:
        mutations = (
            ("claim_id", "C-STALE"),
            ("exact_statement", "A weakened nearby statement."),
            ("exact_statement_sha256", "f" * 64),
            ("validation_epoch", 2),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                project = self.make_project()
                obligations = load_obligations(project)
                first_obligation(obligations)[field] = value
                write_obligations(project, obligations)

                completed = self.run_theory(project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("THEOREM_STATEMENT_STALE", completed.stdout)

    def test_statement_hash_is_computed_from_exact_inventory_text(self) -> None:
        project = self.make_project()
        inventory = load_json(project / "claim_inventory.json")
        inventory["claims"][0]["statement"] += " "
        write_json(project / "claim_inventory.json", inventory)

        completed = self.run_theory(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("THEOREM_STATEMENT_STALE", completed.stdout)

    def test_all_core_witness_kinds_are_required(self) -> None:
        for kind in CORE_WITNESS_KINDS:
            with self.subTest(kind=kind):
                project = self.make_project()
                obligations = load_obligations(project)
                obligation = first_obligation(obligations)
                obligation["witnesses"] = [
                    witness for witness in obligation["witnesses"] if witness["kind"] != kind
                ]
                write_obligations(project, obligations)

                completed = self.run_theory(project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn(f"MISSING_WITNESS_{kind}", completed.stdout)

    def test_duplicate_and_unknown_witness_kinds_are_rejected(self) -> None:
        project = self.make_project()
        obligations = load_obligations(project)
        obligation = first_obligation(obligations)
        obligation["witnesses"].append(dict(obligation["witnesses"][0]))
        obligation["witnesses"][1]["kind"] = "NOT_A_WITNESS"
        write_obligations(project, obligations)

        completed = self.run_theory(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("DUPLICATE_WITNESS_KIND", completed.stdout)
        self.assertIn("INVALID_WITNESS_KIND", completed.stdout)

    def test_premise_removal_must_be_an_observed_failure(self) -> None:
        cases = (
            ("expected", "PASS"),
            ("observed", "PASS"),
            ("exit_code", 0),
        )
        for field, value in cases:
            with self.subTest(field=field):
                project = self.make_project()
                obligations = load_obligations(project)
                witness = find_witness(first_obligation(obligations), "PREMISE_REMOVAL")
                witness[field] = value
                write_obligations(project, obligations)

                completed = self.run_theory(project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("EXPECTED_FAILURE_DID_NOT_FAIL", completed.stdout)

    def test_positive_and_boundary_witnesses_must_pass_the_contract(self) -> None:
        for kind in ("MINIMAL_POSITIVE", "NONZERO_NUISANCE", "BOUNDARY_OR_LIMIT"):
            for field, value in (("expected", "FAIL"), ("observed", "FAIL"), ("exit_code", 2)):
                with self.subTest(kind=kind, field=field):
                    project = self.make_project()
                    obligations = load_obligations(project)
                    find_witness(first_obligation(obligations), kind)[field] = value
                    write_obligations(project, obligations)

                    completed = self.run_theory(project)

                    self.assertEqual(
                        1, completed.returncode, completed.stdout + completed.stderr
                    )
                    self.assertIn("WITNESS_CONTRACT_MISMATCH", completed.stdout)

    def test_each_witness_requires_command_exit_code_output_and_hash(self) -> None:
        cases = (
            ("kind", "MISSING_WITNESS_KIND"),
            ("expected", "MISSING_WITNESS_EXPECTED"),
            ("observed", "MISSING_WITNESS_OBSERVED"),
            ("command", "MISSING_WITNESS_COMMAND"),
            ("exit_code", "MISSING_WITNESS_EXIT_CODE"),
            ("output_file", "MISSING_WITNESS_OUTPUT_FILE"),
            ("output_sha256", "MISSING_WITNESS_OUTPUT_SHA256"),
        )
        for field, code in cases:
            with self.subTest(field=field):
                project = self.make_project()
                obligations = load_obligations(project)
                del first_obligation(obligations)["witnesses"][0][field]
                write_obligations(project, obligations)

                completed = self.run_theory(project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn(code, completed.stdout)

    def test_witness_output_hash_is_recomputed_from_current_bytes(self) -> None:
        project = self.make_project()
        output = project / "theory_witnesses" / "minimal_positive.txt"
        output.write_text("tampered\n", encoding="utf-8")

        completed = self.run_theory(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("WITNESS_OUTPUT_HASH_MISMATCH", completed.stdout)

    def test_witness_field_types_are_strict_and_boolean_is_not_an_integer(self) -> None:
        mutations = (
            ("validation_epoch", True, "INVALID_OBLIGATION_FIELD"),
            ("premises", "x is real", "INVALID_OBLIGATION_FIELD"),
            ("quantifiers", [1], "INVALID_OBLIGATION_FIELD"),
        )
        for field, value, code in mutations:
            with self.subTest(field=field):
                project = self.make_project()
                obligations = load_obligations(project)
                first_obligation(obligations)[field] = value
                write_obligations(project, obligations)
                completed = self.run_theory(project)
                self.assertEqual(1, completed.returncode)
                self.assertIn(code, completed.stdout)

        project = self.make_project()
        obligations = load_obligations(project)
        first_obligation(obligations)["witnesses"][0]["exit_code"] = True
        write_obligations(project, obligations)
        completed = self.run_theory(project)
        self.assertEqual(1, completed.returncode)
        self.assertIn("INVALID_WITNESS_FIELD", completed.stdout)

    def test_random_property_requires_a_witness_or_explicit_audited_na(self) -> None:
        project = self.make_project()
        obligations = load_obligations(project)
        obligation = first_obligation(obligations)
        obligation["witnesses"] = [
            witness for witness in obligation["witnesses"] if witness["kind"] != "RANDOM_PROPERTY"
        ]
        write_obligations(project, obligations)

        completed = self.run_theory(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("MISSING_WITNESS_RANDOM_PROPERTY", completed.stdout)

        obligation["random_property"] = {
            "status": "NOT_APPLICABLE",
            "mathematical_reason": "The finite domain is exhausted symbolically.",
            "independent_audit_acceptance": {
                "accepted": True,
                "reviewer_agent_id": "agent-b",
            },
        }
        write_obligations(project, obligations)
        completed = self.run_theory(project)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_random_property_na_requires_math_reason_and_matching_reviewer_acceptance(self) -> None:
        cases = (
            ("blank_reason", "", True, "agent-b"),
            ("not_accepted", "Finite exhaustive proof.", False, "agent-b"),
            ("wrong_reviewer", "Finite exhaustive proof.", True, "agent-a"),
            ("boolean_type", "Finite exhaustive proof.", 1, "agent-b"),
        )
        for label, reason, accepted, reviewer in cases:
            with self.subTest(label=label):
                project = self.make_project()
                obligations = load_obligations(project)
                obligation = first_obligation(obligations)
                obligation["witnesses"] = [
                    witness
                    for witness in obligation["witnesses"]
                    if witness["kind"] != "RANDOM_PROPERTY"
                ]
                obligation["random_property"] = {
                    "status": "NOT_APPLICABLE",
                    "mathematical_reason": reason,
                    "independent_audit_acceptance": {
                        "accepted": accepted,
                        "reviewer_agent_id": reviewer,
                    },
                }
                write_obligations(project, obligations)

                completed = self.run_theory(project)

                self.assertEqual(1, completed.returncode)
                expected_code = (
                    "RANDOM_PROPERTY_NA_REASON_REQUIRED"
                    if label == "blank_reason"
                    else "RANDOM_PROPERTY_NA_NOT_AUDIT_ACCEPTED"
                )
                self.assertIn(expected_code, completed.stdout)

    def test_random_property_na_requires_canonical_nonempty_unique_audit_authors(self) -> None:
        malformed_authors = (
            ("missing", None),
            ("null", None),
            ("empty", []),
            ("not_list", "agent-a"),
            ("blank", [""]),
            ("whitespace", [" agent-a"]),
            ("duplicate", ["agent-a", "agent-a"]),
            ("non_string", ["agent-a", {}]),
        )
        for label, authors in malformed_authors:
            with self.subTest(label=label):
                project = self.make_project()
                state = load_json(project / "workflow_state.json")
                if label == "missing":
                    del state["independent_audit"]["author_agent_ids"]
                else:
                    state["independent_audit"]["author_agent_ids"] = authors
                write_json(project / "workflow_state.json", state)
                obligations = load_obligations(project)
                obligation = first_obligation(obligations)
                obligation["witnesses"] = [
                    witness
                    for witness in obligation["witnesses"]
                    if witness["kind"] != "RANDOM_PROPERTY"
                ]
                obligation["random_property"] = {
                    "status": "NOT_APPLICABLE",
                    "mathematical_reason": "Finite exhaustive proof.",
                    "independent_audit_acceptance": {
                        "accepted": True,
                        "reviewer_agent_id": "agent-b",
                    },
                }
                write_obligations(project, obligations)

                completed = self.run_theory(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_RANDOM_PROPERTY_AUDIT_AUTHORS", completed.stdout)
                self.assertNotIn("VALIDATOR_ERROR", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_random_property_na_requires_canonical_independent_reviewer(self) -> None:
        reviewer_cases = (
            ("missing", None, "agent-b"),
            ("blank", "", ""),
            ("whitespace", " agent-b", " agent-b"),
            ("non_string", {}, {}),
            ("self_review", "agent-a", "agent-a"),
            ("acceptance_mismatch", "agent-b", "agent-c"),
        )
        for label, state_reviewer, acceptance_reviewer in reviewer_cases:
            with self.subTest(label=label):
                project = self.make_project()
                state = load_json(project / "workflow_state.json")
                if label == "missing":
                    del state["independent_audit"]["reviewer_agent_id"]
                else:
                    state["independent_audit"]["reviewer_agent_id"] = state_reviewer
                write_json(project / "workflow_state.json", state)
                obligations = load_obligations(project)
                obligation = first_obligation(obligations)
                obligation["witnesses"] = [
                    witness
                    for witness in obligation["witnesses"]
                    if witness["kind"] != "RANDOM_PROPERTY"
                ]
                obligation["random_property"] = {
                    "status": "NOT_APPLICABLE",
                    "mathematical_reason": "Finite exhaustive proof.",
                    "independent_audit_acceptance": {
                        "accepted": True,
                        "reviewer_agent_id": acceptance_reviewer,
                    },
                }
                write_obligations(project, obligations)

                completed = self.run_theory(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_RANDOM_PROPERTY_AUDIT_REVIEWER", completed.stdout)
                self.assertNotIn("VALIDATOR_ERROR", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_unhashable_theory_enum_values_are_field_errors(self) -> None:
        for malformed in ([], {}):
            with self.subTest(field="claim_type", malformed=malformed):
                project = self.make_project()
                inventory = load_json(project / "claim_inventory.json")
                inventory["claims"][0]["claim_type"] = malformed
                write_json(project / "claim_inventory.json", inventory)
                completed = self.run_theory(project)
                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_CLAIM_INVENTORY", completed.stdout)
                self.assertIn("claim_type:expected_nonempty_string", completed.stdout)
                self.assertNotIn("VALIDATOR_ERROR", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

            for field in ("kind", "expected", "observed"):
                with self.subTest(field=field, malformed=malformed):
                    project = self.make_project()
                    obligations = load_obligations(project)
                    first_obligation(obligations)["witnesses"][0][field] = malformed
                    write_obligations(project, obligations)
                    completed = self.run_theory(project)
                    self.assertEqual(1, completed.returncode)
                    expected_code = (
                        "INVALID_WITNESS_KIND"
                        if field == "kind"
                        else "INVALID_WITNESS_FIELD"
                    )
                    self.assertIn(expected_code, completed.stdout)
                    self.assertNotIn("VALIDATOR_ERROR", completed.stdout)
                    self.assertNotIn("Traceback", completed.stderr)

            with self.subTest(field="random_property.status", malformed=malformed):
                project = self.make_project()
                obligations = load_obligations(project)
                obligation = first_obligation(obligations)
                obligation["witnesses"] = [
                    witness
                    for witness in obligation["witnesses"]
                    if witness["kind"] != "RANDOM_PROPERTY"
                ]
                obligation["random_property"] = {
                    "status": malformed,
                    "mathematical_reason": "Finite exhaustive proof.",
                    "independent_audit_acceptance": {
                        "accepted": True,
                        "reviewer_agent_id": "agent-b",
                    },
                }
                write_obligations(project, obligations)
                completed = self.run_theory(project)
                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_RANDOM_PROPERTY_NA", completed.stdout)
                self.assertNotIn("VALIDATOR_ERROR", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

            with self.subTest(field="claim_profile", malformed=malformed):
                project = self.make_project()
                state = load_json(project / "workflow_state.json")
                state["claim_profile"] = malformed
                write_json(project / "workflow_state.json", state)
                completed = self.run_theory(project)
                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_CLAIM_PROFILE", completed.stdout)
                self.assertNotIn("VALIDATOR_ERROR", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_validate_all_aggregates_unhashable_claim_profile_schema_issue(self) -> None:
        for malformed in ([], {}):
            with self.subTest(malformed=malformed):
                project = self.make_project()
                state = load_json(project / "workflow_state.json")
                state["claim_profile"] = malformed
                write_json(project / "workflow_state.json", state)

                completed = run_all_validator(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("INVALID_CLAIM_PROFILE", completed.stdout)
                self.assertIn("validation_suite_status=INVALID", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_output_paths_must_be_canonical_relative_regular_files(self) -> None:
        outside = TemporaryDirectory(prefix="outside-theory-output-")
        self.addCleanup(outside.cleanup)
        outside_path = Path(outside.name) / "secret.txt"
        outside_path.write_text("secret\n", encoding="utf-8")
        cases = (
            ("absolute", str(outside_path), "UNSAFE_WITNESS_OUTPUT"),
            ("traversal", "../secret.txt", "UNSAFE_WITNESS_OUTPUT"),
            ("backslash", "theory_witnesses\\minimal_positive.txt", "UNSAFE_WITNESS_OUTPUT"),
            ("dot", "theory_witnesses/./minimal_positive.txt", "UNSAFE_WITNESS_OUTPUT"),
        )
        for label, path, code in cases:
            with self.subTest(label=label):
                project = self.make_project()
                obligations = load_obligations(project)
                first_obligation(obligations)["witnesses"][0]["output_file"] = path
                write_obligations(project, obligations)
                completed = self.run_theory(project)
                self.assertEqual(1, completed.returncode)
                self.assertIn(code, completed.stdout)
                self.assertNotIn("secret", completed.stdout)

    def test_symlink_output_and_symlink_parent_are_rejected(self) -> None:
        project = self.make_project()
        outside = project.parent / f"{project.name}-outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        linked = project / "theory_witnesses" / "linked.txt"
        linked.symlink_to(outside)
        obligations = load_obligations(project)
        first_obligation(obligations)["witnesses"][0]["output_file"] = "theory_witnesses/linked.txt"
        write_obligations(project, obligations)
        completed = self.run_theory(project)
        self.assertEqual(1, completed.returncode)
        self.assertIn("UNSAFE_WITNESS_OUTPUT", completed.stdout)

        linked.unlink()
        real_dir = project / "alternate_outputs"
        real_dir.mkdir()
        (real_dir / "result.txt").write_text("outside parent\n", encoding="utf-8")
        (project / "linked_outputs").symlink_to(real_dir, target_is_directory=True)
        obligations = load_obligations(project)
        first_obligation(obligations)["witnesses"][0]["output_file"] = "linked_outputs/result.txt"
        write_obligations(project, obligations)
        completed = self.run_theory(project)
        self.assertEqual(1, completed.returncode)
        self.assertIn("UNSAFE_WITNESS_OUTPUT", completed.stdout)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unsupported")
    def test_fifo_output_is_rejected_without_blocking(self) -> None:
        project = self.make_project()
        fifo = project / "theory_witnesses" / "stream.txt"
        os.mkfifo(fifo)
        obligations = load_obligations(project)
        first_obligation(obligations)["witnesses"][0]["output_file"] = "theory_witnesses/stream.txt"
        write_obligations(project, obligations)

        completed = self.run_theory(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("UNSAFE_WITNESS_OUTPUT", completed.stdout)

    def test_registry_inventory_state_and_root_cli_paths_are_hardened(self) -> None:
        project = self.make_project()
        with TemporaryDirectory(prefix="outside-theory-cli-") as outside_directory:
            outside = Path(outside_directory)
            for option, source in (
                ("--state", project / "workflow_state.json"),
                ("--inventory", project / "claim_inventory.json"),
                ("--registry", project / REGISTRY_NAME),
            ):
                copied = outside / source.name
                copied.write_bytes(source.read_bytes())
                completed = self.run_theory(project, option, str(copied))
                self.assertEqual(1, completed.returncode)
                self.assertIn("VALIDATOR_ERROR", completed.stdout)

        alias = project.parent / f"{project.name}-alias"
        alias.symlink_to(project, target_is_directory=True)
        self.addCleanup(lambda: alias.unlink(missing_ok=True))
        completed = subprocess.run(
            [
                sys.executable,
                str(REPOSITORY_ROOT / "scripts" / "validate_theory_obligations.py"),
                "--root",
                str(alias),
                "--state",
                str(alias / "workflow_state.json"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(1, completed.returncode)
        self.assertIn("VALIDATOR_ERROR", completed.stdout)

    def test_malformed_json_and_top_level_types_are_stably_invalid(self) -> None:
        for payload, code in (("not json\n", "INVALID_THEORY_REGISTRY_JSON"), ("[]\n", "INVALID_THEORY_REGISTRY")):
            with self.subTest(code=code):
                project = self.make_project()
                (project / REGISTRY_NAME).write_text(payload, encoding="utf-8")
                completed = self.run_theory(project)
                self.assertEqual(1, completed.returncode)
                self.assertIn(code, completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_profile_routing_requires_theory_artifacts_only_for_theory_and_mixed(self) -> None:
        for profile, expected_exit in (("THEORY", 1), ("MIXED", 1), ("ALGORITHM", 0)):
            with self.subTest(profile=profile):
                project = self.make_project(claim_profile=profile)
                (project / REGISTRY_NAME).unlink()
                completed = self.run_theory(project)
                self.assertEqual(expected_exit, completed.returncode, completed.stdout + completed.stderr)
                if expected_exit:
                    self.assertIn("THEORY_OBLIGATION_REGISTRY_REQUIRED", completed.stdout)

    def test_validate_all_enforces_theory_gate_at_validity_audit(self) -> None:
        for profile in ("THEORY", "MIXED"):
            with self.subTest(profile=profile):
                project = self.make_project(claim_profile=profile, validity_level="V2")
                state = load_json(project / "workflow_state.json")
                state["active_state"] = "VALIDITY_AUDIT"
                state["resume_state"] = "VALIDITY_AUDIT"
                write_json(project / "workflow_state.json", state)
                (project / REGISTRY_NAME).unlink()

                completed = run_all_validator(project)

                self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
                self.assertIn("THEORY_OBLIGATION_REGISTRY_REQUIRED", completed.stdout)

    def test_validate_all_is_read_only(self) -> None:
        project = self.make_project()
        before = {
            path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in project.rglob("*")
            if path.is_file()
        }

        completed = run_all_validator(project)

        after = {
            path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in project.rglob("*")
            if path.is_file()
        }
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
