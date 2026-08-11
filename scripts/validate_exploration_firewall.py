#!/usr/bin/env python3
"""Exploration firewall: registered exploration numbers must not leak into frozen artifacts.

S0-SCREEN 之前的数值预实验是永久探索级证据（exploration_registry.json 登记）。
其显著数字 token 不得出现在任何冻结工件（根级 Markdown、claim 相关 JSON、
manuscript）中——即使注明"探索"也不行；冻结工件只允许定性转述。
有 E1/E2 出处的文献数字（near_neighbor_registry / literature_claim_registry
中出现的 token）豁免，因为它们有独立 provenance。
"""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import re
from typing import Any

from validation_common import (
    Issue,
    ProjectContext,
    UnsafePathError,
    canonical_relative_path,
    choose_exit,
    lexical_relative_cli_path,
    nonempty_string,
    render,
)


# 新增检查码：默认 WARNING（不计入退出码），--strict-new-checks 升为 INVALID。
NEW_CHECK_CODES = frozenset({"EXPLORATION_LEAK"})

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
# 显著数字 token：带小数点的数（可选符号/百分号），归一化后按有效位过滤。
NUMBER_PATTERN = re.compile(r"[-−–]?\d+\.\d+%?")
MIN_SIGNIFICANT_DIGITS = 3

# 文献 provenance 文件：其中出现的数字视为有出处，豁免防火墙。
PROVENANCE_KEYS = ("literature_registry", "claim_registry")
# 不作为冻结工件扫描的 artifacts 键（登记簿自身、日志、provenance 源）。
FROZEN_EXCLUDED_KEYS = {
    "exploration_registry",
    "validation_log",
    "literature_registry",
    "claim_registry",
}
# 根级 Markdown 中的例外：README 是仓库元信息，不是研究工件。
FROZEN_MARKDOWN_EXCLUDED = {"README.md"}

_UNICODE_MINUS = str.maketrans({"−": "-", "–": "-"})


def _valid_iso_utc(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def issue_severity(code: str, strict_new_checks: bool) -> str:
    if code in NEW_CHECK_CODES and not strict_new_checks:
        return "WARNING"
    return "INVALID"


def _numeric_tokens(text: str) -> set[str]:
    """提取显著数字 token（去符号、归一化 unicode 减号），有效位 >= 3。"""
    tokens: set[str] = set()
    for match in NUMBER_PATTERN.finditer(text.translate(_UNICODE_MINUS)):
        core = match.group(0).lstrip("-").rstrip("%")
        digits = re.sub(r"\D", "", core).lstrip("0")
        if len(digits) >= MIN_SIGNIFICANT_DIGITS:
            tokens.add(core)
    return tokens


def _frozen_artifact_paths(ctx: ProjectContext, exploration_paths: set[str]) -> list[str]:
    """冻结工件集合：state artifacts（除豁免键）+ 根级 Markdown（除例外）。"""
    frozen: set[str] = set()
    artifacts = ctx.state.get("artifacts")
    keys = set(DEFAULT_FROZEN_KEYS)
    if isinstance(artifacts, dict):
        keys |= {k for k in artifacts if isinstance(k, str)}
    for key in sorted(keys):
        if key in FROZEN_EXCLUDED_KEYS:
            continue
        try:
            relative = ctx.artifact_relative_path(key)
        except (KeyError, UnsafePathError):
            continue
        if relative in exploration_paths:
            continue
        frozen.add(relative)
    try:
        for entry in sorted(os.listdir(ctx.root)):
            if not entry.endswith(".md") or entry in FROZEN_MARKDOWN_EXCLUDED:
                continue
            if (ctx.root / entry).is_file() and entry not in exploration_paths:
                frozen.add(entry)
    except OSError:
        pass
    return sorted(frozen)


# 默认纳入冻结集合的 artifacts 键（存在才读）。
DEFAULT_FROZEN_KEYS = {
    "output_support",
    "claim_inventory",
    "theory_obligations",
    "protocol_contract",
    "baseline_budget",
    "claim_code_trace",
    "audit_manifest",
    "independent_audit",
    "frontier_coverage",
    "manuscript",
}


def _validate_registry_entries(
    ctx: ProjectContext, registry: dict[str, Any]
) -> tuple[list[Issue], list[dict[str, Any]]]:
    issues: list[Issue] = []
    if registry.get("schema_version") != "2.0":
        issues.append(
            Issue(
                "INVALID_EXPLORATION_REGISTRY_SCHEMA",
                "INVALID",
                "exploration_registry",
                f"schema_version:{registry.get('schema_version')}",
            )
        )
    entries = registry.get("explorations")
    if not isinstance(entries, list):
        issues.append(
            Issue(
                "INVALID_EXPLORATION_REGISTRY_SCHEMA",
                "INVALID",
                "exploration_registry",
                "explorations:missing_or_not_list",
            )
        )
        return issues, []
    valid: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, entry in enumerate(entries):
        item_id = f"exploration_registry.explorations[{index}]"
        if not isinstance(entry, dict):
            issues.append(
                Issue(
                    "INVALID_EXPLORATION_REGISTRY_SCHEMA",
                    "INVALID",
                    item_id,
                    "not_an_object",
                )
            )
            continue
        entry_id = entry.get("id")
        path = entry.get("path")
        digest = entry.get("sha256")
        ok = True
        if not nonempty_string(entry_id) or entry_id in seen_ids:
            issues.append(
                Issue(
                    "INVALID_EXPLORATION_REGISTRY_SCHEMA",
                    "INVALID",
                    item_id,
                    f"id:{entry_id}",
                )
            )
            ok = False
        else:
            seen_ids.add(entry_id)
        if not canonical_relative_path(path) or path in seen_paths:
            issues.append(
                Issue(
                    "INVALID_EXPLORATION_REGISTRY_SCHEMA",
                    "INVALID",
                    item_id,
                    f"path:{path}",
                )
            )
            ok = False
        else:
            seen_paths.add(path)
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            issues.append(
                Issue(
                    "INVALID_EXPLORATION_REGISTRY_SCHEMA",
                    "INVALID",
                    item_id,
                    f"sha256:{digest}",
                )
            )
            ok = False
        if not _valid_iso_utc(entry.get("registered_at")):
            issues.append(
                Issue(
                    "INVALID_EXPLORATION_REGISTRY_SCHEMA",
                    "INVALID",
                    item_id,
                    f"registered_at:{entry.get('registered_at')}",
                )
            )
            ok = False
        if entry.get("data_role") != "EXPLORATION_PERMANENT":
            issues.append(
                Issue(
                    "INVALID_EXPLORATION_REGISTRY_SCHEMA",
                    "INVALID",
                    item_id,
                    f"data_role:{entry.get('data_role')}",
                )
            )
            ok = False
        if not nonempty_string(entry.get("description")):
            issues.append(
                Issue(
                    "INVALID_EXPLORATION_REGISTRY_SCHEMA",
                    "INVALID",
                    item_id,
                    "description:missing",
                )
            )
            ok = False
        if ok:
            valid.append(entry)
    return issues, valid


def validate_with_context(
    ctx: ProjectContext,
    *,
    registry_path: str | None = None,
    strict_new_checks: bool = False,
) -> list[Issue]:
    """库入口：registry 缺省按 state["artifacts"] 解析；登记簿不存在则无义务。"""

    relative = registry_path or ctx.artifact_relative_path("exploration_registry")
    if not (ctx.root / relative).is_file():
        return []
    registry = ctx.load_json(relative, "exploration_registry")
    issues, entries = _validate_registry_entries(ctx, registry)

    exploration_paths = {entry["path"] for entry in entries}
    # 登记产物哈希核验：被改动后必须重新登记（iph register-exploration）。
    token_sources: dict[str, set[str]] = {}
    for entry in entries:
        try:
            snapshot = ctx.snapshot(entry["path"], include_data=True)
        except FileNotFoundError:
            issues.append(
                Issue(
                    "EXPLORATION_ARTIFACT_MISSING",
                    "INVALID",
                    entry["path"],
                    "registered_path_missing",
                )
            )
            continue
        except (OSError, UnsafePathError) as error:
            issues.append(
                Issue(
                    "EXPLORATION_ARTIFACT_MISSING",
                    "INVALID",
                    entry["path"],
                    str(error),
                )
            )
            continue
        if snapshot.sha256 != entry["sha256"]:
            issues.append(
                Issue(
                    "EXPLORATION_ARTIFACT_STALE",
                    "INVALID",
                    entry["path"],
                    f"declared:{entry['sha256']};current:{snapshot.sha256}",
                )
            )
            continue
        token_sources[entry["path"]] = _numeric_tokens(
            snapshot.data.decode("utf-8", errors="replace")
        )

    # provenance 豁免：文献注册表（E1/E2）中出现的数字有独立出处。
    exempt_tokens: set[str] = set()
    for key in PROVENANCE_KEYS:
        try:
            provenance_relative = ctx.artifact_relative_path(key)
        except (KeyError, UnsafePathError):
            continue
        try:
            snapshot = ctx.snapshot(provenance_relative, include_data=True)
        except (FileNotFoundError, OSError, UnsafePathError):
            continue
        exempt_tokens |= _numeric_tokens(
            snapshot.data.decode("utf-8", errors="replace")
        )

    frozen_texts: dict[str, str] = {}
    for frozen_relative in _frozen_artifact_paths(ctx, exploration_paths):
        try:
            snapshot = ctx.snapshot(frozen_relative, include_data=True)
        except (FileNotFoundError, OSError, UnsafePathError):
            continue
        frozen_texts[frozen_relative] = snapshot.data.decode(
            "utf-8", errors="replace"
        ).translate(_UNICODE_MINUS)

    severity = issue_severity("EXPLORATION_LEAK", strict_new_checks)
    for source_path, tokens in sorted(token_sources.items()):
        for token in sorted(tokens - exempt_tokens):
            for frozen_relative, text in sorted(frozen_texts.items()):
                if token in text:
                    issues.append(
                        Issue(
                            "EXPLORATION_LEAK",
                            severity,
                            source_path,
                            f"token:{token};frozen_artifact:{frozen_relative}",
                        )
                    )
    return issues


def validate(
    root_fd: int,  # noqa: ARG001 - 兼容旧 API 签名
    state: dict[str, Any],  # noqa: ARG001
    registry: dict[str, Any],  # noqa: ARG001
) -> list[Issue]:
    raise NotImplementedError("use validate_with_context(ctx)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--strict-new-checks", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(os.path.abspath(args.root))
    try:
        with ProjectContext(root, args.state) as ctx:
            registry_relative = None
            if args.registry is not None:
                registry_relative = lexical_relative_cli_path(
                    root, args.registry, "registry"
                )
            issues = validate_with_context(
                ctx,
                registry_path=registry_relative,
                strict_new_checks=args.strict_new_checks,
            )
    except Exception as error:
        detail = str(error).replace(f"{root}/", "")
        if detail.startswith("state:top_level_not_object"):
            detail = "workflow_state:" + detail[len("state:"):]
        issues = [Issue("VALIDATOR_ERROR", "INVALID", "exploration_firewall", detail)]

    print(render("exploration_firewall", issues, args.json))
    return int(choose_exit(issues))


if __name__ == "__main__":
    raise SystemExit(main())
