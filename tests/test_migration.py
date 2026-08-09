from __future__ import annotations

import importlib.util
import subprocess
import sys
import stat
import unittest
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
from unittest import mock

from tests.helpers import REPOSITORY_ROOT, load_json, write_json


FIXTURE_STATE = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "paper1-failure-case"
    / "workflow_state.json"
)


def load_migration_module():
    module_path = REPOSITORY_ROOT / "scripts" / "migrate_v1_to_v2.py"
    spec = importlib.util.spec_from_file_location("migration_under_test", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load migration module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MigrationTests(unittest.TestCase):
    def run_migration(
        self, project: Path, *extra_args: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(REPOSITORY_ROOT / "scripts" / "migrate_v1_to_v2.py"),
                "--root",
                str(project),
                "--state",
                str(project / "workflow_state.json"),
                *extra_args,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

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

    def test_non_in_place_output_cannot_equal_source(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            original = state_path.read_bytes()

            completed = self.run_migration(
                project, "--output", str(state_path.resolve())
            )

            self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("output_equals_state", completed.stdout)
            self.assertEqual(original, state_path.read_bytes())

    def test_default_migration_refuses_existing_output(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            output_path = project / "workflow_state.v2.json"
            output_path.write_bytes(b"do not overwrite\n")

            completed = self.run_migration(project)

            self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("output_exists", completed.stdout)
            self.assertEqual(b"do not overwrite\n", output_path.read_bytes())

    def test_atomic_writer_cleans_temporary_file_if_replace_fails(self) -> None:
        module = load_migration_module()
        atomic_write_json = getattr(module, "atomic_write_json", None)
        self.assertIsNotNone(atomic_write_json, "atomic_write_json helper is required")
        if atomic_write_json is None:
            return
        with TemporaryDirectory(prefix="schema-v2-atomic-") as directory:
            project = Path(directory)
            target = project / "state.json"
            target.write_bytes(b"original\n")

            with mock.patch.object(
                module.os, "replace", side_effect=OSError("replace failed")
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    atomic_write_json(target, {"schema_version": "2.0"})

            self.assertEqual(b"original\n", target.read_bytes())
            self.assertEqual([target], list(project.iterdir()))

    def test_atomic_no_clobber_publish_rejects_racing_target(self) -> None:
        module = load_migration_module()
        atomic_publish_json = getattr(module, "atomic_publish_json", None)
        self.assertIsNotNone(
            atomic_publish_json, "atomic_publish_json helper is required"
        )
        if atomic_publish_json is None:
            return
        with TemporaryDirectory(prefix="schema-v2-race-") as directory:
            project = Path(directory)
            target = project / "state.v2.json"
            original_link = module.os.link

            def create_racing_target(source, destination):
                Path(destination).write_bytes(b"concurrent writer\n")
                return original_link(source, destination)

            with mock.patch.object(
                module.os, "link", side_effect=create_racing_target
            ):
                with self.assertRaises(FileExistsError):
                    atomic_publish_json(target, {"schema_version": "2.0"}, 0o644)

            self.assertEqual(b"concurrent writer\n", target.read_bytes())
            self.assertEqual([target], list(project.iterdir()))

    def test_migration_rejects_non_schema_1_inputs(self) -> None:
        for schema_version in (None, "2.0", "3.0", 1):
            with self.subTest(schema_version=schema_version):
                with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
                    project = Path(directory)
                    state_path = project / "workflow_state.json"
                    state = load_json(FIXTURE_STATE)
                    if schema_version is None:
                        state.pop("schema_version")
                    else:
                        state["schema_version"] = schema_version
                    write_json(state_path, state)

                    completed = self.run_migration(project)

                    self.assertEqual(
                        1, completed.returncode, completed.stdout + completed.stderr
                    )
                    self.assertIn("source_schema_not_1_x", completed.stdout)
                    self.assertFalse((project / "workflow_state.v2.json").exists())

    def test_migration_rejects_non_boolean_n0_lock(self) -> None:
        for malformed in (1, 0, "true", [], {}):
            with self.subTest(malformed=malformed):
                with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
                    project = Path(directory)
                    state_path = project / "workflow_state.json"
                    state = load_json(FIXTURE_STATE)
                    state["gates"]["n0_4_locked"] = malformed
                    write_json(state_path, state)

                    completed = self.run_migration(project)

                    self.assertEqual(
                        1, completed.returncode, completed.stdout + completed.stderr
                    )
                    self.assertIn("n0_4_locked_not_boolean", completed.stdout)
                    self.assertFalse((project / "workflow_state.v2.json").exists())

    def test_in_place_migration_preserves_source_permission_bits(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            state_path.chmod(0o644)

            completed = self.run_migration(project, "--in-place")

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual(0o644, stat.S_IMODE(state_path.stat().st_mode))

    def test_nested_custom_output_is_created_atomically_with_source_mode(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            state_path.chmod(0o644)
            output_path = project / "nested" / "states" / "workflow_state.v2.json"

            completed = self.run_migration(
                project, "--output", str(output_path)
            )

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual("2.0", load_json(output_path)["schema_version"])
            self.assertEqual(0o644, stat.S_IMODE(output_path.stat().st_mode))

    def test_custom_output_rejects_parent_symlink_outside_root(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-migration-") as directory:
            project = Path(directory)
            state_path = project / "workflow_state.json"
            copy2(FIXTURE_STATE, state_path)
            with TemporaryDirectory(prefix="schema-v2-outside-") as outside:
                link = project / "nested"
                link.symlink_to(Path(outside), target_is_directory=True)
                output_path = link / "workflow_state.v2.json"

                completed = self.run_migration(
                    project, "--output", str(output_path)
                )

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertFalse((Path(outside) / "workflow_state.v2.json").exists())


if __name__ == "__main__":
    unittest.main()
