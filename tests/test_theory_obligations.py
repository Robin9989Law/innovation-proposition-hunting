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
from scripts.validation_common import StrictJSONError, strict_json_loads


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


def configure_random_property_na(
    project: Path,
    *,
    accepted: Any,
    capability_available: Any,
    verdict: Any,
) -> dict[str, Any]:
    state = load_json(project / "workflow_state.json")
    state["independent_audit"]["capability_available"] = capability_available
    state["independent_audit"]["verdict"] = verdict
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
        "mathematical_reason": "The finite domain is exhausted symbolically.",
        "independent_audit_acceptance": {
            "accepted": accepted,
            "reviewer_agent_id": "agent-b",
        },
    }
    write_obligations(project, obligations)
    return obligation


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

    def test_duplicate_json_keys_are_rejected_at_every_theory_input_depth(self) -> None:
        cases = (
            (
                REGISTRY_NAME,
                '  "schema_version": "2.0",\n',
                '  "schema_version": "2.0",\n  "schema_version": "2.0",\n',
                "INVALID_THEORY_REGISTRY_JSON",
                "DUPLICATE_KEY:$.schema_version",
            ),
            (
                REGISTRY_NAME,
                '      "claim_id": "C-THEOREM-1",\n',
                '      "claim_id": "C-THEOREM-1",\n      "claim_id": "C-THEOREM-1",\n',
                "INVALID_THEORY_REGISTRY_JSON",
                "DUPLICATE_KEY:$.obligations[0].claim_id",
            ),
            (
                REGISTRY_NAME,
                '          "kind": "MINIMAL_POSITIVE",\n',
                '          "kind": "MINIMAL_POSITIVE",\n          "kind": "MINIMAL_POSITIVE",\n',
                "INVALID_THEORY_REGISTRY_JSON",
                "DUPLICATE_KEY:$.obligations[0].witnesses[0].kind",
            ),
            (
                "claim_inventory.json",
                '      "statement": "For every real x, if x >= 0, then x + 1 > 0.",\n',
                '      "statement": "For every real x, if x >= 0, then x + 1 > 0.",\n'
                '      "statement": "For every real x, if x >= 0, then x + 1 > 0.",\n',
                "INVALID_CLAIM_INVENTORY_JSON",
                "DUPLICATE_KEY:$.claims[0].statement",
            ),
            (
                "workflow_state.json",
                '  "claim_profile": "THEORY",\n',
                '  "claim_profile": "THEORY",\n  "claim_profile": "THEORY",\n',
                "INVALID_WORKFLOW_STATE_JSON",
                "DUPLICATE_KEY:$.claim_profile",
            ),
        )
        for file_name, needle, replacement, code, path in cases:
            with self.subTest(file_name=file_name, path=path):
                project = self.make_project()
                artifact = project / file_name
                raw = artifact.read_text(encoding="utf-8")
                self.assertEqual(1, raw.count(needle))
                artifact.write_text(raw.replace(needle, replacement), encoding="utf-8")

                completed = self.run_theory(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn(code, completed.stdout)
                self.assertIn(path, completed.stdout)
                self.assertNotIn("VALIDATOR_ERROR", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_nonstandard_json_constants_and_utf8_bom_are_rejected(self) -> None:
        project = self.make_project()
        registry_path = project / REGISTRY_NAME
        raw = registry_path.read_text(encoding="utf-8")
        registry_path.write_text(
            raw.replace('  "validation_epoch": 1,\n', '  "validation_epoch": NaN,\n', 1),
            encoding="utf-8",
        )

        completed = self.run_theory(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("INVALID_THEORY_REGISTRY_JSON", completed.stdout)
        self.assertIn("NONSTANDARD_CONSTANT:$.validation_epoch:NaN", completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)

        project = self.make_project()
        state_path = project / "workflow_state.json"
        state_path.write_bytes(b"\xef\xbb\xbf" + state_path.read_bytes())

        completed = self.run_theory(project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("INVALID_WORKFLOW_STATE_JSON", completed.stdout)
        self.assertIn("UTF8_BOM:$", completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)

    def test_isolated_unicode_surrogates_are_rejected_with_ascii_safe_paths(self) -> None:
        cases = (
            (
                "workflow_state.json",
                '  "claim_profile": "THEORY",\n',
                '  "claim_profile": "\\ud800",\n',
                "INVALID_WORKFLOW_STATE_JSON",
                "NON_SCALAR_UNICODE:$.claim_profile:U+D800",
            ),
            (
                "claim_inventory.json",
                '      "statement": "For every real x, if x >= 0, then x + 1 > 0.",\n',
                '      "statement": "\\udc00",\n',
                "INVALID_CLAIM_INVENTORY_JSON",
                "NON_SCALAR_UNICODE:$.claims[0].statement:U+DC00",
            ),
            (
                REGISTRY_NAME,
                '          "command": "python3 checks/theory_witness.py minimal-positive",\n',
                '          "command": "nested-\\ud800-value",\n',
                "INVALID_THEORY_REGISTRY_JSON",
                "NON_SCALAR_UNICODE:$.obligations[0].witnesses[0].command:U+D800",
            ),
            (
                REGISTRY_NAME,
                '      "claim_id": "C-THEOREM-1",\n',
                '      "\\ud800": 1,\n      "\\ud800": 2,\n'
                '      "claim_id": "C-THEOREM-1",\n',
                "INVALID_THEORY_REGISTRY_JSON",
                'NON_SCALAR_UNICODE:$.obligations[0]["\\ud800"]:U+D800',
            ),
        )
        for file_name, needle, replacement, code, detail in cases:
            with self.subTest(file_name=file_name, detail=detail):
                project = self.make_project()
                artifact = project / file_name
                raw = artifact.read_text(encoding="utf-8")
                self.assertEqual(1, raw.count(needle))
                artifact.write_text(raw.replace(needle, replacement), encoding="utf-8")

                completed = self.run_theory(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn(code, completed.stdout)
                self.assertIn(detail, completed.stdout)
                self.assertNotIn("VALIDATOR_ERROR", completed.stdout)
                self.assertNotIn("UnicodeEncodeError", completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)
                completed.stdout.encode("ascii")

    def test_valid_surrogate_pair_and_native_emoji_materialize_identically(self) -> None:
        escaped = strict_json_loads(
            r'{"\ud83d\ude00":"\ud83d\ude00"}'
        )
        native = strict_json_loads('{"😀":"😀"}')

        self.assertEqual({"😀": "😀"}, escaped)
        self.assertEqual(native, escaped)

    def test_duplicate_valid_emoji_key_has_ascii_safe_path(self) -> None:
        with self.assertRaises(StrictJSONError) as raised:
            strict_json_loads('{"😀":1,"\\ud83d\\ude00":2}')

        detail = str(raised.exception)
        self.assertEqual('DUPLICATE_KEY:$["\\ud83d\\ude00"]', detail)
        detail.encode("ascii")

    def test_unavailable_reviewer_capability_preserves_blocked_na(self) -> None:
        project = self.make_project()
        configure_random_property_na(
            project,
            accepted=False,
            capability_available=False,
            verdict="BLOCKED",
        )

        completed = self.run_theory(project)

        self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("BLOCKED_CAPABILITY", completed.stdout)
        self.assertNotIn("INVALID\t", completed.stdout)
        self.assertNotIn("RANDOM_PROPERTY_NA_NOT_AUDIT_ACCEPTED", completed.stdout)

        completed = run_all_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("BLOCKED_CAPABILITY", completed.stdout)
        self.assertIn("STALE_AUDIT", completed.stdout)
        self.assertIn("validation_suite_status=INVALID", completed.stdout)

    def test_unavailable_capability_does_not_hide_local_na_invalidity(self) -> None:
        cases = (
            ("accepted_true", "RANDOM_PROPERTY_NA_NOT_AUDIT_ACCEPTED"),
            ("bad_status", "INVALID_RANDOM_PROPERTY_NA"),
            ("blank_reason", "RANDOM_PROPERTY_NA_REASON_REQUIRED"),
            ("self_review", "INVALID_RANDOM_PROPERTY_AUDIT_REVIEWER"),
            ("bad_verdict", "INVALID_RANDOM_PROPERTY_AUDIT_VERDICT"),
        )
        for label, code in cases:
            with self.subTest(label=label):
                project = self.make_project()
                obligation = configure_random_property_na(
                    project,
                    accepted=label == "accepted_true",
                    capability_available=False,
                    verdict="PASS" if label == "bad_verdict" else "BLOCKED",
                )
                if label == "bad_status":
                    obligation["random_property"]["status"] = []
                elif label == "blank_reason":
                    obligation["random_property"]["mathematical_reason"] = ""
                elif label == "self_review":
                    state = load_json(project / "workflow_state.json")
                    state["independent_audit"]["reviewer_agent_id"] = "agent-a"
                    write_json(project / "workflow_state.json", state)
                    obligation["random_property"]["independent_audit_acceptance"][
                        "reviewer_agent_id"
                    ] = "agent-a"
                write_obligations(project, load_obligations(project) | {
                    "obligations": [obligation]
                })

                completed = self.run_theory(project)

                self.assertEqual(1, completed.returncode)
                self.assertIn("BLOCKED_CAPABILITY", completed.stdout)
                self.assertIn(code, completed.stdout)

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


GOOD_MECHANISM = (
    "Removing premise x >= 0 admits x = -1, so the stated implication fails."
)
GOOD_SENSITIVITY_CONTROL = (
    "nuisance scale 0.5 versus 2.0 keeps the bound strictly positive."
)


def make_witnesses_bite_clean(obligation: dict[str, Any]) -> None:
    find_witness(obligation, "PREMISE_REMOVAL")["mechanism"] = GOOD_MECHANISM
    find_witness(obligation, "NONZERO_NUISANCE")[
        "sensitivity_control"
    ] = GOOD_SENSITIVITY_CONTROL


def configure_author_proposed_na(
    project: Path,
    *,
    reason: Any = "The finite domain is exhausted symbolically.",
    acceptance: Any = None,
) -> dict[str, Any]:
    obligations = load_obligations(project)
    obligation = first_obligation(obligations)
    obligation["witnesses"] = [
        witness
        for witness in obligation["witnesses"]
        if witness["kind"] != "RANDOM_PROPERTY"
    ]
    random_property: dict[str, Any] = {
        "status": "NOT_APPLICABLE",
        "mathematical_reason": reason,
        "proposed_by_author": True,
    }
    if acceptance is not None:
        random_property["independent_audit_acceptance"] = acceptance
    obligation["random_property"] = random_property
    write_obligations(project, obligations)
    return obligation


class WitnessBiteTests(unittest.TestCase):
    def make_project(self) -> Path:
        temporary_directory, project = make_valid_project(claim_profile="THEORY")
        self.addCleanup(temporary_directory.cleanup)
        return project

    def run_theory(
        self, project: Path, *extra_args: str
    ) -> subprocess.CompletedProcess[str]:
        return run_script(
            "validate_theory_obligations.py", project, extra_args=extra_args
        )

    def load_bite_clean_obligations(self, project: Path) -> dict[str, Any]:
        obligations = load_obligations(project)
        make_witnesses_bite_clean(first_obligation(obligations))
        write_obligations(project, obligations)
        return obligations

    def test_missing_mechanism_warns_by_default_and_fails_in_strict(self) -> None:
        project = self.make_project()

        completed = self.run_theory(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("theory_obligations_status=READY", completed.stdout)
        self.assertIn("WARNING\tWITNESS_NO_BITE", completed.stdout)
        self.assertIn(
            "PREMISE_REMOVAL.mechanism:missing_or_empty", completed.stdout
        )

        project = self.make_project()
        completed = self.run_theory(project, "--strict-new-checks")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("INVALID\tWITNESS_NO_BITE", completed.stdout)

    def test_constructive_tautology_phrases_are_reported(self) -> None:
        for phrase in ("by construction", "trivially", "by definition", "恒真"):
            with self.subTest(phrase=phrase):
                project = self.make_project()
                obligations = load_obligations(project)
                find_witness(first_obligation(obligations), "PREMISE_REMOVAL")[
                    "mechanism"
                ] = f"The observed failure holds {phrase} for this encoding."
                write_obligations(project, obligations)

                completed = self.run_theory(project)

                self.assertEqual(
                    0, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("WARNING\tWITNESS_NO_BITE", completed.stdout)
                self.assertIn(
                    f"PREMISE_REMOVAL.mechanism:constructive_tautology:{phrase}",
                    completed.stdout,
                )

    def test_short_mechanism_is_reported(self) -> None:
        project = self.make_project()
        obligations = load_obligations(project)
        find_witness(first_obligation(obligations), "PREMISE_REMOVAL")[
            "mechanism"
        ] = "premise removed"
        write_obligations(project, obligations)

        completed = self.run_theory(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("WITNESS_NO_BITE", completed.stdout)
        self.assertIn("PREMISE_REMOVAL.mechanism:too_short", completed.stdout)

    def test_missing_or_short_sensitivity_control_is_reported(self) -> None:
        project = self.make_project()
        obligations = load_obligations(project)
        obligation = first_obligation(obligations)
        find_witness(obligation, "PREMISE_REMOVAL")["mechanism"] = GOOD_MECHANISM
        write_obligations(project, obligations)

        completed = self.run_theory(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn(
            "NONZERO_NUISANCE.sensitivity_control:missing_or_empty",
            completed.stdout,
        )

        project = self.make_project()
        obligations = load_obligations(project)
        obligation = first_obligation(obligations)
        find_witness(obligation, "PREMISE_REMOVAL")["mechanism"] = GOOD_MECHANISM
        find_witness(obligation, "NONZERO_NUISANCE")["sensitivity_control"] = "nu=0"
        write_obligations(project, obligations)

        completed = self.run_theory(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn(
            "NONZERO_NUISANCE.sensitivity_control:too_short", completed.stdout
        )

        project = self.make_project()
        completed = self.run_theory(project, "--strict-new-checks")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("INVALID\tWITNESS_NO_BITE", completed.stdout)

    def test_qualified_mechanism_and_sensitivity_control_are_clean(self) -> None:
        project = self.make_project()
        self.load_bite_clean_obligations(project)

        completed = self.run_theory(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertNotIn("WITNESS_NO_BITE", completed.stdout)
        self.assertIn("theory_obligations_status=READY", completed.stdout)

    def test_subclaims_without_any_addressing_witness_warn(self) -> None:
        project = self.make_project()
        obligations = self.load_bite_clean_obligations(project)
        first_obligation(obligations)["subclaims"] = [
            "Sub-law alpha holds.",
            "Sub-law beta holds.",
        ]
        write_obligations(project, obligations)

        completed = self.run_theory(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("theory_obligations_status=READY", completed.stdout)
        self.assertEqual(2, completed.stdout.count("SUBCLAIM_WITNESS_GAP"))
        self.assertIn("WARNING\tSUBCLAIM_WITNESS_GAP", completed.stdout)

        project = self.make_project()
        obligations = self.load_bite_clean_obligations(project)
        first_obligation(obligations)["subclaims"] = ["Sub-law alpha holds."]
        write_obligations(project, obligations)
        completed = self.run_theory(project, "--strict-new-checks")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("INVALID\tSUBCLAIM_WITNESS_GAP", completed.stdout)

    def test_partial_subclaim_coverage_reports_only_the_gap(self) -> None:
        project = self.make_project()
        obligations = self.load_bite_clean_obligations(project)
        obligation = first_obligation(obligations)
        obligation["subclaims"] = ["Sub-law alpha holds.", "Sub-law beta holds."]
        obligation["witnesses"][0]["addresses_subclaim"] = "Sub-law alpha holds."
        write_obligations(project, obligations)

        completed = self.run_theory(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual(1, completed.stdout.count("SUBCLAIM_WITNESS_GAP"))
        self.assertIn(
            "subclaim_without_witness:Sub-law beta holds.", completed.stdout
        )
        self.assertNotIn(
            "subclaim_without_witness:Sub-law alpha holds.", completed.stdout
        )

    def test_full_subclaim_coverage_is_clean(self) -> None:
        project = self.make_project()
        obligations = self.load_bite_clean_obligations(project)
        obligation = first_obligation(obligations)
        obligation["subclaims"] = ["Sub-law alpha holds.", "Sub-law beta holds."]
        obligation["witnesses"][0]["addresses_subclaim"] = "Sub-law alpha holds."
        obligation["witnesses"][1]["addresses_subclaim"] = "Sub-law beta holds."
        write_obligations(project, obligations)

        completed = self.run_theory(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertNotIn("SUBCLAIM_WITNESS_GAP", completed.stdout)

    def test_obligation_without_subclaims_skips_coverage_check(self) -> None:
        project = self.make_project()
        self.load_bite_clean_obligations(project)

        completed = self.run_theory(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertNotIn("SUBCLAIM_WITNESS_GAP", completed.stdout)

    def test_author_proposed_exemption_is_pending_until_ratified(self) -> None:
        project = self.make_project()
        configure_author_proposed_na(project)

        completed = self.run_theory(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("theory_obligations_status=READY", completed.stdout)
        self.assertIn(
            "WARNING\tRANDOM_PROPERTY_EXEMPTION_PENDING", completed.stdout
        )
        self.assertNotIn(
            "INVALID_RANDOM_PROPERTY_AUDIT_ACCEPTANCE", completed.stdout
        )
        self.assertNotIn("RANDOM_PROPERTY_NA_NOT_AUDIT_ACCEPTED", completed.stdout)

        project = self.make_project()
        configure_author_proposed_na(project)
        completed = self.run_theory(project, "--strict-new-checks")
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn(
            "INVALID\tRANDOM_PROPERTY_EXEMPTION_PENDING", completed.stdout
        )

    def test_reviewer_ratified_exemption_closes_cleanly(self) -> None:
        project = self.make_project()
        configure_author_proposed_na(
            project,
            acceptance={"accepted": True, "reviewer_agent_id": "agent-b"},
        )

        completed = self.run_theory(project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertNotIn("RANDOM_PROPERTY_EXEMPTION_PENDING", completed.stdout)
        self.assertIn("theory_obligations_status=READY", completed.stdout)

    def test_empty_reason_stays_invalid_even_when_author_proposed(self) -> None:
        project = self.make_project()
        configure_author_proposed_na(project, reason="")

        completed = self.run_theory(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("RANDOM_PROPERTY_NA_REASON_REQUIRED", completed.stdout)


if __name__ == "__main__":
    unittest.main()
