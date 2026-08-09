"""Shared result and rendering helpers for workflow validators."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any


CLAIM_TYPES = frozenset(
    {
        "THEOREM",
        "LEMMA",
        "COROLLARY",
        "PROPOSITION",
        "DEFINITION",
        "ALGORITHM",
        "ALGORITHM_GUARANTEE",
        "ALGORITHM_PERFORMANCE",
        "ONLINE_ALGORITHM",
        "METHOD",
        "ONLINE",
        "PROTOCOL",
        "EMPIRICAL",
        "BASELINE",
        "COMPLEXITY",
    }
)
ALGORITHM_CLAIM_TYPES = frozenset(
    {
        "ALGORITHM",
        "ALGORITHM_GUARANTEE",
        "ALGORITHM_PERFORMANCE",
        "ONLINE_ALGORITHM",
        "METHOD",
        "ONLINE",
        "PROTOCOL",
        "COMPLEXITY",
    }
)


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


@dataclass(frozen=True)
class SafeFileSnapshot:
    """Metadata derived from one already-open regular-file descriptor."""

    sha256: str
    identity: tuple[int, int]
    data: bytes | None = None


class UnsafePathError(ValueError):
    """A path cannot be safely opened below the trusted project root."""


class StrictJSONError(ValueError):
    """Stable strict-JSON parse failure with an exact JSON path."""

    def __init__(self, reason: str, path: str, detail: str = "") -> None:
        self.reason = reason
        self.path = path
        self.detail = detail
        suffix = f":{detail}" if detail else ""
        super().__init__(f"{reason}:{path}{suffix}")


@dataclass(frozen=True)
class _JSONObjectPairs:
    pairs: list[tuple[str, Any]]


@dataclass(frozen=True)
class _JSONConstant:
    value: str


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


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def positive_integer(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 1


def string_list(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(nonempty_string(item) for item in value)
    )


def canonical_relative_path(raw_path: Any) -> bool:
    if not nonempty_string(raw_path) or "\\" in raw_path:
        return False
    path = PurePosixPath(raw_path)
    return (
        not path.is_absolute()
        and bool(path.parts)
        and all(part not in {"", ".", ".."} for part in path.parts)
        and path.as_posix() == raw_path
    )


def lexical_relative_cli_path(root: Path, candidate: Path, label: str) -> str:
    """Return a canonical lexical path without resolving a possible symlink."""

    root_absolute = Path(os.path.abspath(root))
    candidate_absolute = Path(os.path.abspath(candidate))
    try:
        relative = candidate_absolute.relative_to(root_absolute).as_posix()
    except ValueError as error:
        raise UnsafePathError(f"{label}:outside_root") from error
    if not canonical_relative_path(relative):
        raise UnsafePathError(f"{label}:noncanonical_path")
    return relative


def secure_directory_flags() -> int:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("secure_open_flags_unavailable")
    return (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )


def secure_file_flags() -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("secure_open_flags_unavailable")
    return (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )


def open_root_fd(root: Path) -> int:
    """Open the exact root entry, rejecting a root symlink."""

    try:
        return os.open(Path(os.path.abspath(root)), secure_directory_flags())
    except OSError as error:
        raise UnsafePathError(f"root:unsafe_or_not_directory:{type(error).__name__}") from error


def read_regular_file_at(
    root_fd: int, raw_path: str, *, include_data: bool = False
) -> SafeFileSnapshot:
    """Hash/read one regular file below root without following symlinks.

    Each component is opened relative to an already trusted directory descriptor.
    The digest and optional bytes come from the same leaf descriptor, avoiding a
    path-check/read time-of-check/time-of-use gap.
    """

    if not canonical_relative_path(raw_path):
        raise UnsafePathError("path_must_be_canonical_and_relative")
    parts = PurePosixPath(raw_path).parts
    parent_fd = root_fd
    parent_owned = False
    leaf_fd: int | None = None
    try:
        for component in parts[:-1]:
            try:
                next_fd = os.open(component, secure_directory_flags(), dir_fd=parent_fd)
            except OSError as error:
                if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise UnsafePathError("symlink_or_unsafe_parent") from error
                raise
            if parent_owned:
                os.close(parent_fd)
            parent_fd = next_fd
            parent_owned = True
        try:
            leaf_fd = os.open(parts[-1], secure_file_flags(), dir_fd=parent_fd)
        except OSError as error:
            if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise UnsafePathError("symlink_or_unsafe_file") from error
            raise
        metadata = os.fstat(leaf_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise UnsafePathError("not_a_regular_file")
        digest = hashlib.sha256()
        chunks: list[bytes] | None = [] if include_data else None
        while True:
            chunk = os.read(leaf_fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            if chunks is not None:
                chunks.append(chunk)
        return SafeFileSnapshot(
            sha256=digest.hexdigest(),
            identity=(metadata.st_dev, metadata.st_ino),
            data=b"".join(chunks) if chunks is not None else None,
        )
    finally:
        if leaf_fd is not None:
            os.close(leaf_fd)
        if parent_owned:
            os.close(parent_fd)


def _json_child_path(path: str, key: str) -> str:
    if key.isascii() and key.isidentifier():
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, ensure_ascii=True)}]"


def _reject_non_scalar_unicode(value: str, path: str) -> None:
    for character in value:
        codepoint = ord(character)
        if 0xD800 <= codepoint <= 0xDFFF:
            raise StrictJSONError(
                "NON_SCALAR_UNICODE",
                path,
                f"U+{codepoint:04X}",
            )


def _materialize_strict_json(value: Any, path: str) -> Any:
    if isinstance(value, _JSONConstant):
        raise StrictJSONError("NONSTANDARD_CONSTANT", path, value.value)
    if isinstance(value, _JSONObjectPairs):
        seen: set[str] = set()
        for key, _ in value.pairs:
            _reject_non_scalar_unicode(key, _json_child_path(path, key))
            if key in seen:
                raise StrictJSONError("DUPLICATE_KEY", _json_child_path(path, key))
            seen.add(key)
        return {
            key: _materialize_strict_json(child, _json_child_path(path, key))
            for key, child in value.pairs
        }
    if isinstance(value, list):
        return [
            _materialize_strict_json(child, f"{path}[{index}]")
            for index, child in enumerate(value)
        ]
    if isinstance(value, str):
        _reject_non_scalar_unicode(value, path)
    return value


def strict_json_loads(text: str) -> Any:
    """Decode RFC-style JSON, rejecting duplicates and Python constants."""

    if text.startswith("\ufeff"):
        raise StrictJSONError("UTF8_BOM", "$")
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=lambda pairs: _JSONObjectPairs(pairs),
            parse_constant=lambda value: _JSONConstant(value),
        )
    except json.JSONDecodeError as error:
        raise StrictJSONError(
            "MALFORMED_JSON",
            "$",
            f"line:{error.lineno};column:{error.colno}",
        ) from error
    return _materialize_strict_json(parsed, "$")


def strict_json_load_bytes(data: bytes) -> Any:
    try:
        text = data.decode("utf-8")
    except UnicodeError as error:
        raise StrictJSONError("INVALID_UTF8", "$", type(error).__name__) from error
    return strict_json_loads(text)


def read_json_object_at(root_fd: int, raw_path: str, label: str) -> dict[str, Any]:
    snapshot = read_regular_file_at(root_fd, raw_path, include_data=True)
    assert snapshot.data is not None
    payload = strict_json_load_bytes(snapshot.data)
    if not isinstance(payload, dict):
        raise TypeError(f"{label}:top_level_not_object")
    return payload


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
