from __future__ import annotations

import stat
import subprocess
import sys
import unittest
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "paper1-failure-case"


class SchemaV2MigrationTests(unittest.TestCase):
    def test_schema_v1_requires_migration(self) -> None:
        with TemporaryDirectory(prefix="schema-v2-fixture-") as temporary_directory:
            fixture_copy = Path(temporary_directory) / FIXTURE_ROOT.name
            copytree(FIXTURE_ROOT, fixture_copy)
            fixture_directories = [
                fixture_copy,
                *(path for path in fixture_copy.rglob("*") if path.is_dir()),
            ]
            for directory in fixture_directories:
                directory.chmod(directory.stat().st_mode | stat.S_IWUSR)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY_ROOT / "scripts" / "validate_all.py"),
                    "--root",
                    str(fixture_copy),
                    "--state",
                    str(fixture_copy / "workflow_state.json"),
                    "--current-year",
                    "2026",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(3, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("MIGRATION_REQUIRED", completed.stdout)


if __name__ == "__main__":
    unittest.main()
