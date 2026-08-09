"""Shared result and rendering helpers for workflow validators."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum
import hashlib
import json
from pathlib import Path


class ExitCode(IntEnum):
    READY = 0
    INVALID = 1
    BLOCKED = 2
    MIGRATION_REQUIRED = 3


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str  # INVALID | BLOCKED | MIGRATION
    item_id: str
    detail: str


def choose_exit(issues: list[Issue]) -> ExitCode:
    severities = {issue.severity for issue in issues}
    if "MIGRATION" in severities:
        return ExitCode.MIGRATION_REQUIRED
    if "INVALID" in severities:
        return ExitCode.INVALID
    if "BLOCKED" in severities:
        return ExitCode.BLOCKED
    return ExitCode.READY


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render(name: str, issues: list[Issue], as_json: bool = False) -> str:
    exit_code = choose_exit(issues)
    payload = {
        "validator": name,
        "status": exit_code.name,
        "exit_code": int(exit_code),
        "issues": [asdict(issue) for issue in issues],
    }
    if as_json:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    lines = [f"{name}_status={exit_code.name}", f"{name}_issues={len(issues)}"]
    lines.extend(
        f"{issue.severity}\t{issue.code}\t{issue.item_id}\t{issue.detail}"
        for issue in issues
    )
    return "\n".join(lines)
