#!/usr/bin/env python3
"""Validate literature identity, archived full text, atomic claims, and output traceability."""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from validation_common import (
    DEFAULT_ARTIFACT_PATHS,
    Issue,
    ProjectContext,
    UnsafePathError,
    canonical_relative_path,
    choose_exit,
    lexical_relative_cli_path,
    open_root_fd,
    read_json_object_at,
    read_regular_file_at,
    render,
)


IMPORTANCE = {"CRITICAL", "IMPORTANT", "CONTEXT"}
ARCHIVED = {"FULLTEXT_ARCHIVED", "OFFICIAL_HTML_ARCHIVED"}
SEARCH_PHASES = {"RECENT_FRONTIER_PASS", "FOUNDATIONAL_BACKFILL"}
CLAIM_TYPES = {
    "OCCUPIES",
    "ENABLES",
    "CONTRADICTS",
    "BOUNDS",
    "NEUTRAL",
}
# 负面判断（反对/限定候选）：可作 counter，不可作 support。
NEGATIVE_CLAIM_TYPES = {"OCCUPIES", "CONTRADICTS", "BOUNDS"}
EVIDENCE_LEVELS = {"E0", "E1", "E2", "E3", "E4"}
ARTIFACT_KINDS = {
    "OFFICIAL_METADATA",
    "OFFICIAL_ABSTRACT",
    "FULL_ARTICLE_HTML",
    "FULL_ARTICLE_PDF",
    "PROOF_OR_APPENDIX",
}
FULL_ARTICLE_KINDS = {"FULL_ARTICLE_HTML", "FULL_ARTICLE_PDF"}
VERIFIED_CLAIM_STATUSES = {"VERIFIED_FULLTEXT", "VERIFIED_OFFICIAL_HTML"}
USE_STATUSES = {"UNUSED", "USED", "EXCLUDED_WITH_REASON"}
OUTPUT_KINDS = {
    "FACT",
    "SYNTHESIS",
    "METHOD_COMPARISON",
    "NOVELTY_VERDICT",
    "CLOSURE",
    "PROPOSITION_RATIONALE",
}
INFERENCE_TYPES = {"DIRECT", "SYNTHESIS", "CONTRAST", "INFERENCE"}

# 碰撞类结论（R-REVIEW-20）：这些 claim_kind 是"裁决/关闭/比较"，必须带
# evidence 数值锚点或 locator，否则是走形式的碰撞（ATOMIC_COLLISION_NO_ANCHOR）。
COLLISION_KINDS = {"NOVELTY_VERDICT", "CLOSURE", "METHOD_COMPARISON"}
# 数值锚点：小数、百分比、pp 点，或 locator 字段里的表/图/定理/算法号。
NUMERIC_ANCHOR = re.compile(r"\d+\.\d+|\d+\s*%|\d+\s*pp", re.IGNORECASE)
LOCATOR_KEYS = ("table", "figure", "theorem", "algorithm", "lemma", "corollary")
# L1/L2 的分段证据约束：此时注册表负责保存身份与风险分级，不能反过来要求
# 尚未被选入 K 集合的高风险条目已经完成全文归档和原子观点。无 state 的独立
# 校验入口保留历史严格行为；L3（含 K_FULLTEXT）恢复完整硬约束。
PRE_K_STATES = {
    "BOOT",
    "SCOPE_LOCK",
    "PRIOR_CLAIM_DRAIN",
    "RECENT_FRONTIER",
    "LITERATURE_REGISTER",
    "L1_FREEZE",
    "L2_TRIAGE",
    "LAYER_DECISION",
}


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


def add(issues: list[Issue], code: str, item_id: str, detail: str) -> None:
    issues.append(Issue(code, "INVALID", item_id, detail))


def records(
    payload: dict[str, Any],
    issues: list[Issue],
    *,
    field: str = "records",
    item_id: str = "__registry__",
) -> list[dict[str, Any]]:
    # 结构错误记为 INVALID issue，不再让 ValueError 崩出 main。
    value = payload.get(field)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        add(issues, "INVALID_RECORDS", item_id, f"{field}:missing_or_not_list")
        return []
    return value


def nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    return value is not None


def valid_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parts = urlsplit(value.strip())
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def requires_fulltext_claims(ctx: ProjectContext) -> bool:
    """仅在 L3 才要求重要文献完成归档和原子观点。

    这与状态机的 L1 元数据、L2 试读、L3 K 集合重证据分工一致。直接调用
    校验器而没有 workflow_state 时，采取保守的严格校验。
    """

    if not ctx.state:
        return True
    return ctx.effective_state() not in PRE_K_STATES


def requires_atomic_claims(ctx: ProjectContext) -> bool:
    """K_FULLTEXT 只验归档；原子观点从 K_CLAIM_REGISTER 才成为硬约束。"""

    if not ctx.state:
        return True
    return ctx.effective_state() not in (PRE_K_STATES | {"K_FULLTEXT"})


def selected_k_work_ids(ctx: ProjectContext, issues: list[Issue]) -> set[str] | None:
    """L3 只对 current_evidence_scope 明列的 K 文献强制深证据。

    ``None`` 表示旧项目或独立调用未提供 scope，保持全部重要文献的保守历史行为。
    损坏的 scope 不能静默放宽，直接记为 INVALID。
    """

    if not ctx.state:
        return None
    artifacts = ctx.state.get("artifacts")
    raw_scope = artifacts.get("current_evidence_scope") if isinstance(artifacts, dict) else None
    if not isinstance(raw_scope, str) or not canonical_relative_path(raw_scope):
        return None
    try:
        scope = ctx.load_json(raw_scope, "current_evidence_scope")
    except Exception as error:
        add(issues, "CURRENT_EVIDENCE_SCOPE", "__scope__", f"unreadable:{error}")
        return set()
    selected = scope.get("fulltext_registry_ids")
    if not isinstance(selected, list) or not all(nonempty(item) for item in selected):
        add(issues, "CURRENT_EVIDENCE_SCOPE", "__scope__", "fulltext_registry_ids:invalid")
        return set()
    if len(selected) != len(set(selected)):
        add(issues, "CURRENT_EVIDENCE_SCOPE", "__scope__", "fulltext_registry_ids:duplicate")
    return {str(item) for item in selected}


def validate(
    ctx: ProjectContext,
    literature: dict[str, Any],
    claims: dict[str, Any],
    outputs: dict[str, Any],
    current_year: int,
) -> list[Issue]:
    issues: list[Issue] = []
    enforce_fulltext_claims = requires_fulltext_claims(ctx)
    enforce_atomic_claims = requires_atomic_claims(ctx)
    selected_work_ids = selected_k_work_ids(ctx, issues) if enforce_fulltext_claims else set()
    works = records(literature, issues)
    claim_records = records(claims, issues)
    output_records = records(outputs, issues, field="output_claims", item_id="__output__")

    window = literature.get("recent_window")
    if not isinstance(window, dict):
        add(issues, "RECENT_WINDOW", "__registry__", "missing_recent_window")
        window = {}
    expected_start = current_year - 2
    if literature.get("current_year") != current_year:
        add(
            issues,
            "RECENT_WINDOW",
            "__registry__",
            f"current_year:{literature.get('current_year')};expected:{current_year}",
        )
    if window.get("start_year") != expected_start or window.get("end_year") != current_year:
        add(
            issues,
            "RECENT_WINDOW",
            "__registry__",
            f"window:{window.get('start_year')}-{window.get('end_year')};expected:{expected_start}-{current_year}",
        )
    if window.get("status") != "COMPLETE":
        add(issues, "RECENT_WINDOW", "__registry__", "status_not_complete")
    if not nonempty(window.get("completed_at")):
        add(issues, "RECENT_WINDOW", "__registry__", "missing_completed_at")
    if not nonempty(window.get("queries")):
        add(issues, "RECENT_WINDOW", "__registry__", "missing_queries")

    rounds = {
        literature.get("current_collision_round"),
        claims.get("current_collision_round"),
        outputs.get("current_collision_round"),
    }
    if len(rounds) != 1 or not all(isinstance(value, int) and value >= 1 for value in rounds):
        add(issues, "ROUND", "__registry__", f"inconsistent_rounds:{sorted(map(str, rounds))}")
        current_round = 1
    else:
        current_round = next(iter(rounds))

    work_by_id: dict[str, dict[str, Any]] = {}
    for work in works:
        work_id = work.get("registry_id")
        if not nonempty(work_id):
            add(issues, "WORK", "<missing>", "missing_registry_id")
            continue
        if work_id in work_by_id:
            add(issues, "WORK", str(work_id), "duplicate_registry_id")
            continue
        work_by_id[str(work_id)] = work
        for field in ("canonical_title", "authors", "year", "identity_verification_url", "identity_verified_at"):
            if not nonempty(work.get(field)):
                add(issues, "IDENTITY", str(work_id), f"missing:{field}")
        if not isinstance(work.get("canonical_title"), str):
            add(issues, "IDENTITY", str(work_id), "canonical_title_not_string")
        authors = work.get("authors")
        if not isinstance(authors, list) or not authors or not all(nonempty(author) for author in authors):
            add(issues, "IDENTITY", str(work_id), "authors_not_nonempty_list")
        if work.get("identity_status") != "VERIFIED":
            add(issues, "IDENTITY", str(work_id), f"status:{work.get('identity_status')}")
        if not valid_http_url(work.get("identity_verification_url")):
            add(issues, "IDENTITY", str(work_id), "invalid_identity_verification_url")
        year = work.get("year")
        if not isinstance(year, int) or year > current_year:
            add(issues, "WORK", str(work_id), f"invalid_year:{year}")
        phase = work.get("search_phase")
        if phase not in SEARCH_PHASES:
            add(issues, "WORK", str(work_id), f"invalid_search_phase:{phase}")
        elif isinstance(year, int):
            expected_phase = (
                "RECENT_FRONTIER_PASS"
                if expected_start <= year <= current_year
                else "FOUNDATIONAL_BACKFILL"
            )
            if phase != expected_phase:
                add(issues, "WORK", str(work_id), f"search_phase:{phase};expected:{expected_phase}")
        importance = work.get("importance")
        if importance not in IMPORTANCE:
            add(issues, "WORK", str(work_id), f"invalid_importance:{importance}")
        download = work.get("download")
        if not isinstance(download, dict):
            add(issues, "DOWNLOAD", str(work_id), "missing_download_object")
            download = {}
        selected_for_deep_check = (
            importance in {"CRITICAL", "IMPORTANT"}
            and enforce_fulltext_claims
            and (selected_work_ids is None or str(work_id) in selected_work_ids)
        )
        if selected_for_deep_check:
            status = download.get("status")
            if status not in ARCHIVED:
                add(issues, "DOWNLOAD", str(work_id), f"important_not_archived:{status}")
            if not valid_http_url(download.get("source_url")):
                add(issues, "DOWNLOAD", str(work_id), "invalid_or_missing_source_url")
            if not nonempty(download.get("downloaded_at")):
                add(issues, "DOWNLOAD", str(work_id), "missing_downloaded_at")
            if download.get("verified_against_metadata") is not True:
                add(issues, "DOWNLOAD", str(work_id), "metadata_match_not_verified")
            # 本地下载件走 fd-based O_NOFOLLOW 读取，杜绝符号链接 TOCTOU。
            raw_path = download.get("local_path")
            if not isinstance(raw_path, str) or not canonical_relative_path(raw_path):
                add(issues, "DOWNLOAD", str(work_id), "invalid_or_missing_local_path")
            else:
                try:
                    snapshot = ctx.snapshot(raw_path)
                except FileNotFoundError:
                    add(
                        issues,
                        "DOWNLOAD",
                        str(work_id),
                        f"file_not_found:{ctx.root / raw_path}",
                    )
                except (OSError, UnsafePathError) as error:
                    add(issues, "DOWNLOAD", str(work_id), f"unsafe_local_path:{error}")
                else:
                    declared_hash = str(download.get("sha256") or "").lower()
                    if declared_hash != snapshot.sha256:
                        add(issues, "DOWNLOAD", str(work_id), "sha256_mismatch")
            if enforce_atomic_claims and work.get("claim_extraction_status") != "COMPLETE":
                add(issues, "CLAIM_EXTRACTION", str(work_id), "important_claims_not_complete")

    claim_by_id: dict[str, dict[str, Any]] = {}
    claims_by_work: dict[str, list[str]] = {}
    for claim in claim_records:
        claim_id = claim.get("claim_id")
        if not nonempty(claim_id):
            add(issues, "CLAIM", "<missing>", "missing_claim_id")
            continue
        claim_id = str(claim_id)
        if claim_id in claim_by_id:
            add(issues, "CLAIM", claim_id, "duplicate_claim_id")
            continue
        claim_by_id[claim_id] = claim
        source_id = str(claim.get("source_registry_id") or "")
        if source_id not in work_by_id:
            add(issues, "CLAIM", claim_id, f"unknown_source:{source_id}")
        else:
            claims_by_work.setdefault(source_id, []).append(claim_id)
        if claim.get("claim_type") not in CLAIM_TYPES:
            add(issues, "CLAIM", claim_id, f"invalid_type:{claim.get('claim_type')}")
        if not nonempty(claim.get("normalized_statement")):
            add(issues, "CLAIM", claim_id, "missing_normalized_statement")
        if not nonempty(claim.get("scope")):
            add(issues, "CLAIM", claim_id, "missing_scope")
        if not isinstance(claim.get("conditions"), list):
            add(issues, "CLAIM", claim_id, "conditions_not_list")
        if claim.get("evidence_level") not in EVIDENCE_LEVELS:
            add(issues, "CLAIM", claim_id, f"invalid_evidence_level:{claim.get('evidence_level')}")
        elif claim.get("evidence_level") not in {"E2", "E3", "E4"}:
            add(issues, "CLAIM", claim_id, f"important_claim_below_E2:{claim.get('evidence_level')}")
        artifact_kind = claim.get("source_artifact_kind")
        if artifact_kind is not None:
            if artifact_kind not in ARTIFACT_KINDS:
                add(issues, "INVALID_ARTIFACT_KIND", claim_id, f"source_artifact_kind:{artifact_kind}")
            elif claim.get("evidence_level") == "E2" and artifact_kind not in FULL_ARTICLE_KINDS:
                add(issues, "E2_REQUIRES_FULLTEXT", claim_id, f"source_artifact_kind:{artifact_kind}")
            elif claim.get("evidence_level") == "E4" and not (
                artifact_kind == "PROOF_OR_APPENDIX"
                or (
                    artifact_kind in FULL_ARTICLE_KINDS
                    and nonempty(claim.get("proof_locator"))
                )
            ):
                add(issues, "E4_REQUIRES_PROOF", claim_id, f"source_artifact_kind:{artifact_kind}")
        if claim.get("verification_status") not in VERIFIED_CLAIM_STATUSES:
            add(issues, "CLAIM", claim_id, f"not_fulltext_verified:{claim.get('verification_status')}")
        locator = claim.get("locator")
        if not isinstance(locator, dict) or not any(nonempty(value) for value in locator.values()):
            add(issues, "TRACE", claim_id, "missing_locator")
        if claim.get("importance") not in {"CRITICAL", "IMPORTANT"}:
            add(issues, "CLAIM", claim_id, f"invalid_importance:{claim.get('importance')}")
        discovered_round = claim.get("discovered_round")
        if not isinstance(discovered_round, int) or discovered_round < 1 or discovered_round > current_round:
            add(issues, "ROUND", claim_id, f"invalid_discovered_round:{discovered_round}")
        use_status = claim.get("use_status")
        if use_status not in USE_STATUSES:
            add(issues, "USAGE", claim_id, f"invalid_use_status:{use_status}")
        output_uses = claim.get("used_by_output_claim_ids") or []
        collision_uses = claim.get("used_in_collision_ids") or []
        if not isinstance(output_uses, list):
            add(issues, "USAGE", claim_id, "used_by_output_claim_ids_not_list")
            output_uses = []
        if not isinstance(collision_uses, list):
            add(issues, "USAGE", claim_id, "used_in_collision_ids_not_list")
            collision_uses = []
        if use_status == "USED" and not output_uses and not collision_uses:
            add(issues, "USAGE", claim_id, "used_without_target")
        if use_status == "EXCLUDED_WITH_REASON" and not nonempty(claim.get("exclusion_reason")):
            add(issues, "USAGE", claim_id, "excluded_without_reason")

    for work_id, work in work_by_id.items():
        if (
            enforce_atomic_claims
            and work.get("importance") in {"CRITICAL", "IMPORTANT"}
            and (selected_work_ids is None or work_id in selected_work_ids)
            and not claims_by_work.get(work_id)
        ):
            add(issues, "CLAIM_EXTRACTION", work_id, "important_work_without_claims")

    output_by_id: dict[str, dict[str, Any]] = {}
    referenced_claims: set[str] = set()
    for output in output_records:
        output_id = output.get("output_claim_id")
        if not nonempty(output_id):
            add(issues, "OUTPUT", "<missing>", "missing_output_claim_id")
            continue
        output_id = str(output_id)
        if output_id in output_by_id:
            add(issues, "OUTPUT", output_id, "duplicate_output_claim_id")
            continue
        output_by_id[output_id] = output
        if not nonempty(output.get("statement")):
            add(issues, "OUTPUT", output_id, "missing_statement")
        if not nonempty(output.get("output_location")):
            add(issues, "OUTPUT", output_id, "missing_output_location")
        if output.get("claim_kind") not in OUTPUT_KINDS:
            add(issues, "OUTPUT", output_id, f"invalid_claim_kind:{output.get('claim_kind')}")
        inference_type = output.get("inference_type")
        if inference_type not in INFERENCE_TYPES:
            add(issues, "OUTPUT", output_id, f"invalid_inference_type:{inference_type}")
        if inference_type in {"SYNTHESIS", "CONTRAST", "INFERENCE"} and not nonempty(output.get("reasoning")):
            add(issues, "OUTPUT", output_id, "inference_without_reasoning")
        # R-REVIEW-20：碰撞类结论三段式，evidence 必须含数值锚点或 locator。
        if output.get("claim_kind") in COLLISION_KINDS:
            evidence = output.get("evidence")
            if not nonempty(evidence):
                add(issues, "ATOMIC_COLLISION_NO_ANCHOR", output_id, "evidence:missing_or_empty")
            elif not NUMERIC_ANCHOR.search(evidence):
                add(issues, "ATOMIC_COLLISION_NO_ANCHOR", output_id, "evidence:no_numeric_anchor_or_locator")
        supporting = output.get("supporting_claim_ids")
        if not isinstance(supporting, list) or not supporting:
            add(issues, "OUTPUT", output_id, "no_supporting_claim_ids")
            supporting = []
        counters = output.get("counter_claim_ids") or []
        if not isinstance(counters, list):
            add(issues, "OUTPUT", output_id, "counter_claim_ids_not_list")
            counters = []
        for claim_id in [*supporting, *counters]:
            if claim_id not in claim_by_id:
                add(issues, "TRACE", output_id, f"unknown_claim:{claim_id}")
                continue
            referenced_claims.add(str(claim_id))
            claim = claim_by_id[str(claim_id)]
            source_id = str(claim.get("source_registry_id") or "")
            work = work_by_id.get(source_id, {})
            if work.get("importance") not in {"CRITICAL", "IMPORTANT"}:
                add(issues, "TRACE", output_id, f"claim_from_nonimportant_work:{claim_id}")
            if claim.get("verification_status") not in VERIFIED_CLAIM_STATUSES:
                add(issues, "TRACE", output_id, f"unverified_claim:{claim_id}")
            if claim_id in supporting and claim.get("claim_type") in NEGATIVE_CLAIM_TYPES:
                add(issues, "TRACE", output_id, f"negative_claim_used_as_support:{claim_id}")
            if claim_id in counters and claim.get("claim_type") not in NEGATIVE_CLAIM_TYPES:
                add(issues, "TRACE", output_id, f"nonnegative_claim_used_as_counter:{claim_id}")
            if claim.get("use_status") != "USED":
                add(issues, "USAGE", str(claim_id), f"referenced_but_status:{claim.get('use_status')}")
            if output_id not in (claim.get("used_by_output_claim_ids") or []):
                add(issues, "TRACE", output_id, f"missing_reverse_link:{claim_id}")
        if output.get("trace_status") != "VERIFIED":
            add(issues, "TRACE", output_id, f"trace_status:{output.get('trace_status')}")

    for claim_id, claim in claim_by_id.items():
        for output_id in claim.get("used_by_output_claim_ids") or []:
            if output_id not in output_by_id:
                add(issues, "TRACE", claim_id, f"unknown_output_reverse_link:{output_id}")
            elif claim_id not in (output_by_id[output_id].get("supporting_claim_ids") or []) and claim_id not in (
                output_by_id[output_id].get("counter_claim_ids") or []
            ):
                add(issues, "TRACE", claim_id, f"one_way_output_link:{output_id}")

    unused_prior = sorted(
        claim_id
        for claim_id, claim in claim_by_id.items()
        if isinstance(claim.get("discovered_round"), int)
        and claim["discovered_round"] < current_round
        and claim.get("use_status") == "UNUSED"
    )
    gate = outputs.get("collision_gate")
    if not isinstance(gate, dict):
        add(issues, "COLLISION_GATE", "__output__", "missing_collision_gate")
        gate = {}
    if unused_prior:
        add(issues, "COLLISION_GATE", "__output__", f"unused_prior_claims:{','.join(unused_prior)}")
    expected_drained = not unused_prior
    if gate.get("prior_round_claims_drained") is not expected_drained:
        add(issues, "COLLISION_GATE", "__output__", f"drained_flag_should_be:{expected_drained}")
    declared_unused = sorted(gate.get("unused_prior_claim_ids") or [])
    if declared_unused != unused_prior:
        add(issues, "COLLISION_GATE", "__output__", f"unused_list:{declared_unused};actual:{unused_prior}")
    if not nonempty(gate.get("checked_at")):
        add(issues, "COLLISION_GATE", "__output__", "missing_checked_at")

    return issues


def validate_with_context(
    ctx: ProjectContext,
    *,
    literature_path: str | None = None,
    claim_path: str | None = None,
    output_path: str | None = None,
    current_year: int | None = None,
) -> list[Issue]:
    """库函数入口：注册表 JSON 经 ctx.load_json 共享解析，文件哈希经 ctx.snapshot。

    路径缺省时按 state artifacts / 默认文件名解析；年份缺省时取
    state.current_year，再退化到当前日历年。
    """

    literature = ctx.load_json(
        literature_path or ctx.artifact_relative_path("literature_registry"),
        "literature_registry",
    )
    claims = ctx.load_json(
        claim_path or ctx.artifact_relative_path("claim_registry"),
        "claim_registry",
    )
    outputs = ctx.load_json(
        output_path or ctx.artifact_relative_path("output_support"),
        "output_support",
    )
    if current_year is None:
        state_year = ctx.state.get("current_year")
        current_year = (
            state_year if isinstance(state_year, int) else datetime.now().year
        )
    return validate(ctx, literature, claims, outputs, current_year)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--literature-registry", type=Path, required=True)
    parser.add_argument("--claim-registry", type=Path, required=True)
    parser.add_argument("--output-support", type=Path, required=True)
    parser.add_argument("--current-year", type=int, default=datetime.now().year)
    parser.add_argument(
        "--state",
        type=Path,
        help="可选 workflow_state；提供时经 ProjectContext 共享解析缓存。",
    )
    args = parser.parse_args()

    root = Path(os.path.abspath(args.root))
    issues: list[Issue]
    try:
        literature_relative = lexical_relative_cli_path(
            root, args.literature_registry, "literature_registry"
        )
        claims_relative = lexical_relative_cli_path(
            root, args.claim_registry, "claim_registry"
        )
        outputs_relative = lexical_relative_cli_path(
            root, args.output_support, "output_support"
        )
        state_path = args.state if args.state else root / "workflow_state.json"
        context: Any = (
            ProjectContext(root, state_path)
            if state_path.is_file()
            else RootOnlyContext(root)
        )
        with context as ctx:
            issues = validate_with_context(
                ctx,
                literature_path=literature_relative,
                claim_path=claims_relative,
                output_path=outputs_relative,
                current_year=args.current_year,
            )
    except Exception as error:
        # 任何未预期异常统一收敛为 VALIDATOR_ERROR（INVALID），不再 traceback。
        issues = [Issue("VALIDATOR_ERROR", "INVALID", "evidence_chain", str(error))]
    print(render("evidence_chain", issues))
    return int(choose_exit(issues))


if __name__ == "__main__":
    raise SystemExit(main())
