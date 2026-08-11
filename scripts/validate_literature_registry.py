#!/usr/bin/env python3
"""Validate that academic URLs in research records map to a literature registry."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from validation_common import (
    DEFAULT_ARTIFACT_PATHS,
    Issue,
    ProjectContext,
    UnsafePathError,
    choose_exit,
    lexical_relative_cli_path,
    open_root_fd,
    read_json_object_at,
    read_regular_file_at,
    render,
    secure_directory_flags,
)


URL_RE = re.compile(r"https?://[^\s<>)\"`\]]+")
ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|html|pdf)/(\d{4}\.\d{4,5})", re.I)
ACADEMIC_HOST_MARKERS = (
    "aclanthology.org",
    "arxiv.org",
    "doi.org",
    "openreview.net",
    "openaccess.thecvf.com",
    "proceedings.mlr.press",
    "papers.neurips.cc",
    "neurips.cc",
    "icml.cc",
    "proceedings.iclr.cc",
    "ojs.aaai.org",
    "ecva.net",
    "ijcai.org",
    "papers.miccai.org",
    "jmlr.org",
    "research.google",
    "github.io",
    "uni-saarland.de",
    "uwaterloo.ca",
    "ohiolink.edu",
    "upv.es",
    "fas.harvard.edu",
    "link.springer.com",
    "dl.acm.org",
    "pmc.ncbi.nlm.nih.gov",
    "ieeexplore.ieee.org",
    "springer.com",
    "sciencedirect.com",
)
PUBLICATION_STATUSES = {
    "PUBLISHED",
    "PUBLISHED_WITH_PREPRINT_ALIAS",
    "ACCEPTED_NOT_PUBLISHED",
    "PREPRINT_ONLY",
    "SUBMISSION_ONLY",
    "FORMAL_NON_PEER_REVIEWED",
    "STATUS_UNVERIFIED",
}
QUALIFIED_PUBLICATION_STATUSES = {
    "PUBLISHED",
    "PUBLISHED_WITH_PREPRINT_ALIAS",
}
PEER_REVIEW_STATUSES = {
    "PEER_REVIEWED_PUBLISHED",
    "PEER_REVIEWED_ACCEPTED_NOT_PUBLISHED",
    "NON_PEER_REVIEWED",
    "PEER_REVIEW_STATUS_UNVERIFIED",
}

SCAN_SUFFIXES = {".md", ".json", ".txt", ".tex", ".bib"}
# 全树扫描防护上限：防止无界 rglob 卡死校验进程；超限报 INVALID 而非崩溃。
MAX_SCAN_DEPTH = 6
MAX_SCAN_FILES = 20000
DEFAULT_LEDGER_NAME = "near_neighbor_url_ledger.csv"


class RootOnlyContext:
    """无 workflow_state 时的独立运行兜底上下文（无跨校验器缓存）。

    与 ProjectContext 保持相同的 load_json/snapshot 接口，
    使 validate_with_context 在两种上下文下行为一致。
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.abspath(root))
        self.root_fd = open_root_fd(self.root)
        self.state: dict[str, Any] = {}

    def close(self) -> None:
        if self.root_fd is not None:
            os.close(self.root_fd)
            self.root_fd = None  # type: ignore[assignment]

    def __enter__(self) -> "RootOnlyContext":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def artifact_relative_path(self, key: str) -> str:
        return DEFAULT_ARTIFACT_PATHS[key]

    def load_json(self, relative_path: str, label: str = "json") -> dict[str, Any]:
        return read_json_object_at(self.root_fd, relative_path, label)

    def snapshot(self, relative_path: str, *, include_data: bool = False):
        return read_regular_file_at(
            self.root_fd, relative_path, include_data=include_data
        )


@dataclass
class RegistryFacts:
    """单次解析注册表得到的全部派生事实（消除二次 json.loads）。"""

    records: list[Any]
    registered_keys: set[str] = field(default_factory=set)
    owners: dict[str, str] = field(default_factory=dict)
    conflicts: list[tuple[str, str, str]] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)
    publication_errors: list[tuple[str, str]] = field(default_factory=list)
    actual_peer_reviewed_count: int = 0
    declared_peer_reviewed_count: Any = None
    search_mode: Any = None


@dataclass
class LiteratureReport:
    """_run 的完整结果：issues 之外还携带台账/汇总行所需数据。"""

    issues: list[Issue]
    facts: RegistryFacts
    rows: list[dict[str, object]]
    missing_keys: list[str]
    scan_path_errors: int


def clean_url(url: str) -> str:
    return url.rstrip(".,;:")


def canonical_url_key(url: str) -> str:
    """Normalize common paper aliases without discarding the original URL."""
    cleaned = clean_url(url)
    arxiv = ARXIV_RE.search(cleaned)
    if arxiv:
        return f"arxiv:{arxiv.group(1)}"
    parts = urlsplit(cleaned)
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    query = parts.query
    return urlunsplit(("https", host, path, query, ""))


def is_academic_url(url: str) -> bool:
    host = urlsplit(url).netloc.lower()
    return any(marker in host for marker in ACADEMIC_HOST_MARKERS)


def parse_registry(payload: dict[str, Any]) -> RegistryFacts:
    """从已解析的注册表 payload 提取事实；结构缺陷记 issue 而非 KeyError。"""

    facts = RegistryFacts(records=[])
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        facts.publication_errors.append(("__registry__", "records:missing_or_not_list"))
        raw_records = []
    facts.records = raw_records

    seen_ids: set[Any] = set()
    for record in raw_records:
        if not isinstance(record, dict):
            facts.publication_errors.append(("<record>", "record_not_object"))
            continue
        record_id = record.get("registry_id") or record.get("id")
        if isinstance(record_id, (list, dict, set)):
            facts.publication_errors.append(
                (str(record_id), "registry_id_not_scalar")
            )
            continue
        if record_id in seen_ids:
            facts.duplicate_ids.append(record_id)
        seen_ids.add(record_id)
        history = record.get("importance_history")
        if history is not None:
            if not isinstance(history, list) or not history or not all(
                isinstance(event, dict) for event in history
            ):
                facts.publication_errors.append(
                    (record_id, "invalid_importance_history")
                )
            elif record.get("importance") != history[-1].get("importance"):
                facts.publication_errors.append(
                    (record_id, "importance_history_mismatch")
                )
            else:
                downgrade = any(
                    prior.get("importance") in {"CRITICAL", "IMPORTANT"}
                    and current.get("importance") == "CONTEXT"
                    for prior, current in zip(history, history[1:])
                )
                download = record.get("download")
                download_status = (
                    download.get("status") if isinstance(download, dict) else None
                )
                if downgrade and download_status in {"DOWNLOAD_BLOCKED", "BLOCKED"}:
                    facts.publication_errors.append(
                        (record_id, "download_blocked_cannot_downgrade")
                    )
        publication_status = record.get("publication_status")
        eligibility = record.get("terminal_rejection_eligibility")
        verification_url = record.get("publication_verification_url")
        peer_review_status = record.get("peer_review_status")
        peer_review_verification_url = record.get("peer_review_verification_url")
        if publication_status not in PUBLICATION_STATUSES:
            facts.publication_errors.append(
                (record_id, f"invalid_or_missing_status:{publication_status}")
            )
        expected_eligibility = (
            "QUALIFIED"
            if publication_status in QUALIFIED_PUBLICATION_STATUSES
            else "NOT_QUALIFIED"
        )
        if eligibility != expected_eligibility:
            facts.publication_errors.append(
                (
                    record_id,
                    f"eligibility:{eligibility};expected:{expected_eligibility}",
                )
            )
        if expected_eligibility == "QUALIFIED" and not verification_url:
            facts.publication_errors.append(
                (record_id, "qualified_without_publication_verification_url")
            )
        if peer_review_status not in PEER_REVIEW_STATUSES:
            facts.publication_errors.append(
                (
                    record_id,
                    f"invalid_or_missing_peer_review_status:{peer_review_status}",
                )
            )
        if (
            peer_review_status == "PEER_REVIEWED_PUBLISHED"
            and not peer_review_verification_url
        ):
            facts.publication_errors.append(
                (record_id, "peer_reviewed_published_without_verification_url")
            )
        urls = [
            record.get("canonical_url") or record.get("url"),
            *(record.get("alternate_urls") or []),
        ]
        for url in filter(None, urls):
            if not isinstance(url, str):
                facts.publication_errors.append(
                    (record_id, f"invalid_url_entry:{url!r}")
                )
                continue
            key = canonical_url_key(url)
            if key in facts.owners and facts.owners[key] != record_id:
                facts.conflicts.append((key, facts.owners[key], record_id))
            facts.registered_keys.add(key)
            facts.owners[key] = record_id

    facts.actual_peer_reviewed_count = sum(
        isinstance(record, dict)
        and record.get("peer_review_status") == "PEER_REVIEWED_PUBLISHED"
        for record in raw_records
    )
    facts.declared_peer_reviewed_count = payload.get("peer_reviewed_published_count")
    facts.search_mode = payload.get("search_mode")
    return facts


def check_registry_counts(facts: RegistryFacts, payload: dict[str, Any]) -> None:
    """注册表级一致性检查；与逐条检查共用同一份 payload（单次解析）。"""

    if facts.declared_peer_reviewed_count != facts.actual_peer_reviewed_count:
        facts.publication_errors.append(
            (
                "__registry__",
                "peer_reviewed_published_count:"
                f"{facts.declared_peer_reviewed_count};actual:{facts.actual_peer_reviewed_count}",
            )
        )
    threshold = payload.get("synthesis_lock_threshold", 100)
    if isinstance(threshold, bool) or not isinstance(threshold, int):
        facts.publication_errors.append(
            ("__registry__", f"invalid_synthesis_lock_threshold:{threshold}")
        )
        threshold = 100
    allowed_modes = (
        {"SYNTHESIS_LOCK", "EXCEPTION_REOPEN"}
        if facts.actual_peer_reviewed_count >= threshold
        else {"SEARCH_OPEN"}
    )
    if facts.search_mode not in allowed_modes:
        facts.publication_errors.append(
            (
                "__registry__",
                f"search_mode:{facts.search_mode};allowed:{sorted(allowed_modes)}",
            )
        )


def scan(
    root_fd: int, ignored: set[str]
) -> tuple[list[dict[str, object]], list[Issue]]:
    """fd-based 全树扫描：O_NOFOLLOW 读文件，带深度/数量上限。

    文件符号链接一律不跟随（记 PATH_OUTSIDE_ROOT）；目录符号链接不下钻，
    与 Python 3.13 rglob 的默认行为一致。
    """

    rows: list[dict[str, object]] = []
    issues: list[Issue] = []
    files_seen = 0
    depth_exceeded = False
    truncated = False
    stack: list[tuple[str, int]] = [("", 0)]
    while stack and not truncated:
        relative_dir, depth = stack.pop()
        try:
            dir_fd = os.open(
                relative_dir or ".", secure_directory_flags(), dir_fd=root_fd
            )
        except OSError as error:
            issues.append(
                Issue(
                    "PATH_OUTSIDE_ROOT",
                    "INVALID",
                    relative_dir or ".",
                    f"directory_unreadable:{type(error).__name__}",
                )
            )
            continue
        try:
            entries = sorted(
                (
                    (
                        entry.name,
                        entry.is_symlink(),
                        entry.is_dir(follow_symlinks=False),
                        entry.is_file(follow_symlinks=False),
                    )
                    for entry in os.scandir(dir_fd)
                ),
                key=lambda item: item[0],
            )
        finally:
            os.close(dir_fd)
        for name, is_link, is_dir, is_file in entries:
            relative = f"{relative_dir}/{name}" if relative_dir else name
            if is_link:
                if is_dir:
                    continue  # 目录符号链接：不下钻
                issues.append(
                    Issue(
                        "PATH_OUTSIDE_ROOT",
                        "INVALID",
                        relative,
                        "symlink_not_followed",
                    )
                )
                continue
            if is_dir:
                if depth + 1 >= MAX_SCAN_DEPTH:
                    depth_exceeded = True
                    continue
                stack.append((relative, depth + 1))
                continue
            if not is_file:
                continue
            files_seen += 1
            if files_seen > MAX_SCAN_FILES:
                truncated = True
                break
            if relative in ignored:
                continue
            if Path(name).suffix.lower() not in SCAN_SUFFIXES:
                continue
            try:
                snapshot = read_regular_file_at(root_fd, relative, include_data=True)
            except FileNotFoundError:
                continue  # 扫描期间被并发删除：跳过而非报错
            except (OSError, UnsafePathError) as error:
                issues.append(
                    Issue("PATH_OUTSIDE_ROOT", "INVALID", relative, str(error))
                )
                continue
            assert snapshot.data is not None
            text = snapshot.data.decode("utf-8", errors="ignore")
            for line_no, line in enumerate(text.splitlines(), start=1):
                for match in URL_RE.finditer(line):
                    url = clean_url(match.group(0))
                    if not is_academic_url(url):
                        continue
                    rows.append(
                        {
                            "url": url,
                            "canonical_key": canonical_url_key(url),
                            "source_file": relative,
                            "line": line_no,
                        }
                    )
    if depth_exceeded:
        issues.append(
            Issue(
                "SCAN_LIMIT",
                "INVALID",
                "scan",
                f"max_depth_exceeded:{MAX_SCAN_DEPTH}",
            )
        )
    if truncated:
        issues.append(
            Issue(
                "SCAN_LIMIT",
                "INVALID",
                "scan",
                f"max_files_exceeded:{MAX_SCAN_FILES}",
            )
        )
    return rows, issues


def _run(
    ctx: ProjectContext, registry_relative: str, ledger_relative: str
) -> LiteratureReport:
    payload = ctx.load_json(registry_relative, "literature_registry")
    facts = parse_registry(payload)
    check_registry_counts(facts, payload)
    rows, scan_issues = scan(ctx.root_fd, {registry_relative, ledger_relative})
    missing = sorted(
        {str(row["canonical_key"]) for row in rows} - facts.registered_keys
    )

    issues: list[Issue] = []
    for key in missing:
        issues.append(Issue("UNREGISTERED", "INVALID", key, "url_not_in_registry"))
    for record_id in facts.duplicate_ids:
        issues.append(
            Issue("DUPLICATE_ID", "INVALID", str(record_id), "duplicate_registry_id")
        )
    for key, left, right in facts.conflicts:
        issues.append(
            Issue("URL_CONFLICT", "INVALID", key, f"owners:{left};also:{right}")
        )
    for record_id, error in facts.publication_errors:
        issues.append(Issue("PUBLICATION_ERROR", "INVALID", str(record_id), error))
    issues.extend(scan_issues)
    return LiteratureReport(
        issues=issues,
        facts=facts,
        rows=rows,
        missing_keys=missing,
        scan_path_errors=sum(1 for issue in scan_issues),
    )


def validate_with_context(
    ctx: ProjectContext,
    *,
    registry_path: str | None = None,
    ledger_path: str | None = None,
) -> list[Issue]:
    """库函数入口：注册表 JSON 经 ctx.load_json 共享解析（单次解析）。

    路径缺省时按 state artifacts / 默认文件名解析。
    """

    report = _run(
        ctx,
        registry_path or ctx.artifact_relative_path("literature_registry"),
        ledger_path or DEFAULT_LEDGER_NAME,
    )
    return report.issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument(
        "--ledger-output", type=Path, default=Path(DEFAULT_LEDGER_NAME)
    )
    parser.add_argument(
        "--state",
        type=Path,
        help="可选 workflow_state；提供时经 ProjectContext 共享解析缓存。",
    )
    ledger_mode = parser.add_mutually_exclusive_group()
    ledger_mode.add_argument(
        "--write-ledger",
        action="store_true",
        help="Explicitly create or replace the URL ledger.",
    )
    ledger_mode.add_argument(
        "--read-only",
        action="store_true",
        help="Compatibility flag; read-only is the default.",
    )
    args = parser.parse_args()

    root = Path(os.path.abspath(args.root))
    ledger = (
        args.ledger_output if args.ledger_output.is_absolute() else root / args.ledger_output
    )
    issues: list[Issue] = []
    report: LiteratureReport | None = None
    # 路径越界与旧版 print_path_error 等价：PATH_OUTSIDE_ROOT + exit 1。
    try:
        registry_relative = lexical_relative_cli_path(root, args.registry, "registry")
    except UnsafePathError as error:
        issues.append(Issue("PATH_OUTSIDE_ROOT", "INVALID", "registry", str(error)))
        registry_relative = ""
    if not issues:
        try:
            ledger_relative = lexical_relative_cli_path(root, ledger, "ledger")
        except UnsafePathError as error:
            issues.append(Issue("PATH_OUTSIDE_ROOT", "INVALID", "ledger", str(error)))
            ledger_relative = ""
    if not issues:
        try:
            state_path = args.state if args.state else root / "workflow_state.json"
            context: Any = (
                ProjectContext(root, state_path)
                if state_path.is_file()
                else RootOnlyContext(root)
            )
            with context as ctx:
                report = _run(ctx, registry_relative, ledger_relative)
            issues = report.issues
            if args.write_ledger and report.scan_path_errors == 0:
                ledger.parent.mkdir(parents=True, exist_ok=True)
                with ledger.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=[
                            "url",
                            "canonical_key",
                            "source_file",
                            "line",
                            "registry_id",
                            "registered",
                        ],
                    )
                    writer.writeheader()
                    for row in report.rows:
                        key = str(row["canonical_key"])
                        row["registry_id"] = report.facts.owners.get(key, "")
                        row["registered"] = (
                            "YES" if key in report.facts.registered_keys else "NO"
                        )
                        writer.writerow(row)
        except UnsafePathError as error:
            # 根目录/注册表本体不安全（如符号链接）：等价旧版 print_path_error。
            issues = [Issue("PATH_OUTSIDE_ROOT", "INVALID", "root", str(error))]
            report = None
        except Exception as error:
            # 任何未预期异常统一收敛为 VALIDATOR_ERROR（INVALID），不再 traceback。
            issues = [Issue("VALIDATOR_ERROR", "INVALID", "literature_registry", str(error))]
            report = None

    if report is not None:
        facts = report.facts
        print(f"academic_url_occurrences={len(report.rows)}")
        print(f"registered_url_keys={len(facts.registered_keys)}")
        print(f"unregistered_url_keys={len(report.missing_keys)}")
        print(f"duplicate_registry_ids={len(facts.duplicate_ids)}")
        print(f"cross_record_url_conflicts={len(facts.conflicts)}")
        print(f"publication_metadata_errors={len(facts.publication_errors)}")
        print(f"path_boundary_errors={report.scan_path_errors}")
        print(f"peer_reviewed_published_count={facts.actual_peer_reviewed_count}")
        print(f"search_mode={facts.search_mode}")
    print(render("literature_registry", issues))
    return int(choose_exit(issues))


if __name__ == "__main__":
    raise SystemExit(main())
