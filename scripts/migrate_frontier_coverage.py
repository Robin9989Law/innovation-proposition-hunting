#!/usr/bin/env python3
"""把 frontier_coverage.json 的 legacy author_continuations 字符串条目迁移为实名格式。

背景（docs/design-schema-3.0.md §7、templates.md §7）：author_continuations 只收
作者续作边——每条边必须给出两端 work 的真实作者交集 shared_authors；legacy 字符串
条目无法核验交集，一律报 HOLLOW_COVERAGE_AXIS（WARNING，strict 升 INVALID）。
旧项目手工重做成本高，本脚本做保守的半自动迁移：

- 字符串条目按 "→" 切成链段，逐段在近邻注册表中匹配 work
  （作者姓氏词边界命中，且段内年份与 work.year 一致；段内无年份则只靠姓氏）。
- 仅当每段**恰好**匹配一个 work、且相邻 work 的作者交集全部非空时，才改写为
  {"edge": "A → B", "shared_authors": [...]}（逐相邻对一条边）。
- 任何一步核验不了（匹配 0 个、多个、交集为空），原字符串原样降级到可选轴
  method_lineage（去重）——引用链本来就该放那里，绝不编造作者交集。
- dict 条目（已是新格式）原样保留；capability BLOCKED 对象不处理。

迁移后若 author_continuations 为空，校验器会报 FRONTIER_AXIS_INVALID
（nonempty_list_required）——脚本不伪造续作边，需项目人工补真实核验过的边。

默认先写排他备份 frontier_coverage.json.legacy-backup-<timestamp> 再原子替换；
--dry-run 只打印计划不落盘。退出码：0 成功（含无可迁移内容），1 用法/读写错误。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import stat
import sys
import unicodedata
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from migrate_v1_to_v2 import (  # noqa: E402
    atomic_write_json,
    create_exclusive_backup,
    load_json,
    open_trusted_directory,
)

YEAR_RE = re.compile(r"(?:19|20)\d{2}")
MIN_SURNAME_LEN = 2


def normalize(text: Any) -> str:
    """NFKD 去变音符、小写，用于姓氏/年份的宽松匹配。"""

    decomposed = unicodedata.normalize("NFKD", str(text))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.lower()


def surname(author: Any) -> str:
    """取作者名最后一个空白分隔 token 作为姓氏；过短的返回空串（不参与匹配）。"""

    tokens = normalize(author).split()
    if not tokens:
        return ""
    name = tokens[-1]
    return name if len(name) >= MIN_SURNAME_LEN else ""


def segment_years(segment: str) -> set[str]:
    return set(YEAR_RE.findall(segment))


def match_segment(segment: str, works: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """段内命中的 work：姓氏词边界命中，且段内有年份时 work.year 必须落在其中。"""

    normalized = normalize(segment)
    years = segment_years(segment)
    matched: list[dict[str, Any]] = []
    for work in works:
        authors = work.get("authors")
        if not isinstance(authors, list):
            continue
        hit = any(
            re.search(rf"\b{re.escape(name)}\b", normalized)
            for name in (surname(author) for author in authors)
            if name
        )
        if not hit:
            continue
        if years:
            year = work.get("year")
            if year is None or str(year) not in years:
                continue
        matched.append(work)
    return matched


def author_intersection(
    first: dict[str, Any], second: dict[str, Any]
) -> list[str]:
    """两端作者的真实交集；输出保留 first 侧的原始写法。"""

    second_names = {normalize(a) for a in second.get("authors") or []}
    return [
        author
        for author in first.get("authors") or []
        if normalize(author) in second_names
    ]


def edge_label(work: dict[str, Any]) -> str:
    registry_id = work.get("registry_id")
    title = work.get("canonical_title")
    if isinstance(title, str) and title.strip():
        return f"{registry_id}（{title.strip()}）"
    return str(registry_id)


def migrate_payload(
    coverage: dict[str, Any], works: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[str], bool]:
    """返回 (新 coverage, 摘要行, 是否有改动)。不处理非列表/无字符串的情况。"""

    axes = coverage.get("axes")
    if not isinstance(axes, dict):
        return coverage, ["axes 缺失或非对象：无可迁移内容"], False
    value = axes.get("author_continuations")
    if not isinstance(value, list):
        return coverage, ["author_continuations 非列表（capability 对象？）：跳过"], False

    kept: list[Any] = []
    demoted: list[str] = []
    summary: list[str] = []
    changed = False
    for entry in value:
        if not isinstance(entry, str):
            kept.append(entry)
            continue
        segments = [part.strip() for part in entry.split("→") if part.strip()]
        chain = [match_segment(segment, works) for segment in segments]
        if len(segments) >= 2 and all(len(matches) == 1 for matches in chain):
            works_chain = [matches[0] for matches in chain]
            pairs = [
                (works_chain[index], works_chain[index + 1])
                for index in range(len(works_chain) - 1)
            ]
            intersections = [author_intersection(a, b) for a, b in pairs]
            if all(intersections):
                for (a, b), shared in zip(pairs, intersections):
                    kept.append(
                        {
                            "edge": f"{edge_label(a)} → {edge_label(b)}",
                            "shared_authors": shared,
                        }
                    )
                summary.append(
                    f"converted: {entry[:60]}… → {len(pairs)} 条实名边"
                    if len(entry) > 60
                    else f"converted: {entry} → {len(pairs)} 条实名边"
                )
                changed = True
                continue
        demoted.append(entry)
        summary.append(
            f"demoted: {entry[:60]}…（核验失败，转 method_lineage）"
            if len(entry) > 60
            else f"demoted: {entry}（核验失败，转 method_lineage）"
        )
        changed = True

    if not changed:
        return coverage, ["无 legacy 字符串条目：无需迁移"], False

    migrated = json.loads(json.dumps(coverage))
    migrated_axes = migrated["axes"]
    migrated_axes["author_continuations"] = kept
    lineage = migrated_axes.get("method_lineage")
    if not isinstance(lineage, list):
        lineage = []
    for entry in demoted:
        if entry not in lineage:
            lineage.append(entry)
    if lineage:
        migrated_axes["method_lineage"] = lineage
    if not kept:
        summary.append(
            "WARNING: 迁移后 author_continuations 为空——校验器将报 "
            "FRONTIER_AXIS_INVALID(nonempty_list_required)；请人工补真实核验过的续作边"
        )
    return migrated, summary, True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="项目根目录")
    parser.add_argument("--coverage", type=Path, default=None,
                        help="frontier_coverage.json 路径（默认 <root>/frontier_coverage.json）")
    parser.add_argument("--registry", type=Path, default=None,
                        help="near_neighbor_registry.json 路径（默认 <root>/near_neighbor_registry.json）")
    parser.add_argument("--dry-run", action="store_true", help="只打印迁移计划，不写盘")
    args = parser.parse_args()

    root = args.root.resolve()
    coverage_path = (args.coverage or root / "frontier_coverage.json").resolve()
    registry_path = (args.registry or root / "near_neighbor_registry.json").resolve()
    for label, path in (("coverage", coverage_path), ("registry", registry_path)):
        if not path.is_file():
            print(f"error: {label} 不存在：{path}", file=sys.stderr)
            return 1
        try:
            path.relative_to(root)
        except ValueError:
            print(f"error: {label} 必须位于项目根内：{path}", file=sys.stderr)
            return 1

    try:
        coverage = load_json(coverage_path)
        registry = load_json(registry_path)
    except (OSError, ValueError) as error:
        print(f"error: 读取失败：{error}", file=sys.stderr)
        return 1
    works = registry.get("works") or registry.get("records") or []
    works = [w for w in works if isinstance(w, dict)]

    migrated, summary, changed = migrate_payload(coverage, works)
    for line in summary:
        print(line)
    if not changed:
        return 0
    if args.dry_run:
        print("dry-run：未写盘")
        return 0

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_name = f"{coverage_path.name}.legacy-backup-{timestamp}"
    source_mode = stat.S_IMODE(coverage_path.stat().st_mode)
    with open_trusted_directory(root, coverage_path.parent, create=False) as dir_fd:
        create_exclusive_backup(dir_fd, coverage_path.name, backup_name, source_mode)
        atomic_write_json(dir_fd, coverage_path.name, migrated, source_mode)
    print(f"backup: {coverage_path.with_name(backup_name)}")
    print(f"migrated: {coverage_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
