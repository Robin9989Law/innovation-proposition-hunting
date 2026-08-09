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
    append_text,
    load_json,
    make_valid_project,
    run_script,
    run_validator,
    write_json,
)


REQUIRED_CLAIM_FIELDS = (
    "claim_id",
    "statement",
    "claim_type",
    "locations",
    "evidence_responsibility",
    "risk_terms",
    "status",
    "validation_epoch",
)


def expected_occurrence_id(
    relative_path: str, line: str, term: str, ordinal: int
) -> str:
    normalized = " ".join(line.split()).casefold()
    raw = f"{relative_path}\0{term.casefold()}\0{normalized}\0{ordinal}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def claim(
    occurrence_ids: list[str],
    *,
    claim_id: str = "C-0001",
    statement: str = "The exact inverse is recovered.",
    validation_epoch: int = 1,
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "statement": statement,
        "claim_type": "THEOREM",
        "locations": ["manuscript.md:1"],
        "evidence_responsibility": "Supply a proof of the published statement.",
        "risk_terms": ["exact"],
        "status": "FROZEN",
        "validation_epoch": validation_epoch,
        "occurrence_ids": occurrence_ids,
    }


def set_inventory(
    project: Path,
    *,
    claims: list[dict[str, Any]],
    sources: list[str] | None = None,
    validation_epoch: int = 1,
) -> None:
    write_json(
        project / "claim_inventory.json",
        {
            "schema_version": "2.0",
            "validation_epoch": validation_epoch,
            "manuscript_sources": sources or ["manuscript.md"],
            "claims": claims,
        },
    )


class ClaimInventoryTests(unittest.TestCase):
    def make_project(
        self, *, validity_level: str = "V2"
    ) -> tuple[object, Path]:
        temporary_directory, project = make_valid_project(
            claim_profile="THEORY", validity_level=validity_level
        )
        self.addCleanup(temporary_directory.cleanup)
        return temporary_directory, project

    def test_unregistered_exact_claim_fails_before_independent_audit(self) -> None:
        _, project = self.make_project(validity_level="V2")
        (project / "manuscript.md").write_text(
            "The exact inverse recovers every anomaly losslessly.\n",
            encoding="utf-8",
        )
        set_inventory(project, claims=[])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("UNREGISTERED_HIGH_RISK_CLAIM", completed.stdout)

    def test_english_terms_are_case_insensitive(self) -> None:
        for term in ("EXACT", "Universal", "BoUnDeD"):
            with self.subTest(term=term):
                _, project = self.make_project(validity_level="V1")
                (project / "manuscript.md").write_text(
                    f"This is a {term} conclusion.\n", encoding="utf-8"
                )
                set_inventory(project, claims=[])

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("UNREGISTERED_HIGH_RISK_CLAIM", completed.stdout)

    def test_chinese_equivalents_are_scanned(self) -> None:
        _, project = self.make_project(validity_level="V0")
        (project / "manuscript.md").write_text(
            "该结论是精确、普适、普遍且有界的。\n", encoding="utf-8"
        )
        set_inventory(project, claims=[])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("claim_inventory_issues=4", completed.stdout)
        self.assertEqual(4, completed.stdout.count("UNREGISTERED_HIGH_RISK_CLAIM"))

    def test_theorem_headings_and_tex_environments_are_scanned(self) -> None:
        _, project = self.make_project(validity_level="V2")
        (project / "manuscript.md").write_text(
            "# Theorem 1\n## 引理 2\n**Corollary 3.**\n定理 4.\n",
            encoding="utf-8",
        )
        (project / "appendix.tex").write_text(
            "\\begin{corollary}\n\\begin{lemma*}\n", encoding="utf-8"
        )
        set_inventory(project, claims=[], sources=["manuscript.md", "appendix.tex"])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("claim_inventory_issues=6", completed.stdout)

    def test_normal_prose_without_risk_terms_is_ready(self) -> None:
        _, project = self.make_project(validity_level="V2")

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("claim_inventory_status=READY", completed.stdout)

    def test_registered_case_variant_uses_stable_occurrence_id(self) -> None:
        _, project = self.make_project(validity_level="V2")
        line = "The EXACT inverse is recovered."
        (project / "manuscript.md").write_text(line + "\n", encoding="utf-8")
        occurrence = expected_occurrence_id("manuscript.md", line, "exact", 1)
        set_inventory(project, claims=[claim([occurrence], statement=line)])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_duplicate_identical_lines_have_distinct_ordinals(self) -> None:
        _, project = self.make_project(validity_level="V2")
        line = "The exact inverse is recovered."
        (project / "manuscript.md").write_text(
            f"{line}\n{line}\n", encoding="utf-8"
        )
        first = expected_occurrence_id("manuscript.md", line, "exact", 1)
        second = expected_occurrence_id("manuscript.md", line, "exact", 2)
        self.assertNotEqual(first, second)
        set_inventory(project, claims=[claim([first, second])])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_occurrence_cannot_be_bound_to_two_claims(self) -> None:
        _, project = self.make_project(validity_level="V2")
        line = "The exact inverse is recovered."
        (project / "manuscript.md").write_text(line + "\n", encoding="utf-8")
        occurrence = expected_occurrence_id("manuscript.md", line, "exact", 1)
        set_inventory(
            project,
            claims=[
                claim([occurrence], claim_id="C-0001"),
                claim([occurrence], claim_id="C-0002"),
            ],
        )

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("DUPLICATE_OCCURRENCE_BINDING", completed.stdout)

    def test_inventory_binding_must_reference_a_scanned_occurrence(self) -> None:
        _, project = self.make_project(validity_level="V2")
        set_inventory(project, claims=[claim(["f" * 64])])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("ORPHAN_OCCURRENCE_BINDING", completed.stdout)

    def test_every_required_claim_field_is_enforced(self) -> None:
        for field in REQUIRED_CLAIM_FIELDS:
            with self.subTest(field=field):
                _, project = self.make_project(validity_level="V2")
                malformed = claim([])
                malformed.pop(field)
                set_inventory(project, claims=[malformed])

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("INVALID_CLAIM_FIELD", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_claim_field_types_are_strictly_validated(self) -> None:
        malformed_values = {
            "claim_id": 7,
            "statement": [],
            "claim_type": {},
            "locations": "manuscript.md:1",
            "evidence_responsibility": 3,
            "risk_terms": "exact",
            "status": [],
            "validation_epoch": True,
            "occurrence_ids": "f" * 64,
        }
        for field, value in malformed_values.items():
            with self.subTest(field=field):
                _, project = self.make_project(validity_level="V2")
                malformed = claim([])
                malformed[field] = value
                set_inventory(project, claims=[malformed])

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("INVALID_CLAIM_FIELD", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_duplicate_claim_ids_are_invalid(self) -> None:
        _, project = self.make_project(validity_level="V2")
        set_inventory(project, claims=[claim([]), claim([])])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("DUPLICATE_CLAIM_ID", completed.stdout)

    def test_claim_and_inventory_epochs_must_match_state(self) -> None:
        for target in ("claim", "inventory"):
            with self.subTest(target=target):
                _, project = self.make_project(validity_level="V2")
                claims = [claim([], validation_epoch=2)] if target == "claim" else []
                set_inventory(
                    project,
                    claims=claims,
                    validation_epoch=2 if target == "inventory" else 1,
                )

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("VALIDATION_EPOCH_MISMATCH", completed.stdout)

    def test_malformed_json_and_top_level_types_are_stably_invalid(self) -> None:
        _, project = self.make_project(validity_level="V2")
        for raw, code in (
            ("{not json\n", "INVALID_CLAIM_INVENTORY_JSON"),
            ("[]\n", "INVALID_CLAIM_INVENTORY"),
        ):
            with self.subTest(raw=raw):
                (project / "claim_inventory.json").write_text(raw, encoding="utf-8")

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn(code, completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_inventory_structure_types_are_stably_invalid(self) -> None:
        cases = (
            ({"schema_version": "1.0", "manuscript_sources": [], "claims": []},
             "INVALID_INVENTORY_FIELD"),
            ({"schema_version": "2.0", "manuscript_sources": "manuscript.md", "claims": []},
             "INVALID_INVENTORY_FIELD"),
            ({"schema_version": "2.0", "manuscript_sources": ["manuscript.md"], "claims": {}},
             "INVALID_INVENTORY_FIELD"),
        )
        _, project = self.make_project(validity_level="V2")
        for payload, code in cases:
            with self.subTest(payload=payload):
                write_json(project / "claim_inventory.json", payload)

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn(code, completed.stdout)

    def test_source_paths_are_relative_supported_and_unique(self) -> None:
        _, project = self.make_project(validity_level="V2")
        cases = (
            (["../outside.md"], "UNSAFE_MANUSCRIPT_SOURCE"),
            ([str((project / "manuscript.md").resolve())], "UNSAFE_MANUSCRIPT_SOURCE"),
            (["workflow_state.json"], "UNSUPPORTED_MANUSCRIPT_SOURCE"),
            (["manuscript.md", "manuscript.md"], "DUPLICATE_MANUSCRIPT_SOURCE"),
            (["missing.md"], "MISSING_MANUSCRIPT_SOURCE"),
        )
        for sources, code in cases:
            with self.subTest(sources=sources):
                set_inventory(project, claims=[], sources=sources)

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn(code, completed.stdout)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_source_symlink_outside_root_is_rejected(self) -> None:
        _, project = self.make_project(validity_level="V2")
        with TemporaryDirectory(prefix="claim-inventory-outside-") as directory:
            outside = Path(directory) / "outside.md"
            outside.write_text("The exact result.\n", encoding="utf-8")
            (project / "linked.md").symlink_to(outside)
            set_inventory(project, claims=[], sources=["linked.md"])

            completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("UNSAFE_MANUSCRIPT_SOURCE", completed.stdout)

    def test_inventory_and_state_cli_paths_must_stay_within_root(self) -> None:
        _, project = self.make_project(validity_level="V2")
        with TemporaryDirectory(prefix="claim-inventory-outside-") as directory:
            outside = Path(directory)
            outside_inventory = outside / "claim_inventory.json"
            outside_inventory.write_bytes((project / "claim_inventory.json").read_bytes())
            outside_state = outside / "workflow_state.json"
            outside_state.write_bytes((project / "workflow_state.json").read_bytes())
            cases = (
                ("--inventory", outside_inventory),
                ("--state", outside_state),
            )
            for option, path in cases:
                with self.subTest(option=option):
                    completed = run_script(
                        "validate_claim_inventory.py",
                        project,
                        (option, str(path)),
                    )

                    self.assertEqual(
                        1, completed.returncode, completed.stdout + completed.stderr
                    )
                    self.assertIn("VALIDATOR_ERROR", completed.stdout)
                    self.assertIn("outside_root", completed.stdout)

    def test_post_audit_claim_promotion_is_rejected_by_validate_all(self) -> None:
        _, project = self.make_project(validity_level="V3")
        append_text(project / "manuscript.md", "The result is universally bounded.\n")

        completed = run_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("CLAIM_PROMOTION_UNAUDITED", completed.stdout)

    def test_validate_all_claim_scan_is_read_only(self) -> None:
        _, project = self.make_project(validity_level="V2")
        before = {
            path.relative_to(project).as_posix(): path.read_bytes()
            for path in project.rglob("*")
            if path.is_file()
        }

        completed = run_validator(project)

        after = {
            path.relative_to(project).as_posix(): path.read_bytes()
            for path in project.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertIn("claim_inventory_status=READY", completed.stdout)


if __name__ == "__main__":
    unittest.main()
