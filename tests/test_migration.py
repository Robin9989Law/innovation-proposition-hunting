from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory

from tests.helpers import REPOSITORY_ROOT, load_json, write_json


FIXTURE_STATE = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "paper1-failure-case"
    / "workflow_state.json"
)


class MigrationTests(unittest.TestCase):
    def test_default_migration_preserves_v1_and_resets_validity(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            original = state_path.read_bytes()

            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY_ROOT / "scripts" / "migrate_v1_to_v2.py"),
                    "--root",
                    str(project),
                    "--state",
                    str(state_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            output_path = project / "workflow_state.v2.json"
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual(original, state_path.read_bytes())
            migrated = load_json(output_path)
            self.assertEqual("2.0", migrated["schema_version"])
            self.assertEqual("VALIDITY", migrated["active_track"])
            self.assertEqual("CLAIM_FREEZE", migrated["active_state"])
            self.assertEqual("N0-4C", migrated["novelty_level"])
            self.assertEqual("V0", migrated["validity_level"])
            self.assertEqual(1, migrated["validation_epoch"])
            self.assertEqual("", migrated["claim_bundle_sha256"])
            self.assertEqual({}, migrated["independent_audit"])
            self.assertFalse(migrated["gates"]["compute_authorized"])

    def test_in_place_migration_creates_byte_identical_backup(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            original = state_path.read_bytes()

            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY_ROOT / "scripts" / "migrate_v1_to_v2.py"),
                    "--root",
                    str(project),
                    "--state",
                    str(state_path),
                    "--in-place",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            backups = list(project.glob("workflow_state.json.v1-backup-*"))
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual(1, len(backups))
            self.assertEqual(original, backups[0].read_bytes())
            self.assertEqual("2.0", load_json(state_path)["schema_version"])

    def test_custom_output_maps_unlocked_novelty_to_n0_3(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            state = load_json(state_path)
            state["n0_4_status"] = "NOT_LOCKED"
            state["gates"]["n0_4_locked"] = False
            write_json(state_path, state)
            output_path = project / "custom-state.json"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY_ROOT / "scripts" / "migrate_v1_to_v2.py"),
                    "--root",
                    str(project),
                    "--state",
                    str(state_path),
                    "--output",
                    str(output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual("N0-3", load_json(output_path)["novelty_level"])


if __name__ == "__main__":
    unittest.main()
