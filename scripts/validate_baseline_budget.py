#!/usr/bin/env python3
"""Validate fair-budget comparator coverage for algorithm claims.

只要 claim inventory 存在 ALGORITHM 类 claim（即 profile 为 ALGORITHM/MIXED 且
收集到 algorithm claims），baseline_budget.json 就必须存在且有效：不再依赖
manuscript/claim 文本里的 "strong baseline"/"公平比较" 等触发词。每个
comparator 必须用 claim_ids 绑定到至少一个 inventory 中的 algorithm claim，
且所有 algorithm claims 都必须被至少一个 comparator 覆盖。
"""

from __future__ import annotations

import argparse
from collections import Counter
import os
from pathlib import Path
from typing import Any

from validation_common import (
    Issue,
    ProjectContext,
    choose_exit,
    lexical_relative_cli_path,
    nonempty_string,
    positive_integer,
    render,
    string_list,
)
from validate_protocol_contract import (
    ALGORITHM_PROFILES,
    collect_algorithm_claims,
    load_object_via_ctx,
)


REQUIRED_COMPARATOR_FIELDS = (
    "width_or_parameter_budget",
    "seeds",
    "regularization_search_space",
    "tuning_data",
    "label_access",
    "update_frequency",
    "compute_budget",
    "stopping_rules",
)


def comparator_field_valid(field: str, value: Any) -> bool:
    if field == "seeds":
        return (
            isinstance(value, list)
            and bool(value)
            and all(not isinstance(seed, bool) and isinstance(seed, int) for seed in value)
            and len(set(value)) == len(value)
        )
    if field == "regularization_search_space":
        return (
            isinstance(value, list)
            and bool(value)
            and all(
                not isinstance(item, (dict, list, bool))
                and (isinstance(item, (int, float, str)))
                and (not isinstance(item, str) or bool(item.strip()))
                for item in value
            )
        )
    return nonempty_string(value)


def validate_baselines(
    baseline: dict[str, Any] | None,
    algorithm_claims: dict[str, dict[str, Any]],
    state_epoch: Any,
) -> list[Issue]:
    """baseline_budget 硬校验：对全部 algorithm claims 强制，无触发词门控。

    baseline 为 None（文件缺失）时按 claim 逐个报 BASELINE_BUDGET_INCOMPLETE；
    没有 algorithm claims 时无 comparator 义务。
    """

    if not algorithm_claims:
        return []
    if baseline is None:
        return [
            Issue(
                "BASELINE_BUDGET_INCOMPLETE",
                "INVALID",
                claim_id,
                "baseline_budget.json:missing",
            )
            for claim_id in sorted(algorithm_claims)
        ]
    issues: list[Issue] = []
    if baseline.get("schema_version") != "2.0":
        issues.append(
            Issue(
                "BASELINE_BUDGET_INCOMPLETE",
                "INVALID",
                "baseline_budget",
                f"schema_version:{baseline.get('schema_version')}",
            )
        )
    epoch = baseline.get("validation_epoch")
    if not positive_integer(epoch) or (
        positive_integer(state_epoch) and epoch != state_epoch
    ):
        issues.append(
            Issue(
                "BASELINE_BUDGET_INCOMPLETE",
                "INVALID",
                "baseline_budget",
                f"validation_epoch:{epoch};state:{state_epoch}",
            )
        )
    comparators = baseline.get("comparators")
    if not isinstance(comparators, list):
        return issues + [
            Issue(
                "BASELINE_BUDGET_INCOMPLETE",
                "INVALID",
                "baseline_budget",
                "comparators:expected_list",
            )
        ]
    covered: set[str] = set()
    comparator_ids: list[str] = []
    for index, comparator in enumerate(comparators):
        item_id = f"comparator[{index}]"
        if not isinstance(comparator, dict):
            issues.append(
                Issue(
                    "BASELINE_BUDGET_INCOMPLETE",
                    "INVALID",
                    item_id,
                    "expected_object",
                )
            )
            continue
        comparator_id = comparator.get("comparator_id")
        if not nonempty_string(comparator_id) or comparator_id.strip() != comparator_id:
            issues.append(
                Issue(
                    "BASELINE_BUDGET_INCOMPLETE",
                    "INVALID",
                    item_id,
                    "comparator_id:expected_canonical_nonempty_string",
                )
            )
        else:
            item_id = comparator_id
            comparator_ids.append(comparator_id)
        claim_ids = comparator.get("claim_ids")
        if not string_list(claim_ids) or len(set(claim_ids)) != len(claim_ids):
            issues.append(
                Issue(
                    "BASELINE_BUDGET_INCOMPLETE",
                    "INVALID",
                    item_id,
                    "claim_ids:expected_nonempty_unique_string_list",
                )
            )
        else:
            covered.update(claim_ids)
            # comparator 必须绑定到至少一个 inventory algorithm claim；
            # 否则它比较的不是任何登记算法，预算契约失去对象。
            if set(claim_ids).isdisjoint(algorithm_claims):
                issues.append(
                    Issue(
                        "BASELINE_BUDGET_INCOMPLETE",
                        "INVALID",
                        item_id,
                        "claim_ids:no_algorithm_claim_intersection",
                    )
                )
        # comparator 字段契约对全部 algorithm claims 强制（去 trigger 门控）。
        for field in REQUIRED_COMPARATOR_FIELDS:
            if field not in comparator or not comparator_field_valid(
                field, comparator.get(field)
            ):
                issues.append(
                    Issue(
                        "BASELINE_BUDGET_INCOMPLETE",
                        "INVALID",
                        item_id,
                        f"{field}:missing_or_invalid",
                    )
                )
    for comparator_id, count in Counter(comparator_ids).items():
        if count > 1:
            issues.append(
                Issue(
                    "BASELINE_BUDGET_INCOMPLETE",
                    "INVALID",
                    comparator_id,
                    f"duplicate_comparator_id:count:{count}",
                )
            )
    for claim_id in sorted(set(algorithm_claims) - covered):
        issues.append(
            Issue(
                "BASELINE_BUDGET_INCOMPLETE",
                "INVALID",
                claim_id,
                "no_comparator_covers_algorithm_claim",
            )
        )
    return issues


def validate_with_context(
    ctx: ProjectContext,
    *,
    inventory_path: str | None = None,
    baseline_budget: str | None = None,
) -> list[Issue]:
    """库入口：state 复用 ctx.state；inventory/baseline 经 ctx.load_json 缓存。

    各可选参数为 CLI 显式覆盖的相对路径；缺省按 state["artifacts"] 解析。
    baseline_budget.json 缺失时不作为加载错误，而是由 validate_baselines
    按 algorithm claim 逐个报 BASELINE_BUDGET_INCOMPLETE。
    """

    state = ctx.state
    issues: list[Issue] = []
    profile = state.get("claim_profile")
    if not isinstance(profile, str) or profile not in {
        "THEORY",
        "ALGORITHM",
        "MIXED",
    }:
        issues.append(
            Issue(
                "INVALID_CLAIM_PROFILE",
                "INVALID",
                "workflow_state",
                f"claim_profile:{profile}",
            )
        )
        return issues
    if profile not in ALGORITHM_PROFILES:
        return issues
    inventory_data, inventory_issues = load_object_via_ctx(
        ctx,
        inventory_path or ctx.artifact_relative_path("claim_inventory"),
        "claim_inventory",
    )
    baseline, baseline_issues = load_object_via_ctx(
        ctx,
        baseline_budget or ctx.artifact_relative_path("baseline_budget"),
        "baseline_budget",
        required=False,
    )
    issues.extend(inventory_issues + baseline_issues)
    if inventory_data is not None:
        algorithm_claims, claim_issues = collect_algorithm_claims(
            inventory_data, state.get("validation_epoch")
        )
        issues.extend(claim_issues)
        issues.extend(
            validate_baselines(
                baseline, algorithm_claims, state.get("validation_epoch")
            )
        )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--baseline-budget", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(os.path.abspath(args.root))
    try:
        with ProjectContext(root, args.state) as ctx:
            # 显式 CLI 覆盖：先做与其他校验器一致的词法校验，缺省则交由
            # validate_with_context 按 state["artifacts"] 解析。
            inventory_relative = (
                lexical_relative_cli_path(root, args.inventory, "inventory")
                if args.inventory is not None
                else None
            )
            baseline_relative = (
                lexical_relative_cli_path(root, args.baseline_budget, "baseline_budget")
                if args.baseline_budget is not None
                else None
            )
            issues = validate_with_context(
                ctx,
                inventory_path=inventory_relative,
                baseline_budget=baseline_relative,
            )
    except Exception as error:
        # ctx.load_json 的 os.stat 用绝对路径，OSError 文本需剥掉 root 前缀；
        # ctx 内部以 label "state" 抛 TypeError，历史输出用 "workflow_state"。
        detail = str(error).replace(f"{root}/", "")
        if detail.startswith("state:top_level_not_object"):
            detail = "workflow_state:" + detail[len("state:"):]
        issues = [Issue("VALIDATOR_ERROR", "INVALID", "baseline_budget", detail)]

    print(render("baseline_budget", issues, args.json))
    return int(choose_exit(issues))


if __name__ == "__main__":
    raise SystemExit(main())
