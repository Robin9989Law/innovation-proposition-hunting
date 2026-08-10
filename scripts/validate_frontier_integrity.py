#!/usr/bin/env python3
"""Validate frontier coverage, evidence kinds, and importance downgrades."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Any

from validation_common import (
    ExitCode,
    Issue,
    ProjectContext,
    StrictJSONError,
    UnsafePathError,
    choose_exit,
    lexical_relative_cli_path,
    nonempty_string,
    open_root_fd,
    read_json_object_at,
    render,
    string_list,
)


IMPORTANCE = frozenset({"CRITICAL", "IMPORTANT", "CONTEXT"})
HIGH_IMPORTANCE = frozenset({"CRITICAL", "IMPORTANT"})
ARTIFACT_KINDS = frozenset(
    {
        "OFFICIAL_METADATA",
        "OFFICIAL_ABSTRACT",
        "FULL_ARTICLE_HTML",
        "FULL_ARTICLE_PDF",
        "PROOF_OR_APPENDIX",
    }
)
FULL_ARTICLE_KINDS = frozenset({"FULL_ARTICLE_HTML", "FULL_ARTICLE_PDF"})
REQUIRED_AXES = (
    "method_synonyms",
    "target_tasks",
    "theory_terms",
    "algorithm_structures",
    "author_continuations",
    "backward_citations",
    "forward_citations",
)
SHA256_RE = re.compile(r"[0-9a-f]{64}")


def add(
    issues: list[Issue], code: str, item_id: str, detail: str, severity: str = "INVALID"
) -> None:
    issues.append(Issue(code, severity, item_id, detail))


def records(
    payload: dict[str, Any], artifact: str, issues: list[Issue]
) -> list[dict[str, Any]]:
    value = payload.get("records")
    if not isinstance(value, list):
        add(issues, "INVALID_RECORDS", artifact, "records_must_be_list")
        return []
    if not all(isinstance(item, dict) for item in value):
        add(issues, "INVALID_RECORDS", artifact, "record_must_be_object")
        return [item for item in value if isinstance(item, dict)]
    return value


def locator_present(value: Any) -> bool:
    if nonempty_string(value):
        return True
    if isinstance(value, dict):
        return bool(value) and all(nonempty_string(key) for key in value) and any(
            locator_present(child) for child in value.values()
        )
    if isinstance(value, list):
        return bool(value) and any(locator_present(child) for child in value)
    return False


def validate_evidence_records(
    payload: dict[str, Any], *, require_artifact_kind: bool = True
) -> tuple[list[Issue], dict[tuple[str, str], dict[str, Any]]]:
    issues: list[Issue] = []
    by_source_artifact: dict[tuple[str, str], dict[str, Any]] = {}
    seen_claim_ids: set[str] = set()
    for index, claim in enumerate(records(payload, "literature_claim_registry", issues)):
        claim_id = claim.get("claim_id")
        item_id = claim_id if nonempty_string(claim_id) else f"records[{index}]"
        if not nonempty_string(claim_id):
            add(issues, "INVALID_CLAIM_ID", item_id, "missing_claim_id")
        elif claim_id in seen_claim_ids:
            add(issues, "DUPLICATE_CLAIM_ID", item_id, "duplicate_claim_id")
        else:
            seen_claim_ids.add(claim_id)

        source_id = claim.get("source_registry_id")
        artifact_id = claim.get("source_artifact_id")
        if not nonempty_string(source_id):
            add(issues, "INVALID_SOURCE_ID", item_id, "missing_source_registry_id")
        if not nonempty_string(artifact_id):
            add(issues, "INVALID_ARTIFACT_ID", item_id, "missing_source_artifact_id")
        if nonempty_string(source_id) and nonempty_string(artifact_id):
            key = (source_id, artifact_id)
            if key in by_source_artifact:
                add(issues, "DUPLICATE_ARTIFACT_ID", item_id, artifact_id)
            else:
                by_source_artifact[key] = claim

        artifact_kind = claim.get("source_artifact_kind")
        if artifact_kind is None and not require_artifact_kind:
            continue
        if not isinstance(artifact_kind, str) or artifact_kind not in ARTIFACT_KINDS:
            add(
                issues,
                "INVALID_ARTIFACT_KIND",
                item_id,
                f"source_artifact_kind:{artifact_kind}",
            )
            continue

        evidence_level = claim.get("evidence_level")
        if evidence_level == "E2" and artifact_kind not in FULL_ARTICLE_KINDS:
            add(
                issues,
                "E2_REQUIRES_FULLTEXT",
                item_id,
                f"source_artifact_kind:{artifact_kind}",
            )
        if evidence_level == "E4" and not (
            artifact_kind == "PROOF_OR_APPENDIX"
            or (
                artifact_kind in FULL_ARTICLE_KINDS
                and locator_present(claim.get("proof_locator"))
            )
        ):
            add(
                issues,
                "E4_REQUIRES_PROOF",
                item_id,
                f"source_artifact_kind:{artifact_kind};missing_proof_locator",
            )
    return issues, by_source_artifact


def event_time(event: dict[str, Any]) -> Any:
    return event.get("at", event.get("recorded_at"))


def validate_reclassification(
    issues: list[Issue],
    work_id: str,
    prior: dict[str, Any],
    current: dict[str, Any],
    work: dict[str, Any],
    claim_artifacts: dict[tuple[str, str], dict[str, Any]],
    author_agent_ids: set[str],
) -> None:
    download = work.get("download")
    download_status = download.get("status") if isinstance(download, dict) else None
    if download_status in {"DOWNLOAD_BLOCKED", "BLOCKED"}:
        add(
            issues,
            "DOWNLOAD_BLOCKED_CANNOT_DOWNGRADE",
            work_id,
            f"download_status:{download_status}",
        )

    reclassifications = work.get("reclassifications")
    if not isinstance(reclassifications, list) or not all(
        isinstance(record, dict) for record in reclassifications
    ):
        add(
            issues,
            "UNJUSTIFIED_IMPORTANCE_DOWNGRADE",
            work_id,
            "missing_reclassification_record",
        )
        return
    matches = [
        record
        for record in reclassifications
        if record.get("from_importance") == prior.get("importance")
        and record.get("to_importance") == current.get("importance")
        and record.get("at") == event_time(current)
    ]
    if len(matches) != 1:
        add(
            issues,
            "UNJUSTIFIED_IMPORTANCE_DOWNGRADE",
            work_id,
            f"matching_reclassification_records:{len(matches)}",
        )
        return

    record = matches[0]
    artifact_id = record.get("fulltext_artifact_id")
    evidence_level = record.get("evidence_level")
    reviewer = record.get("reviewer_agent_id")
    thread = record.get("reviewer_thread_id")
    audited_hash = record.get("audited_artifact_sha256")
    failures: list[str] = []
    if not nonempty_string(artifact_id):
        failures.append("missing_fulltext_artifact_id")
    if evidence_level not in {"E2", "E4"}:
        failures.append(f"evidence_level:{evidence_level}")
    if not nonempty_string(reviewer):
        failures.append("missing_reviewer_agent_id")
    elif reviewer in author_agent_ids:
        failures.append("reviewer_not_independent")
    if not nonempty_string(thread):
        failures.append("missing_reviewer_thread_id")
    if not isinstance(audited_hash, str) or not SHA256_RE.fullmatch(audited_hash):
        failures.append("invalid_audited_artifact_sha256")

    claim = (
        claim_artifacts.get((work_id, artifact_id))
        if nonempty_string(artifact_id)
        else None
    )
    if claim is None:
        failures.append("fulltext_artifact_not_registered")
    elif claim.get("evidence_level") != evidence_level:
        failures.append("reclassification_evidence_level_mismatch")
    if failures:
        add(
            issues,
            "UNJUSTIFIED_IMPORTANCE_DOWNGRADE",
            work_id,
            ";".join(failures),
        )


def validate_importance_records(
    payload: dict[str, Any],
    claim_artifacts: dict[tuple[str, str], dict[str, Any]],
    author_agent_ids: set[str],
    *,
    require_history: bool = True,
) -> list[Issue]:
    issues: list[Issue] = []
    seen_ids: set[str] = set()
    for index, work in enumerate(records(payload, "near_neighbor_registry", issues)):
        registry_id = work.get("registry_id")
        work_id = registry_id if nonempty_string(registry_id) else f"records[{index}]"
        if not nonempty_string(registry_id):
            add(issues, "INVALID_REGISTRY_ID", work_id, "missing_registry_id")
        elif registry_id in seen_ids:
            add(issues, "DUPLICATE_REGISTRY_ID", work_id, "duplicate_registry_id")
        else:
            seen_ids.add(registry_id)
        if work.get("importance") not in IMPORTANCE:
            add(
                issues,
                "INVALID_IMPORTANCE",
                work_id,
                f"importance:{work.get('importance')}",
            )

        history = work.get("importance_history")
        if history is None and not require_history:
            continue
        if not isinstance(history, list) or not history or not all(
            isinstance(event, dict) for event in history
        ):
            add(issues, "INVALID_IMPORTANCE_HISTORY", work_id, "nonempty_object_list_required")
            continue
        previous_time: str | None = None
        history_valid = True
        for event_index, event in enumerate(history):
            importance = event.get("importance")
            at = event_time(event)
            if importance not in IMPORTANCE:
                add(
                    issues,
                    "INVALID_IMPORTANCE_HISTORY",
                    work_id,
                    f"event:{event_index};importance:{importance}",
                )
                history_valid = False
            if not nonempty_string(at) or not nonempty_string(event.get("reason")):
                add(
                    issues,
                    "INVALID_IMPORTANCE_HISTORY",
                    work_id,
                    f"event:{event_index};missing_at_or_reason",
                )
                history_valid = False
            elif previous_time is not None and at <= previous_time:
                add(
                    issues,
                    "IMPORTANCE_HISTORY_ORDER",
                    work_id,
                    f"event:{event_index};at:{at}",
                )
                history_valid = False
            if isinstance(at, str):
                previous_time = at
        if work.get("importance") != history[-1].get("importance"):
            add(
                issues,
                "IMPORTANCE_HISTORY_MISMATCH",
                work_id,
                f"current:{work.get('importance')};last:{history[-1].get('importance')}",
            )
        if not history_valid:
            continue
        for prior, current in zip(history, history[1:]):
            if (
                prior.get("importance") in HIGH_IMPORTANCE
                and current.get("importance") == "CONTEXT"
            ):
                validate_reclassification(
                    issues,
                    work_id,
                    prior,
                    current,
                    work,
                    claim_artifacts,
                    author_agent_ids,
                )
    return issues


def unavailable_capability(axis: Any) -> tuple[bool, str]:
    if not isinstance(axis, dict) or axis.get("status") != "BLOCKED":
        return False, ""
    capability = axis.get("capability")
    if not isinstance(capability, dict):
        return False, "missing_capability_object"
    name = capability.get("name")
    reason = capability.get("reason")
    if (
        not nonempty_string(name)
        or capability.get("available") is not False
        or not nonempty_string(reason)
    ):
        return False, "capability_requires_name_available_false_and_reason"
    return True, f"{name}:{reason}"


def validate_coverage(payload: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    if payload.get("schema_version") != "2.0":
        add(
            issues,
            "INVALID_FRONTIER_SCHEMA",
            "frontier_coverage",
            f"schema_version:{payload.get('schema_version')}",
        )
    axes = payload.get("axes")
    if not isinstance(axes, dict):
        add(issues, "INVALID_FRONTIER_AXES", "frontier_coverage", "axes_must_be_object")
        axes = {}
    for axis_name in REQUIRED_AXES:
        if axis_name not in axes:
            add(issues, "FRONTIER_AXIS_MISSING", axis_name, "axis_omitted")
            continue
        value = axes[axis_name]
        if string_list(value):
            continue
        unavailable, detail = unavailable_capability(value)
        if unavailable:
            add(
                issues,
                "FRONTIER_CAPABILITY_UNAVAILABLE",
                axis_name,
                detail,
                "BLOCKED",
            )
        else:
            add(
                issues,
                "FRONTIER_AXIS_INVALID",
                axis_name,
                detail or "nonempty_string_list_required",
            )

    routes = payload.get("routes")
    valid_independent: list[dict[str, Any]] = []
    blocked_route = False
    if not isinstance(routes, list):
        add(issues, "FRONTIER_ROUTES_INVALID", "routes", "routes_must_be_list")
        routes = []
    seen_route_ids: set[str] = set()
    for index, route in enumerate(routes):
        unavailable, detail = unavailable_capability(route)
        if unavailable:
            blocked_route = True
            add(
                issues,
                "FRONTIER_CAPABILITY_UNAVAILABLE",
                f"routes[{index}]",
                detail,
                "BLOCKED",
            )
            continue
        if not isinstance(route, dict):
            add(issues, "FRONTIER_ROUTE_INVALID", f"routes[{index}]", "must_be_object")
            continue
        route_id = route.get("route_id")
        if (
            not nonempty_string(route_id)
            or route_id in seen_route_ids
            or not nonempty_string(route.get("route_type"))
            or route.get("independent") is not True
            or not nonempty_string(route.get("details"))
        ):
            add(
                issues,
                "FRONTIER_ROUTE_INVALID",
                f"routes[{index}]",
                "unique_id_type_independent_true_and_details_required",
            )
            continue
        seen_route_ids.add(route_id)
        valid_independent.append(route)
    route_types = {route["route_type"] for route in valid_independent}
    if (len(valid_independent) < 2 or len(route_types) < 2) and not blocked_route:
        add(
            issues,
            "FRONTIER_ROUTES_INSUFFICIENT",
            "routes",
            f"independent_routes:{len(valid_independent)};route_types:{len(route_types)}",
        )
    return issues


def validate(
    state: dict[str, Any],
    literature: dict[str, Any],
    claims: dict[str, Any],
    coverage: dict[str, Any],
) -> list[Issue]:
    evidence_issues, claim_artifacts = validate_evidence_records(claims)
    audit = state.get("independent_audit")
    authors = audit.get("author_agent_ids") if isinstance(audit, dict) else []
    author_agent_ids = set(authors) if string_list(authors, allow_empty=True) else set()
    return [
        *evidence_issues,
        *validate_importance_records(literature, claim_artifacts, author_agent_ids),
        *validate_coverage(coverage),
    ]


def _state_label_detail(error: Exception) -> str:
    # ctx 内部以 label "state" 抛错；CLI 历史输出使用 "workflow_state"。
    detail = str(error)
    if detail.startswith("state:"):
        return "workflow_state:" + detail[len("state:"):]
    return detail


def _relative_error_detail(root: Path, error: Exception) -> str:
    # ctx.load_json 的 os.stat 使用绝对路径，OSError 文本含绝对路径；
    # 历史 CLI 以 dir_fd 相对打开，文本为相对路径。剥掉 root 前缀保持一致。
    return str(error).replace(f"{root}/", "")


def validate_with_context(
    ctx: ProjectContext, *, paths: dict[str, Path] | None = None
) -> list[Issue]:
    """库入口：复用 ctx 已解析的 state 与 strict JSON 缓存。

    paths 为调用方显式覆盖（label -> 路径，CLI 覆盖参数由此传入）；
    缺省按 state["artifacts"] 解析并回退默认文件名。逐文件做路径
    转换+读取，保持与原 CLI 完全一致的逐文件错误顺序。
    """

    issues: list[Issue] = []
    payloads: dict[str, dict[str, Any]] = {}
    artifact_keys = {
        "near_neighbor_registry": "literature_registry",
        "literature_claim_registry": "claim_registry",
        "frontier_coverage": "frontier_coverage",
    }
    overrides = paths or {}
    for label, key in artifact_keys.items():
        try:
            override = overrides.get(label)
            relative = (
                lexical_relative_cli_path(ctx.root, override, label)
                if override is not None
                else ctx.artifact_relative_path(key)
            )
            payloads[label] = ctx.load_json(relative, label)
        except StrictJSONError as error:
            add(issues, "STRICT_JSON", label, str(error))
        except (OSError, TypeError, UnsafePathError, ValueError) as error:
            add(
                issues,
                "UNSAFE_OR_MISSING_ARTIFACT",
                label,
                _relative_error_detail(ctx.root, error),
            )
    if issues:
        return issues
    return validate(
        ctx.state,
        payloads["near_neighbor_registry"],
        payloads["literature_claim_registry"],
        payloads["frontier_coverage"],
    )


def _collect_artifact_errors(root: Path, paths: dict[str, Path]) -> list[Issue]:
    # state 读取失败后的兼容回退：原 CLI 会继续逐个读取其余输入以聚合
    # 错误（不跑 validate）。root 此前已成功打开，此处失败则无新增可报告项。
    issues: list[Issue] = []
    root_fd: int | None = None
    try:
        root_fd = open_root_fd(root)
        for label, path in paths.items():
            try:
                relative = lexical_relative_cli_path(root, path, label)
                read_json_object_at(root_fd, relative, label)
            except StrictJSONError as error:
                add(issues, "STRICT_JSON", label, str(error))
            except (OSError, TypeError, UnsafePathError, ValueError) as error:
                add(issues, "UNSAFE_OR_MISSING_ARTIFACT", label, str(error))
    except (OSError, UnsafePathError, RuntimeError):
        pass
    finally:
        if root_fd is not None:
            os.close(root_fd)
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--literature-registry", type=Path)
    parser.add_argument("--claim-registry", type=Path)
    parser.add_argument("--frontier-coverage", type=Path)
    args = parser.parse_args()

    root = args.root.absolute()
    cli_paths = {
        "near_neighbor_registry": args.literature_registry
        or root / "near_neighbor_registry.json",
        "literature_claim_registry": args.claim_registry
        or root / "literature_claim_registry.json",
        "frontier_coverage": args.frontier_coverage or root / "frontier_coverage.json",
    }
    issues: list[Issue] = []
    ctx: ProjectContext | None = None
    root_failed = False
    try:
        ctx = ProjectContext(root, args.state)
    except StrictJSONError as error:
        add(issues, "STRICT_JSON", "workflow_state", str(error))
    except UnsafePathError as error:
        detail = _state_label_detail(error)
        if str(error).startswith("root:"):
            root_failed = True
            add(issues, "UNSAFE_PROJECT_ROOT", "root", detail)
        else:
            add(issues, "UNSAFE_OR_MISSING_ARTIFACT", "workflow_state", detail)
    except (OSError, RuntimeError) as error:
        if isinstance(error, OSError):
            # open_root_fd 内部已把 OSError 包成 UnsafePathError；裸 OSError
            # 只可能来自 state 文件读取（如 FileNotFoundError）。
            add(issues, "UNSAFE_OR_MISSING_ARTIFACT", "workflow_state", str(error))
        else:
            root_failed = True
            add(issues, "UNSAFE_PROJECT_ROOT", "root", str(error))
    except (TypeError, ValueError) as error:
        add(
            issues,
            "UNSAFE_OR_MISSING_ARTIFACT",
            "workflow_state",
            _state_label_detail(error),
        )

    if ctx is not None and not issues:
        with ctx:
            # 显式 CLI 覆盖参数优先；缺省保持固定的默认文件名（不读
            # state["artifacts"]），与历史 CLI 行为一致。
            issues.extend(validate_with_context(ctx, paths=cli_paths))
    elif ctx is None and not root_failed:
        issues.extend(_collect_artifact_errors(root, cli_paths))
    print(render("frontier_integrity", issues))
    return int(choose_exit(issues))


if __name__ == "__main__":
    raise SystemExit(main())
