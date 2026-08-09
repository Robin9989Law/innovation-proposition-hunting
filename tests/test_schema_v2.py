from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "paper1-failure-case"


class SchemaV2MigrationTests(unittest.TestCase):
    def test_schema_v1_requires_migration(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(REPOSITORY_ROOT / "scripts" / "validate_all.py"),
                "--root",
                str(FIXTURE_ROOT),
                "--state",
                str(FIXTURE_ROOT / "workflow_state.json"),
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
