#!/usr/bin/env python3
"""Validate the executable state machine for innovation-proposition-hunting."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from validation_common import (
    Issue,
    canonical_relative_path,
    choose_exit,
    nonempty_string,
    open_root_fd,
    positive_integer,
    read_regular_file_at,
    render,
    strict_json_load_bytes,
)
from validate_artifact_hashes import valid_sha256
from validate_schema_v2 import validate as validate_schema_v2


STATES = {
    # L1_SCOUT 段（证据层级 L1：仅元数据，零全文零原子观点）
    "BOOT",
    "SCOPE_LOCK",
    "PRIOR_CLAIM_DRAIN",
    "RECENT_FRONTIER",
    "LITERATURE_REGISTER",
    "L1_FREEZE",
    # L2_TRIAGE 段（证据层级 L2：≤12 全文试读、K 集合选拔，不提取原子观点）
    "L2_TRIAGE",
    "LAYER_DECISION",
    # L3_EVIDENCE 段（证据层级 L3：只对 K 集合跑全文归档与观点提取）
    "K_FULLTEXT",
    "K_CLAIM_REGISTER",
    "SYNTHESIZE_COLLISION",
    "OUTPUT_CLAIM_BIND",
    "EVIDENCE_VALIDATE",
    "N0_AUDIT",
    # VALIDITY 轴
    "CLAIM_FREEZE",
    "VALIDITY_AUDIT",
    "INDEPENDENT_REVIEW",
    "DIRECTION_LOCK",
    "POSTCOMPUTE_CLAIM_FREEZE",
    "FINAL_VALIDITY_AUDIT",
    "FINAL_LOCK",
    # COMPUTE 轴与终态
    "COMPUTE",
    "BLOCKED",
    "COMPLETE",
}
RESUMABLE_STATES = STATES - {"BLOCKED", "COMPLETE"}
OUTPUT_TYPES = {
    "UNRESOLVED",
    "DOCTORAL_DISSERTATION",
    "JOURNAL_ARTICLE",
}
CONTRACTS = {
    "UNRESOLVED",
    "THREE_ORGANIC_A_B_C",
    "ONE_MAIN_M",
}
CONTRIBUTIONS = {"NONE", "M", "A", "B", "C"}
SEARCH_MODES = {"SEARCH_OPEN", "SYNTHESIS_LOCK", "EXCEPTION_REOPEN"}
COMPUTE_STAGES = {"NOT_STARTED", "S0", "S1", "S2", "S3", "S4", "STOPPED"}
SNAPSHOT_MODES = {"NOT_SET", "NEW_SEARCH", "REUSED_VERIFIED_SNAPSHOT"}
GATE_KEYS = {
    "scope_locked",
    "prior_claims_drained",
    "recent_frontier_complete",
    "literature_registry_valid",
    "l1_frozen",
    "k_set_selected",
    "l2_frozen",
    "architecture_frozen",
    "k_fulltext_complete",
    "k_claims_complete",
    "output_claims_traced",
    "evidence_validated",
    "n0_4_locked",
    "compute_authorized",
}

STATE_PREREQUISITES = {
    "BOOT": (),
    "SCOPE_LOCK": (),
    "PRIOR_CLAIM_DRAIN": ("scope_locked",),
    "RECENT_FRONTIER": ("scope_locked", "prior_claims_drained"),
    "LITERATURE_REGISTER": (
        "scope_locked",
        "prior_claims_drained",
        "recent_frontier_complete",
    ),
    "L1_FREEZE": (
        "scope_locked",
        "prior_claims_drained",
        "recent_frontier_complete",
        "literature_registry_valid",
    ),
    "L2_TRIAGE": (
        "scope_locked",
        "prior_claims_drained",
        "recent_frontier_complete",
        "literature_registry_valid",
        "l1_frozen",
    ),
    "LAYER_DECISION": ("scope_locked", "k_set_selected"),
    "K_FULLTEXT": ("scope_locked", "l2_frozen", "architecture_frozen"),
    "K_CLAIM_REGISTER": ("scope_locked", "k_fulltext_complete"),
    "SYNTHESIZE_COLLISION": ("scope_locked", "k_claims_complete"),
    "OUTPUT_CLAIM_BIND": ("scope_locked", "k_claims_complete"),
    "EVIDENCE_VALIDATE": ("scope_locked", "output_claims_traced"),
    "N0_AUDIT": (
        "scope_locked",
        "evidence_validated",
        "l1_frozen",
        "l2_frozen",
        "architecture_frozen",
    ),
    "COMPUTE": (),
    "COMPLETE": ("scope_locked", "evidence_validated"),
}

GATE_ARTIFACTS = {
    "scope_locked": ("scope_lock", "hierarchy_status"),
    "literature_registry_valid": ("literature_registry", "url_ledger"),
    "l1_frozen": ("l1_card",),
    "k_set_selected": ("k_triage",),
    "l2_frozen": ("l2_card",),
    "architecture_frozen": ("contribution_architecture",),
    "k_fulltext_complete": ("literature_archive",),
    "k_claims_complete": ("claim_registry",),
    "output_claims_traced": ("output_support",),
    "evidence_validated": (
        "literature_registry",
        "claim_registry",
        "output_support",
        "validation_log",
    ),
    "n0_4_locked": ("hierarchy_novelty_audit",),
}

# gate -> 置真该 gate 的状态。置真必须能在 decision_log 中找到对应状态的完成
# 记录（条目 state 允许 "BLOCKED@<STATE>" 形式），否则视为"自报置真"。
GATE_COMPLETION_STATE = {
    "scope_locked": "SCOPE_LOCK",
    "prior_claims_drained": "PRIOR_CLAIM_DRAIN",
    "recent_frontier_complete": "RECENT_FRONTIER",
    "literature_registry_valid": "LITERATURE_REGISTER",
    "l1_frozen": "L1_FREEZE",
    "k_set_selected": "L2_TRIAGE",
    "l2_frozen": "LAYER_DECISION",
    "architecture_frozen": "LAYER_DECISION",
    "k_fulltext_complete": "K_FULLTEXT",
    "k_claims_complete": "K_CLAIM_REGISTER",
    "output_claims_traced": "OUTPUT_CLAIM_BIND",
    "evidence_validated": "EVIDENCE_VALIDATE",
    "n0_4_locked": "N0_AUDIT",
}

TRACK_STATES = {
    "NOVELTY": {
        "BOOT",
        "SCOPE_LOCK",
        "PRIOR_CLAIM_DRAIN",
        "RECENT_FRONTIER",
        "LITERATURE_REGISTER",
        "L1_FREEZE",
        "L2_TRIAGE",
        "LAYER_DECISION",
        "K_FULLTEXT",
        "K_CLAIM_REGISTER",
        "SYNTHESIZE_COLLISION",
        "OUTPUT_CLAIM_BIND",
        "EVIDENCE_VALIDATE",
        "N0_AUDIT",
    },
    "VALIDITY": {
        "CLAIM_FREEZE",
        "VALIDITY_AUDIT",
        "INDEPENDENT_REVIEW",
        "DIRECTION_LOCK",
        "POSTCOMPUTE_CLAIM_FREEZE",
        "FINAL_VALIDITY_AUDIT",
        "FINAL_LOCK",
    },
    "COMPUTE": {"COMPUTE"},
}

# 新增检查码：默认 WARNING（不计入退出码），--strict-new-checks 升为 INVALID。
# 不在此集合内的码维持原有严重级语义。
NEW_CHECK_CODES = frozenset(
    {
        "DECISION_LOG_ENTRY_SCHEMA",
        "DECISION_LOG_UNKNOWN_STATE",
        "DECISION_LOG_NON_MONOTONIC",
        "FUTURE_DECISION_TIMESTAMP",
        "DECISION_LOG_AFTER_STATE_WRITE",
        "UPDATED_AT_BEFORE_DECISION_LOG",
        "GATE_COMPLETION_RECORD_MISSING",
        "SELF_DECLARED_LEVEL",
        "COMPLETE_REQUIRES_FINAL_LOCK_CONDITIONS",
        "UNREGISTERED_COMPUTE_ARTIFACT",
        "REGISTRY_POINTER_MISSING",
        "FALSIFICATION_LEDGER_MISSING",
        "OCCUPATION_EVIDENCE_MISSING",
        "REDUCTION_EVIDENCE_MISSING",
        "COMPUTE_DATA_SOURCE_UNSPECIFIED",
        "SYNTHETIC_DATA_NAMED_AS_REAL",
        "MANUSCRIPT_DATASET_UNVERIFIED",
        "BASELINE_NOT_EXECUTED",
        "EVIDENCE_SCOPE_REGRESSED",
        "NEXT_ACTION_INCONSISTENT_WITH_STATE",
        "CAPABILITY_FLIPPED_WITHOUT_PROVENANCE",
        "ATOMIC_CLAIM_NO_ANCHOR",
        "INSTANCE_PROBE_UNAUTHORIZED",
        "INSTANCE_PROBE_LIMIT",
        "INSTANCE_PROBE_MEAN_AS_THRESHOLD",
        "L3_CONTRACT_MISSING",
        "L3_CONTRACT_INVALID",
        "AXIS_NOT_IN_INPUT",
        "G4_ROLE_MISSING",
        "G4_ROLE_UNKNOWN",
        "G4_WALKTHROUGH_ONLY",
        "G4_NOT_A_THRESHOLD_AS_COUNTEREXAMPLE",
        "COMPOSITION_AUDIT_MISSING",
        "COMPOSITION_AUDIT_INVALID",
        "COMPOSITION_REDUCES",
        "WIRINGS_MISSING",
        "WIRING_KIND_MISSING",
        "WIRING_NOT_ATTEMPTED",
        "WIRING_STILL_ALIVE",
        "SEPARATION_NOT_WHOLE",
        "PROTOCOL_SEALED_ACCESS_CONTRADICTION",
        "SEALED_UNIT_FINGERPRINT_MISSING",
        "SEALED_UNIT_SEEN_IN_PRECOMPUTE",
    }
)


# 主线是 L1→L2→L3 逐段构建；证据深度按段供给（SKILL.md §3.1、R-LAYER-13）。
# 证据层级 -> (全文预算, 原子观点预算)；超出即报 EVIDENCE_DEPTH_EXCEEDS_LAYER。
# schema 3.0 起状态机按段排布，合规流程不会超预算，故本检查为常驻 INVALID。
# L3 默认可被课题规模证伪：decision_log 登记
# `EVIDENCE_DEPTH_WAIVER fulltext<=N claims<=M` 后，用登记上限（不得低于默认，
# 且不得突破硬顶）。L1/L2 不得豁免。
EVIDENCE_DEPTH_BUDGETS = {
    "L1": (0, 0),
    "L2": (12, 0),
    "L3": (20, 60),
}
EVIDENCE_DEPTH_HARD_CAPS = {"L3": (40, 100)}
EVIDENCE_DEPTH_WAIVER_RE = re.compile(
    r"EVIDENCE_DEPTH_WAIVER\s+fulltext<=(\d+)\s+claims<=(\d+)"
)


def resolve_evidence_depth_budget(
    state: dict[str, Any], tier: str
) -> tuple[int, int]:
    """L3 可用 decision_log 登记的上限替换默认预算；L1/L2 不得豁免。"""

    default_fulltext, default_claims = EVIDENCE_DEPTH_BUDGETS[tier]
    if tier != "L3":
        return default_fulltext, default_claims
    hard_fulltext, hard_claims = EVIDENCE_DEPTH_HARD_CAPS["L3"]
    waived_fulltext = default_fulltext
    waived_claims = default_claims
    for entry in state.get("decision_log") or []:
        if not isinstance(entry, dict):
            continue
        action = entry.get("action")
        if not isinstance(action, str):
            continue
        match = EVIDENCE_DEPTH_WAIVER_RE.search(action)
        if match is None:
            continue
        waived_fulltext = max(waived_fulltext, int(match.group(1)))
        waived_claims = max(waived_claims, int(match.group(2)))
    return (
        min(waived_fulltext, hard_fulltext),
        min(waived_claims, hard_claims),
    )

# 证据层级不再持久化（design-schema-3.0 §4），由 effective_state 派生：
# 未列出的状态（L3_EVIDENCE 段、VALIDITY/COMPUTE 轴、COMPLETE）均为 L3。
STATE_EVIDENCE_TIER = {
    "BOOT": "L1",
    "SCOPE_LOCK": "L1",
    "PRIOR_CLAIM_DRAIN": "L1",
    "RECENT_FRONTIER": "L1",
    "LITERATURE_REGISTER": "L1",
    "L1_FREEZE": "L1",
    "L2_TRIAGE": "L2",
    "LAYER_DECISION": "L2",
}


def evidence_tier(effective_state: str) -> str:
    """由有效状态派生证据层级；BLOCKED 请先解析为 resume_state 再传入。"""
    return STATE_EVIDENCE_TIER.get(effective_state, "L3")


def count_registered_evidence(
    root: Path, state: dict[str, Any]
) -> tuple[int, int, list[str]]:
    """统计已注册的全文数与原子观点数；注册表缺失或损坏按 0 计。

    若 state 声明的注册表路径缺失或不安全，而默认路径（项目根下
    near_neighbor_registry.json / literature_claim_registry.json）存在，则回退按
    默认路径计数并记录一条 issue——防止改指针架空证据预算（指针落空≠证据为零）。
    """

    artifacts = state.get("artifacts")
    issues: list[str] = []

    def registry_path(key: str, default: str) -> Path:
        raw = artifacts.get(key) if isinstance(artifacts, dict) else None
        if nonempty(raw):
            declared = resolve_artifact(root, raw)
            if declared is not None and declared.is_file():
                return declared
            fallback = root / default
            if fallback.is_file():
                issues.append(f"{key}:declared_missing:{raw};counted_default:{default}")
                return fallback
            return root / str(raw)
        return root / default

    fulltext = 0
    try:
        literature_path = registry_path("literature_registry", "near_neighbor_registry.json")
        if literature_path.is_file():
            payload = json.loads(literature_path.read_text(encoding="utf-8"))
            records = payload.get("works") or payload.get("records") or []
            for record in records:
                if isinstance(record, dict) and (
                    record.get("download") or {}
                ).get("status") == "FULLTEXT_ARCHIVED":
                    fulltext += 1
    except (OSError, ValueError):
        pass
    atomic_claims = 0
    try:
        claims_path = registry_path("claim_registry", "literature_claim_registry.json")
        if claims_path.is_file():
            payload = json.loads(claims_path.read_text(encoding="utf-8"))
            records = payload.get("claims") or payload.get("records") or []
            atomic_claims = sum(isinstance(record, dict) for record in records)
    except (OSError, ValueError):
        pass
    return fulltext, atomic_claims, issues


def count_current_evidence(
    root: Path, state: dict[str, Any]
) -> tuple[int, int, list[tuple[str, str]]]:
    """统计计入当前碰撞轮深证据预算的全文数与原子观点数。

    全局注册表跨轮追加、只增不删，以保住 URL 完整性与历史溯源。state 声明了
    ``artifacts.current_evidence_scope`` 时，只有 scope 明列的 work/claim ID 计入
    当前层预算；未声明 scope 的项目保持旧行为，按全注册表计数。

    返回 (全文数, 观点数, issues)；issues 为 (检查码, 明细) 二元组：
    scope 文件自身的问题报 CURRENT_EVIDENCE_SCOPE_INVALID（INVALID 级），
    回退分支里注册表指针落空报 REGISTRY_POINTER_MISSING（WARNING 级）。
    """

    artifacts = state.get("artifacts")
    raw_scope = (
        artifacts.get("current_evidence_scope")
        if isinstance(artifacts, dict)
        else None
    )
    if not isinstance(raw_scope, str) or not raw_scope.strip():
        fulltext, claims, pointer_issues = count_registered_evidence(root, state)
        return (
            fulltext,
            claims,
            [("REGISTRY_POINTER_MISSING", detail) for detail in pointer_issues],
        )

    scope_path = resolve_artifact(root, raw_scope)
    if scope_path is None or not scope_path.is_file():
        return 0, 0, [("CURRENT_EVIDENCE_SCOPE_INVALID", f"missing_or_unsafe_path:{raw_scope}")]
    try:
        payload = json.loads(scope_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return 0, 0, [("CURRENT_EVIDENCE_SCOPE_INVALID", f"unreadable:{raw_scope}:{error}")]
    if not isinstance(payload, dict):
        return 0, 0, [("CURRENT_EVIDENCE_SCOPE_INVALID", "top_level_must_be_object")]

    issues: list[str] = []
    if payload.get("schema_version") != "2.0":
        issues.append(f"schema_version:{payload.get('schema_version')}")
    if payload.get("collision_round") != state.get("collision_round"):
        issues.append(
            "collision_round:"
            f"{payload.get('collision_round')};state:{state.get('collision_round')}"
        )

    def scoped_ids(key: str) -> list[str]:
        value = payload.get(key)
        if not isinstance(value, list) or not all(nonempty(item) for item in value):
            issues.append(f"{key}:nonempty_string_list_required")
            return []
        if len(value) != len(set(value)):
            issues.append(f"{key}:duplicate_ids")
        return list(dict.fromkeys(value))

    fulltext_ids = scoped_ids("fulltext_registry_ids")
    claim_ids = scoped_ids("atomic_claim_ids")

    def artifact_payload(key: str, default: str) -> dict[str, Any]:
        raw = artifacts.get(key) if isinstance(artifacts, dict) else None
        path = resolve_artifact(root, raw if isinstance(raw, str) else default)
        if path is None or not path.is_file():
            issues.append(f"{key}:missing_or_unsafe_path")
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            issues.append(f"{key}:unreadable:{error}")
            return {}
        if not isinstance(value, dict):
            issues.append(f"{key}:top_level_must_be_object")
            return {}
        return value

    literature = artifact_payload(
        "literature_registry", "near_neighbor_registry.json"
    )
    literature_records = literature.get("works") or literature.get("records") or []
    works_by_id = {
        record.get("registry_id"): record
        for record in literature_records
        if isinstance(record, dict) and nonempty(record.get("registry_id"))
    }
    for registry_id in fulltext_ids:
        record = works_by_id.get(registry_id)
        if record is None:
            issues.append(f"unknown_fulltext_registry_id:{registry_id}")
            continue
        status = (record.get("download") or {}).get("status")
        if status not in {"FULLTEXT_ARCHIVED", "OFFICIAL_HTML_ARCHIVED"}:
            issues.append(
                f"fulltext_registry_id_not_archived:{registry_id};status:{status}"
            )

    claims = artifact_payload("claim_registry", "literature_claim_registry.json")
    claim_records = claims.get("claims") or claims.get("records") or []
    known_claim_ids = {
        record.get("claim_id")
        for record in claim_records
        if isinstance(record, dict) and nonempty(record.get("claim_id"))
    }
    for claim_id in claim_ids:
        if claim_id not in known_claim_ids:
            issues.append(f"unknown_atomic_claim_id:{claim_id}")
    return (
        len(fulltext_ids),
        len(claim_ids),
        [("CURRENT_EVIDENCE_SCOPE_INVALID", detail) for detail in issues],
    )


# compute_authorized=false 时视为"未授权计算产物"的路径模式（根相对 glob）。
# instance_probes/ 必须先经 iph authorize/register-instance-probe 登记。
COMPUTE_ARTIFACT_GLOBS = ("s0_*", "s0_outputs/**/*", "instance_probes/**/*")
MAX_INSTANCE_PROBES = 5
MEAN_AS_THRESHOLD = re.compile(
    r"dataset mean|dataset-level|总体均值|平均分当|figure\s*4.*threshold",
    re.IGNORECASE,
)
G4_ROLES = {
    "OLD_STOP_STILL_SCORES",
    "NEW_STOP_FAIL",
    "DESIGN_WALKTHROUGH",
    "NOT_A_THRESHOLD",
    "RECONSTRUCTION",
}
G4_SUPPORTING_ROLES = frozenset({"OLD_STOP_STILL_SCORES", "NEW_STOP_FAIL"})
ALGORITHM_PROFILES = {"ALGORITHM", "MIXED"}


def n0_4_claimed(state: dict[str, Any]) -> bool:
    gates = state.get("gates")
    return state.get("novelty_level") == "N0-4C" or (
        isinstance(gates, dict) and gates.get("n0_4_locked") is True
    )


def algorithm_profile(state: dict[str, Any]) -> bool:
    return state.get("claim_profile") in ALGORITHM_PROFILES


def load_optional_json_artifact(
    root: Path, state: dict[str, Any], key: str, fallback: str
) -> tuple[Path | None, dict[str, Any] | None, str | None]:
    """读取可选 JSON 工件。返回 (path, payload, error)。缺文件时 path 为 None。"""

    artifacts = state.get("artifacts")
    raw = artifacts.get(key) if isinstance(artifacts, dict) else None
    relative = raw if isinstance(raw, str) and raw.strip() else fallback
    path = resolve_artifact(root, relative)
    if path is None or not path.is_file():
        return None, None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return path, None, f"unreadable:{error}"
    if not isinstance(payload, dict):
        return path, None, "top_level_must_be_object"
    return path, payload, None


def validate_instance_probe_registry(
    root: Path, state: dict[str, Any], errors: list[str]
) -> None:
    """N0-3 实例探针：必须先授权、≤5 条、不得把数据集均值当成功阈值。"""

    artifacts = state.get("artifacts")
    raw = (
        artifacts.get("instance_probe_registry")
        if isinstance(artifacts, dict)
        else None
    )
    relative = raw if isinstance(raw, str) and raw.strip() else "instance_probe_registry.json"
    path = resolve_artifact(root, relative)
    if path is None or not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        add(errors, "INSTANCE_PROBE_UNAUTHORIZED", f"unreadable:{error}")
        return
    if not isinstance(payload, dict):
        add(errors, "INSTANCE_PROBE_UNAUTHORIZED", "top_level_must_be_object")
        return
    if not nonempty(payload.get("authorization_note")):
        add(errors, "INSTANCE_PROBE_UNAUTHORIZED", "authorization_note:missing")
    probes = payload.get("probes")
    if probes is None:
        probes = []
    if not isinstance(probes, list):
        add(errors, "INSTANCE_PROBE_UNAUTHORIZED", "probes:not_list")
        return
    if len(probes) > MAX_INSTANCE_PROBES:
        add(
            errors,
            "INSTANCE_PROBE_LIMIT",
            f"count:{len(probes)}>max:{MAX_INSTANCE_PROBES}",
        )
    observed_roles: list[str] = []
    for index, probe in enumerate(probes):
        item = f"probes[{index}]"
        if not isinstance(probe, dict):
            add(errors, "INSTANCE_PROBE_UNAUTHORIZED", f"{item}:not_object")
            continue
        if probe.get("old_metric_verdict") == "SUCCESS":
            rule = probe.get("success_rule")
            if not nonempty(rule) or MEAN_AS_THRESHOLD.search(str(rule)):
                add(
                    errors,
                    "INSTANCE_PROBE_MEAN_AS_THRESHOLD",
                    f"{item}:success_rule:{rule}",
                )
        role = probe.get("g4_role")
        if role is None or (isinstance(role, str) and not role.strip()):
            if n0_4_claimed(state):
                add(errors, "G4_ROLE_MISSING", f"{item}:g4_role")
            continue
        if role not in G4_ROLES:
            add(errors, "G4_ROLE_UNKNOWN", f"{item}:g4_role:{role}")
            continue
        observed_roles.append(role)
        if (
            n0_4_claimed(state)
            and probe.get("purpose") == "COUNTEREXAMPLE"
            and role == "NOT_A_THRESHOLD"
        ):
            add(
                errors,
                "G4_NOT_A_THRESHOLD_AS_COUNTEREXAMPLE",
                f"{item}:published score is not a fail witness",
            )
    if n0_4_claimed(state) and observed_roles:
        if not any(role in G4_SUPPORTING_ROLES for role in observed_roles):
            add(
                errors,
                "G4_WALKTHROUGH_ONLY",
                "DESIGN_WALKTHROUGH/NOT_A_THRESHOLD/RECONSTRUCTION cannot solely support N0-4C",
            )


def validate_l3_contract(
    root: Path, state: dict[str, Any], errors: list[str]
) -> None:
    """停止轴必须是已声明输入的函数（AXIS_NOT_IN_INPUT）。"""

    path, payload, error = load_optional_json_artifact(
        root, state, "l3_contract", "l3_contract.json"
    )
    required = n0_4_claimed(state) and algorithm_profile(state)
    if path is None:
        if required:
            add(errors, "L3_CONTRACT_MISSING", "ALGORITHM/MIXED N0-4C 需要 l3_contract.json")
        return
    if payload is None:
        add(errors, "L3_CONTRACT_INVALID", error or "unreadable")
        return
    inputs = payload.get("inputs")
    generated = payload.get("generated")
    stop_axes = payload.get("stop_axes")
    input_set: set[str] = set()
    generated_set: set[str] = set()
    if not isinstance(inputs, list) or not inputs:
        add(errors, "L3_CONTRACT_INVALID", "inputs:expected_nonempty_list")
    else:
        for index, item in enumerate(inputs):
            if not nonempty(item):
                add(errors, "L3_CONTRACT_INVALID", f"inputs[{index}]:expected_nonempty_string")
                continue
            input_set.add(item.strip())
    if generated is not None:
        if not isinstance(generated, list):
            add(errors, "L3_CONTRACT_INVALID", "generated:expected_list")
        else:
            for index, item in enumerate(generated):
                if not nonempty(item):
                    add(
                        errors,
                        "L3_CONTRACT_INVALID",
                        f"generated[{index}]:expected_nonempty_string",
                    )
                    continue
                name = item.strip()
                if name in input_set:
                    add(errors, "L3_CONTRACT_INVALID", f"generated:{name}:overlaps_inputs")
                    continue
                generated_set.add(name)
    allowed = input_set | generated_set
    if not isinstance(stop_axes, list) or not stop_axes:
        add(errors, "L3_CONTRACT_INVALID", "stop_axes:expected_nonempty_list")
        return
    for index, axis in enumerate(stop_axes):
        item = f"stop_axes[{index}]"
        if not isinstance(axis, dict):
            add(errors, "L3_CONTRACT_INVALID", f"{item}:not_object")
            continue
        name = axis.get("name")
        axis_name = name.strip() if nonempty(name) else item
        depends_on = axis.get("depends_on")
        if not isinstance(depends_on, list):
            add(errors, "L3_CONTRACT_INVALID", f"{item}:depends_on:not_list")
            continue
        for dep_index, dep in enumerate(depends_on):
            if not nonempty(dep):
                add(
                    errors,
                    "L3_CONTRACT_INVALID",
                    f"{item}:depends_on[{dep_index}]:expected_nonempty_string",
                )
                continue
            if dep.strip() not in allowed:
                add(
                    errors,
                    "AXIS_NOT_IN_INPUT",
                    f"axis:{axis_name};dep:{dep.strip()}",
                )
    if "p" not in allowed:
        artifacts = state.get("artifacts")
        raw_statement = (
            artifacts.get("exact_statement") if isinstance(artifacts, dict) else None
        )
        statement_path = resolve_artifact(
            root, raw_statement if nonempty(raw_statement) else "l3-exact.md"
        )
        if statement_path is not None and statement_path.is_file():
            try:
                statement = statement_path.read_text(encoding="utf-8")
            except OSError:
                statement = ""
            if re.search(r"p_loc|\(src_span", statement):
                add(
                    errors,
                    "AXIS_NOT_IN_INPUT",
                    "axis:two_sided_certificate;dep:p",
                )


REQUIRED_WIRING_KINDS = ("POSTHOC_LABEL", "SCHEMA_EXTENSION", "RENAME")
WIRING_STATUSES = {"KILLED", "ALIVE", "NOT_ATTEMPTED"}


def composition_n0_4_lock_errors(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """N0-4C 组合锁：必须先打过三种必做接线，且没有仍活/未尝试的接线。"""

    problems: list[tuple[str, str]] = []
    if payload.get("union_equals_candidate") is True:
        problems.append(
            (
                "COMPOSITION_REDUCES",
                "union_equals_candidate=true 是机械并集，不能锁定 N0-4C",
            )
        )
    elif payload.get("union_equals_candidate") is not False:
        problems.append(
            (
                "COMPOSITION_AUDIT_INVALID",
                "union_equals_candidate:expected_false_for_N0-4C",
            )
        )
    if not nonempty(payload.get("reduction_failed_because")):
        problems.append(
            ("COMPOSITION_AUDIT_INVALID", "reduction_failed_because:missing")
        )
    remaining = payload.get("strongest_remaining")
    if remaining not in {None, ""}:
        if not nonempty(remaining):
            problems.append(
                ("COMPOSITION_AUDIT_INVALID", "strongest_remaining:expected_string_or_empty")
            )
        else:
            problems.append(
                (
                    "WIRING_STILL_ALIVE",
                    f"strongest_remaining:{remaining.strip()}",
                )
            )
    wirings = payload.get("wirings")
    if not isinstance(wirings, list) or not wirings:
        problems.append(("WIRINGS_MISSING", "N0-4C 必须登记 wirings"))
        for kind in REQUIRED_WIRING_KINDS:
            problems.append(("WIRING_KIND_MISSING", f"kind:{kind}"))
        return problems
    seen: set[str] = set()
    for index, wiring in enumerate(wirings):
        item = f"wirings[{index}]"
        if not isinstance(wiring, dict):
            problems.append(("COMPOSITION_AUDIT_INVALID", f"{item}:not_object"))
            continue
        kind = wiring.get("kind")
        if kind not in REQUIRED_WIRING_KINDS and not nonempty(kind):
            problems.append(("COMPOSITION_AUDIT_INVALID", f"{item}:kind:missing"))
            continue
        if nonempty(kind):
            seen.add(str(kind).strip())
        status = wiring.get("status")
        if status not in WIRING_STATUSES:
            problems.append(
                ("COMPOSITION_AUDIT_INVALID", f"{item}:status:{status}")
            )
            continue
        if status == "NOT_ATTEMPTED":
            problems.append(
                ("WIRING_NOT_ATTEMPTED", f"{item}:kind:{kind}")
            )
        elif status == "ALIVE":
            problems.append(("WIRING_STILL_ALIVE", f"{item}:kind:{kind}"))
        elif status == "KILLED":
            claim_ids = wiring.get("kill_claim_ids")
            if not isinstance(claim_ids, list) or not any(
                nonempty(claim_id) for claim_id in claim_ids
            ):
                problems.append(
                    ("SEPARATION_NOT_WHOLE", f"{item}:kill_claim_ids:missing")
                )
            if wiring.get("whole_mapping_separates") is not True:
                problems.append(
                    (
                        "SEPARATION_NOT_WHOLE",
                        f"{item}:whole_mapping_separates:not_true",
                    )
                )
    for kind in REQUIRED_WIRING_KINDS:
        if kind not in seen:
            problems.append(("WIRING_KIND_MISSING", f"kind:{kind}"))
    return problems


def validate_composition_audit(
    root: Path, state: dict[str, Any], errors: list[str]
) -> None:
    """N0-4C ALGORITHM/MIXED 必须登记并杀死三种必做接线，不是只杀一种弱 U*。"""

    path, payload, error = load_optional_json_artifact(
        root, state, "composition_audit", "composition_audit.json"
    )
    required = n0_4_claimed(state) and algorithm_profile(state)
    if path is None:
        if required:
            add(
                errors,
                "COMPOSITION_AUDIT_MISSING",
                "ALGORITHM/MIXED N0-4C 需要 composition_audit.json",
            )
        return
    if payload is None:
        add(errors, "COMPOSITION_AUDIT_INVALID", error or "unreadable")
        return
    components = payload.get("components")
    if not isinstance(components, list) or not components:
        add(errors, "COMPOSITION_AUDIT_INVALID", "components:expected_nonempty_list")
        return
    for index, component in enumerate(components):
        item = f"components[{index}]"
        if not isinstance(component, dict):
            add(errors, "COMPOSITION_AUDIT_INVALID", f"{item}:not_object")
            continue
        if not nonempty(component.get("mechanical_gap")):
            add(errors, "COMPOSITION_AUDIT_INVALID", f"{item}:mechanical_gap:missing")
    if not required:
        return
    for code, detail in composition_n0_4_lock_errors(payload):
        add(errors, code, detail)


def find_unregistered_compute_artifacts(
    root: Path, state: dict[str, Any]
) -> list[str]:
    """S0-SCREEN 之前的数值产物必须登记 exploration_registry，否则逐一上报。"""

    registered: set[str] = set()
    try:
        artifacts = state.get("artifacts")
        relative = (
            artifacts.get("exploration_registry")
            if isinstance(artifacts, dict)
            else None
        )
        registry_path = root / (
            relative if isinstance(relative, str) else "exploration_registry.json"
        )
        if registry_path.is_file():
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            entries = registry.get("explorations")
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and isinstance(
                        entry.get("path"), str
                    ):
                        registered.add(entry["path"])
        probe_relative = (
            artifacts.get("instance_probe_registry")
            if isinstance(artifacts, dict)
            else None
        )
        probe_path = root / (
            probe_relative
            if isinstance(probe_relative, str)
            else "instance_probe_registry.json"
        )
        if probe_path.is_file():
            registered.add(probe_path.relative_to(root).as_posix())
            probes = json.loads(probe_path.read_text(encoding="utf-8")).get(
                "probes"
            )
            if isinstance(probes, list):
                for probe in probes:
                    if isinstance(probe, dict) and isinstance(
                        probe.get("output_file"), str
                    ):
                        registered.add(probe["output_file"])
    except (OSError, ValueError):
        pass
    found: list[str] = []
    for pattern in COMPUTE_ARTIFACT_GLOBS:
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                if relative not in registered:
                    found.append(relative)
    return sorted(set(found))


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workflow state top level must be an object")
    return payload


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def add(errors: list[str], code: str, detail: str) -> None:
    errors.append(f"{code}\t{detail}")


def resolve_artifact(root: Path, raw_path: Any) -> Path | None:
    if not nonempty(raw_path):
        return None
    path = (root / str(raw_path)).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


# 新颖性裁决证据识别——正面与负面终局同价（R-N0-17）。
# 证伪书（falsification ledger）：N0-4C 候选存活，须列杀死候选的尝试及失败原因。
# 占据证据（occupation evidence）：N0-1 直接占据，须列占据者及覆盖内容。
# 归约证据（reduction evidence）：N0-2 机械可推出，须列可归约近邻及归约路径。
FALSIFICATION_HEADING = re.compile(r"证伪书|falsification\s*ledger", re.IGNORECASE)
FALSIFICATION_ENTRY = re.compile(
    r"^\s*[-*]\s*\[(?:证伪路径|falsification)", re.IGNORECASE
)
OCCUPATION_HEADING = re.compile(r"占据证据|occupation\s*evidence", re.IGNORECASE)
OCCUPATION_ENTRY = re.compile(r"^\s*[-*]\s*\[(?:占据|occupation)", re.IGNORECASE)
REDUCTION_HEADING = re.compile(r"归约证据|reduction\s*evidence", re.IGNORECASE)
REDUCTION_ENTRY = re.compile(r"^\s*[-*]\s*\[(?:归约|reduction)", re.IGNORECASE)


def section_present(text: str, heading: re.Pattern[str], entry: re.Pattern[str]) -> bool:
    """文档是否含指定标题且其后至少一条条目。"""
    lines = text.splitlines()
    saw_heading = False
    for line in lines:
        if not saw_heading and heading.search(line):
            saw_heading = True
            continue
        if saw_heading and entry.search(line):
            return True
    return False


# novelty_level -> (所需证据节, 缺失错误码)。
# N0-3 是 HOLD（未裁决），不要求终局证据。
NOVELTY_VERDICT_EVIDENCE = {
    "N0-4C": (FALSIFICATION_HEADING, FALSIFICATION_ENTRY, "FALSIFICATION_LEDGER_MISSING"),
    "N0-1": (OCCUPATION_HEADING, OCCUPATION_ENTRY, "OCCUPATION_EVIDENCE_MISSING"),
    "N0-2": (REDUCTION_HEADING, REDUCTION_ENTRY, "REDUCTION_EVIDENCE_MISSING"),
}


def validate_novelty_verdict_evidence(
    root: Path, state: dict[str, Any], errors: list[str]
) -> None:
    """novelty-audit.md 必须含与 novelty_level 对应的裁决证据（R-N0-17）。"""
    novelty_level = state.get("novelty_level")
    spec = NOVELTY_VERDICT_EVIDENCE.get(novelty_level)
    if spec is None:
        return
    heading, entry, code = spec
    artifacts = state.get("artifacts")
    if not isinstance(artifacts, dict):
        return
    path = resolve_artifact(root, artifacts.get("hierarchy_novelty_audit"))
    if path is None or not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    if not section_present(text, heading, entry):
        add(
            errors,
            code,
            f"novelty-audit 缺少 {novelty_level} 所需的裁决证据节",
        )


def validate_evidence_scope_monotonic(
    root: Path, state: dict[str, Any], errors: list[str]
) -> None:
    """R-LAYER-13：scope 登记单调不减。K 全文门已过（k_fulltext_complete=true）
    时，current_evidence_scope 的 fulltext_registry_ids 不得为空——清空 scope
    以骗过预算门即 EVIDENCE_SCOPE_REGRESSED。"""
    gates = state.get("gates")
    if not isinstance(gates, dict) or gates.get("k_fulltext_complete") is not True:
        return
    artifacts = state.get("artifacts")
    raw_scope = (
        artifacts.get("current_evidence_scope")
        if isinstance(artifacts, dict)
        else None
    )
    if not isinstance(raw_scope, str) or not raw_scope.strip():
        add(errors, "EVIDENCE_SCOPE_REGRESSED", "k_fulltext_complete=true 但未声明 current_evidence_scope")
        return
    scope_path = resolve_artifact(root, raw_scope)
    if scope_path is None or not scope_path.is_file():
        return
    try:
        payload = json.loads(scope_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    fulltext_ids = payload.get("fulltext_registry_ids")
    if not isinstance(fulltext_ids, list) or not fulltext_ids:
        add(errors, "EVIDENCE_SCOPE_REGRESSED", f"{raw_scope} 的 fulltext_registry_ids 为空")


def validate_next_action_consistent(
    state: dict[str, Any], errors: list[str]
) -> None:
    """R-LOG-04：终局状态下 next_required_action 不得出现前向状态推进提示。"""
    effective = state.get("active_state")
    if effective == "BLOCKED":
        effective = state.get("resume_state")
    if effective not in {"FINAL_LOCK", "COMPLETE"}:
        return
    next_action = state.get("next_required_action")
    if not nonempty_string(next_action):
        return
    # 前向中间态名：终局状态下若提示里仍含这些词，说明 next_required_action 滞留旧态。
    forward_markers = (
        "LAYER_DECISION",
        "L2_TRIAGE",
        "L1_FREEZE",
        "K_FULLTEXT",
        "K_CLAIM_REGISTER",
        "CLAIM_FREEZE",
        "SYNTHESIZE_COLLISION",
        "N0_AUDIT",
        "VALIDITY_AUDIT",
        "INDEPENDENT_REVIEW",
        "DIRECTION_LOCK",
        "COMPUTE",
        "POSTCOMPUTE_CLAIM_FREEZE",
        "FINAL_VALIDITY_AUDIT",
    )
    lowered = next_action.casefold()
    for marker in forward_markers:
        if marker.casefold() in lowered:
            add(
                errors,
                "NEXT_ACTION_INCONSISTENT_WITH_STATE",
                f"active_state:{effective};next_required_action 含中间态 {marker}",
            )
            return


def validate_capability_flip_provenance(
    state: dict[str, Any], errors: list[str]
) -> None:
    """R-REVIEW-20：capability_available=true 且 verdict=PASS 时，必须有
    review_artifact_sha256 登记（走 iph review 命令），否则视为无 provenance 的翻转。"""
    audit = state.get("independent_audit")
    if not isinstance(audit, dict):
        return
    if audit.get("capability_available") is not True:
        return
    if audit.get("verdict") != "PASS":
        return
    if not nonempty_string(state.get("review_artifact_sha256")):
        add(
            errors,
            "CAPABILITY_FLIPPED_WITHOUT_PROVENANCE",
            "PASS 但无 review_artifact_sha256 登记（未走 iph review）",
        )


# 公开真实数据集名白名单：manuscript 声称用这些数据集时，compute_evidence 的
# data_sources 必须有对应非合成条目（R-COMPUTE-02 数据真实性）。
REAL_DATASET_MARKERS = (
    "auscredit",
    "german credit",
    "ieee-cis",
    "ieee cis",
    "paysim",
    "creditcard",
    "mnist",
    "cifar",
    "imagenet",
    "kaggle",
    "uci",
)


def _data_sources_from_evidence(evidence_text: str) -> tuple[list[dict], list[str]]:
    """解析 compute_evidence 内容，返回 (data_sources, issues)。"""
    try:
        payload = strict_json_load_bytes(evidence_text.encode("utf-8"))
    except Exception:
        return [], []
    if not isinstance(payload, dict):
        return [], []
    data_sources = payload.get("data_sources")
    if not isinstance(data_sources, list):
        return [], []
    return data_sources, []


def iter_sealed_runs(payload: Any) -> list[dict[str, Any]]:
    """收集 compute_evidence 中 split=sealed 的运行行。"""

    found: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if payload.get("split") == "sealed" and isinstance(payload.get("unit"), str):
            found.append(payload)
        for value in payload.values():
            found.extend(iter_sealed_runs(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(iter_sealed_runs(item))
    return found


def load_json_if_present(root: Path, relative: Any) -> dict[str, Any] | None:
    if not canonical_relative_path(relative):
        return None
    path = root / relative
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def validate_sealed_confirmation(
    root: Path, state: dict[str, Any], errors: list[str]
) -> None:
    """S4/封存运行必须与协议一致，且不得复用计算前测试构造。"""

    artifacts = state.get("artifacts")
    protocol_rel = (
        artifacts.get("protocol_contract")
        if isinstance(artifacts, dict) and artifacts.get("protocol_contract")
        else "protocol_contract.json"
    )
    protocol = load_json_if_present(root, protocol_rel)
    sealed_role = (
        protocol.get("sealed_confirmation_data") if isinstance(protocol, dict) else None
    )

    evidence_payload: dict[str, Any] | None = None
    evidence = state.get("compute_evidence")
    if isinstance(evidence, dict) and evidence.get("status") == "COMPLETED":
        evidence_payload = load_json_if_present(root, evidence.get("artifact_path"))
    sealed_runs = iter_sealed_runs(evidence_payload) if evidence_payload else []
    compute_reached_s4 = state.get("compute_stage") == "S4" or bool(sealed_runs)

    if compute_reached_s4 and sealed_role == "NOT_YET_ACCESSED":
        add(
            errors,
            "PROTOCOL_SEALED_ACCESS_CONTRADICTION",
            "protocol.sealed_confirmation_data=NOT_YET_ACCESSED after sealed compute",
        )

    if not sealed_runs:
        return

    test_texts: list[str] = []
    trace_rel = (
        artifacts.get("claim_code_trace")
        if isinstance(artifacts, dict) and artifacts.get("claim_code_trace")
        else "claim_code_trace.json"
    )
    trace = load_json_if_present(root, trace_rel)
    traces = trace.get("traces") if isinstance(trace, dict) else None
    if isinstance(traces, list):
        for item in traces:
            if not isinstance(item, dict):
                continue
            test_rel = item.get("executable_test_relative_path")
            if not canonical_relative_path(test_rel):
                continue
            test_path = root / test_rel
            if test_path.is_file():
                try:
                    test_texts.append(test_path.read_text(encoding="utf-8"))
                except OSError:
                    continue

    for run in sealed_runs:
        unit = run.get("unit")
        fingerprint = run.get("unseen_fingerprint")
        if not nonempty_string(fingerprint) or len(str(fingerprint).strip()) < 4:
            add(
                errors,
                "SEALED_UNIT_FINGERPRINT_MISSING",
                f"unit:{unit}",
            )
            continue
        token = str(fingerprint).strip()
        for text in test_texts:
            if token in text:
                add(
                    errors,
                    "SEALED_UNIT_SEEN_IN_PRECOMPUTE",
                    f"unit:{unit};fingerprint:{token}",
                )
                break


def validate_data_sources(
    root: Path, state: dict[str, Any], errors: list[str]
) -> None:
    """数据真实性：compute_evidence.data_sources 与 manuscript 数据集名交叉验证。"""
    evidence = state.get("compute_evidence")
    if not isinstance(evidence, dict) or evidence.get("status") != "COMPLETED":
        return
    artifact_path = evidence.get("artifact_path")
    if not canonical_relative_path(artifact_path):
        return

    # 读 compute_evidence 内容。
    root_fd: int | None = None
    try:
        root_fd = open_root_fd(root)
        snapshot = read_regular_file_at(root_fd, artifact_path, include_data=True)
    except Exception:
        return
    finally:
        if root_fd is not None:
            os.close(root_fd)
    if snapshot.data is None:
        return

    data_sources, _ = _data_sources_from_evidence(snapshot.data.decode("utf-8"))
    if not data_sources:
        add(errors, "COMPUTE_DATA_SOURCE_UNSPECIFIED", "compute_evidence.data_sources:missing_or_empty")
        return

    # synthetic=true 的源不得使用真实数据集名。
    for source in data_sources:
        if not isinstance(source, dict):
            continue
        name = source.get("name")
        synthetic = source.get("synthetic") is True
        if synthetic and nonempty_string(name):
            lowered = name.casefold()
            for marker in REAL_DATASET_MARKERS:
                if marker in lowered:
                    add(
                        errors,
                        "SYNTHETIC_DATA_NAMED_AS_REAL",
                        f"data_sources.name:{name}",
                    )
                    break

    # manuscript 声称的真实数据集名必须能在 data_sources 找到非合成条目。
    non_synthetic_names = {
        source.get("name", "").casefold()
        for source in data_sources
        if isinstance(source, dict) and source.get("synthetic") is not True
    }
    artifacts = state.get("artifacts")
    manuscript_rel = (
        artifacts.get("manuscript")
        if isinstance(artifacts, dict) and artifacts.get("manuscript")
        else "manuscript.md"
    )
    try:
        root_fd = open_root_fd(root)
        manuscript_snapshot = read_regular_file_at(
            root_fd, manuscript_rel, include_data=True
        )
    except Exception:
        return
    finally:
        if root_fd is not None:
            os.close(root_fd)
    if manuscript_snapshot.data is None:
        return
    manuscript_text = manuscript_snapshot.data.decode("utf-8").casefold()
    for marker in REAL_DATASET_MARKERS:
        if marker not in manuscript_text:
            continue
        if marker in non_synthetic_names or any(
            marker in name for name in non_synthetic_names
        ):
            continue
        add(
            errors,
            "MANUSCRIPT_DATASET_UNVERIFIED",
            f"manuscript 声称数据集 {marker!r}，但 compute_evidence.data_sources 无对应非合成条目",
        )


def validate_baseline_execution(
    root: Path, state: dict[str, Any], errors: list[str]
) -> None:
    """空壳 baseline 检测：baseline_budget 声明的 comparator 在 compute_evidence
    里必须有非空执行证据（per_run 非空）。per_run 为空数组即 BASELINE_NOT_EXECUTED。"""
    evidence = state.get("compute_evidence")
    if not isinstance(evidence, dict) or evidence.get("status") != "COMPLETED":
        return
    artifact_path = evidence.get("artifact_path")
    if not canonical_relative_path(artifact_path):
        return

    artifacts = state.get("artifacts")
    baseline_rel = (
        artifacts.get("baseline_budget")
        if isinstance(artifacts, dict) and artifacts.get("baseline_budget")
        else "baseline_budget.json"
    )
    if not canonical_relative_path(baseline_rel):
        return

    root_fd: int | None = None
    try:
        root_fd = open_root_fd(root)
        evidence_snapshot = read_regular_file_at(
            root_fd, artifact_path, include_data=True
        )
        baseline_snapshot = read_regular_file_at(
            root_fd, baseline_rel, include_data=True
        )
    except Exception:
        return
    finally:
        if root_fd is not None:
            os.close(root_fd)
    if evidence_snapshot.data is None or baseline_snapshot.data is None:
        return

    try:
        evidence_payload = strict_json_load_bytes(evidence_snapshot.data)
        baseline_payload = strict_json_load_bytes(baseline_snapshot.data)
    except Exception:
        return
    if not isinstance(evidence_payload, dict) or not isinstance(baseline_payload, dict):
        return
    comparators = baseline_payload.get("comparators")
    if not isinstance(comparators, list):
        return

    # baseline_budget 的 comparator_id 用连字符，compute_evidence 顶层键用下划线。
    # 归一化后匹配；匹配不到即保守跳过（不误报主方法/命名不一致）。
    evidence_keys = set(evidence_payload.keys())
    for comparator in comparators:
        if not isinstance(comparator, dict):
            continue
        comparator_id = comparator.get("comparator_id")
        if not nonempty_string(comparator_id):
            continue
        normalized = comparator_id.replace("-", "_")
        entry = evidence_payload.get(normalized)
        if not isinstance(entry, dict):
            continue
        per_run = entry.get("per_run")
        if isinstance(per_run, list) and not per_run:
            add(
                errors,
                "BASELINE_NOT_EXECUTED",
                f"comparator:{comparator_id} per_run 为空，未实际执行",
            )


# 原子观点套壳信号：观点是"文献元描述"而非"文献可判断观点"（R-ATOMIC-19）。
# 匹配任一模式即 ATOMIC_CLAIM_NO_ANCHOR：元描述不是观点，套壳填槽不算提炼。
ATOMIC_SHELL_PATTERNS = (
    re.compile(r"^(?:paper|the\s+paper|this\s+paper)\b", re.IGNORECASE),
    re.compile(r"introduction/abstract", re.IGNORECASE),
    re.compile(r"\bis\s+(?:远邻|近邻)\b", re.IGNORECASE),
    re.compile(r"acknowledges?\s+limitations", re.IGNORECASE),
)


def validate_atomic_claim_quality(
    root: Path, state: dict[str, Any], errors: list[str]
) -> None:
    """R-ATOMIC-19：原子观点不能是文献元描述套壳（"Paper W-XXXX proposes..."）。"""
    artifacts = state.get("artifacts")
    claim_rel = (
        artifacts.get("claim_registry")
        if isinstance(artifacts, dict) and artifacts.get("claim_registry")
        else "literature_claim_registry.json"
    )
    if not canonical_relative_path(claim_rel):
        return
    path = resolve_artifact(root, claim_rel)
    if path is None or not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    records = payload.get("claims") or payload.get("records") or []
    for record in records:
        if not isinstance(record, dict):
            continue
        statement = record.get("normalized_statement") or record.get("statement") or ""
        if not nonempty_string(statement):
            continue
        claim_id = record.get("claim_id") or "?"
        for pattern in ATOMIC_SHELL_PATTERNS:
            if pattern.search(statement):
                add(
                    errors,
                    "ATOMIC_CLAIM_NO_ANCHOR",
                    f"{claim_id}: 套壳观点「{statement[:80]}」",
                )
                break



def validate_compute_evidence(
    root: Path,
    state: dict[str, Any],
    errors: list[str],
) -> bool:
    evidence = state.get("compute_evidence")
    if not isinstance(evidence, dict):
        add(errors, "INVALID_COMPUTE_EVIDENCE", "missing_or_invalid_object")
        return False

    valid = True
    if evidence.get("status") != "COMPLETED":
        add(
            errors,
            "INVALID_COMPUTE_EVIDENCE",
            f"status:{evidence.get('status')}",
        )
        valid = False

    evidence_epoch = evidence.get("validation_epoch")
    state_epoch = state.get("validation_epoch")
    if not positive_integer(evidence_epoch) or evidence_epoch != state_epoch:
        add(
            errors,
            "INVALID_COMPUTE_EVIDENCE",
            f"validation_epoch:{evidence_epoch};state:{state_epoch}",
        )
        valid = False

    artifact_path = evidence.get("artifact_path")
    if not canonical_relative_path(artifact_path):
        add(
            errors,
            "INVALID_COMPUTE_EVIDENCE",
            f"artifact_path:{artifact_path}",
        )
        valid = False

    artifact_sha256 = evidence.get("artifact_sha256")
    if not valid_sha256(artifact_sha256):
        add(
            errors,
            "INVALID_COMPUTE_EVIDENCE",
            f"artifact_sha256:{artifact_sha256}",
        )
        valid = False

    if not valid:
        return False

    root_fd: int | None = None
    try:
        root_fd = open_root_fd(root)
        snapshot = read_regular_file_at(root_fd, artifact_path)
    except Exception as error:
        add(
            errors,
            "INVALID_COMPUTE_EVIDENCE",
            f"artifact_unavailable:{artifact_path}:{error}",
        )
        return False
    finally:
        if root_fd is not None:
            os.close(root_fd)

    if snapshot.sha256 != artifact_sha256:
        add(
            errors,
            "STALE_COMPUTE_EVIDENCE",
            f"declared:{artifact_sha256};current:{snapshot.sha256}",
        )
        return False
    return True


def current_independent_audit(state: dict[str, Any]) -> bool:
    audit = state.get("independent_audit")
    if not isinstance(audit, dict):
        return False
    if audit.get("capability_available") is not True:
        return False
    authors = audit.get("author_agent_ids")
    reviewer = audit.get("reviewer_agent_id")
    if (
        not isinstance(authors, list)
        or not authors
        or not all(nonempty_string(author) for author in authors)
        or not nonempty_string(reviewer)
        or reviewer in authors
        or not nonempty_string(audit.get("reviewer_thread_id"))
        or audit.get("verdict") != "PASS"
    ):
        return False
    state_epoch = state.get("validation_epoch")
    state_bundle = state.get("claim_bundle_sha256")
    return (
        positive_integer(state_epoch)
        and audit.get("validation_epoch") == state_epoch
        and valid_sha256(state_bundle)
        and audit.get("audited_bundle_sha256") == state_bundle
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def validate_decision_log(
    root: Path,
    state: dict[str, Any],
    state_mtime: datetime | None,
    errors: list[str],
) -> set[str]:
    """校验 decision_log 的条目 schema、时间完整性与工件哈希登记。

    返回条目中出现过的状态集合（"BLOCKED@" 前缀已剥离），供 gate 完成
    记录交叉检查使用。
    """

    decision_log = state.get("decision_log")
    if not isinstance(decision_log, list):
        add(errors, "DECISION_LOG", "not_list")
        return set()

    tolerance = timedelta(seconds=300)
    now = datetime.now(timezone.utc)
    previous: datetime | None = None
    seen_states: set[str] = set()
    root_fd: int | None = None
    try:
        for index, entry in enumerate(decision_log):
            if not isinstance(entry, dict):
                add(errors, "DECISION_LOG_ENTRY_SCHEMA", f"index:{index}:not_object")
                continue
            raw_state = entry.get("state")
            base_state = (
                raw_state.removeprefix("BLOCKED@")
                if isinstance(raw_state, str)
                else raw_state
            )
            if base_state not in STATES:
                add(
                    errors,
                    "DECISION_LOG_UNKNOWN_STATE",
                    f"index:{index}:state:{raw_state!r}",
                )
            else:
                seen_states.add(base_state)
            if not nonempty(entry.get("action")):
                add(
                    errors,
                    "DECISION_LOG_ENTRY_SCHEMA",
                    f"index:{index}:empty_action",
                )
            timestamp = _parse_timestamp(entry.get("at"))
            if timestamp is None:
                add(
                    errors,
                    "DECISION_LOG_ENTRY_SCHEMA",
                    f"index:{index}:unparseable_at:{entry.get('at')!r}",
                )
            else:
                if previous is not None and timestamp < previous:
                    add(
                        errors,
                        "DECISION_LOG_NON_MONOTONIC",
                        f"index:{index}:at:{entry.get('at')}",
                    )
                if previous is None or timestamp > previous:
                    previous = timestamp
                if timestamp > now + tolerance:
                    add(
                        errors,
                        "FUTURE_DECISION_TIMESTAMP",
                        f"index:{index}:at:{entry.get('at')}",
                    )
                if state_mtime is not None and timestamp > state_mtime + tolerance:
                    add(
                        errors,
                        "DECISION_LOG_AFTER_STATE_WRITE",
                        f"index:{index}:at:{entry.get('at')};"
                        f"state_mtime:{state_mtime.isoformat()}",
                    )
            artifacts = entry.get("artifacts")
            if artifacts is None:
                continue
            if not isinstance(artifacts, list):
                add(
                    errors,
                    "DECISION_LOG_ENTRY_SCHEMA",
                    f"index:{index}:artifacts_not_list",
                )
                continue
            for artifact in artifacts:
                if (
                    not isinstance(artifact, dict)
                    or not canonical_relative_path(artifact.get("path"))
                    or not valid_sha256(artifact.get("sha256"))
                ):
                    add(
                        errors,
                        "DECISION_LOG_ENTRY_SCHEMA",
                        f"index:{index}:bad_artifact_entry:{artifact!r}",
                    )
                    continue
                if root_fd is None:
                    root_fd = open_root_fd(root)
                try:
                    snapshot = read_regular_file_at(root_fd, artifact["path"])
                except Exception as error:
                    add(
                        errors,
                        "STALE_DECISION_ARTIFACT",
                        f"index:{index}:unavailable:{artifact['path']}:{error}",
                    )
                    continue
                if snapshot.sha256 != artifact["sha256"]:
                    add(
                        errors,
                        "STALE_DECISION_ARTIFACT",
                        f"index:{index}:declared:{artifact['sha256']};"
                        f"current:{snapshot.sha256}",
                    )
    finally:
        if root_fd is not None:
            os.close(root_fd)

    updated = _parse_timestamp(state.get("updated_at"))
    if previous is not None and updated is not None and updated < previous:
        add(
            errors,
            "UPDATED_AT_BEFORE_DECISION_LOG",
            f"updated_at:{state.get('updated_at')};last_entry:{previous.isoformat()}",
        )
    return seen_states


def validate(
    root: Path,
    state: dict[str, Any],
    expected_year: int,
    state_mtime: datetime | None = None,
) -> list[str]:
    errors: list[str] = []

    for field in (
        "schema_version",
        "workflow_id",
        "updated_at",
        "next_required_action",
    ):
        if not nonempty(state.get(field)):
            add(errors, "FIELD", f"missing_or_empty:{field}")
    current_year = state.get("current_year")
    if current_year != expected_year:
        add(errors, "YEAR", f"current_year:{current_year};expected:{expected_year}")

    recent = state.get("recent_window")
    if not isinstance(recent, dict):
        add(errors, "RECENT_WINDOW", "missing_object")
        recent = {}
    if recent.get("start_year") != expected_year - 2:
        add(
            errors,
            "RECENT_WINDOW",
            f"start_year:{recent.get('start_year')};expected:{expected_year - 2}",
        )
    if recent.get("end_year") != expected_year:
        add(
            errors,
            "RECENT_WINDOW",
            f"end_year:{recent.get('end_year')};expected:{expected_year}",
        )
    if recent.get("status") not in {"INCOMPLETE", "COMPLETE"}:
        add(errors, "RECENT_WINDOW", f"invalid_status:{recent.get('status')}")
    if recent.get("snapshot_mode") not in SNAPSHOT_MODES:
        add(
            errors,
            "RECENT_WINDOW",
            f"invalid_snapshot_mode:{recent.get('snapshot_mode')}",
        )

    output_type = state.get("output_type")
    contract = state.get("contribution_contract")
    contribution = state.get("active_contribution")
    active_state = state.get("active_state")
    resume_state = state.get("resume_state")

    if output_type not in OUTPUT_TYPES:
        add(errors, "OUTPUT_TYPE", f"invalid:{output_type}")
    if contract not in CONTRACTS:
        add(errors, "CONTRACT", f"invalid:{contract}")
    if contribution not in CONTRIBUTIONS:
        add(errors, "CONTRIBUTION", f"invalid:{contribution}")
    if active_state not in STATES:
        add(errors, "STATE", f"invalid_active_state:{active_state}")
    if resume_state not in STATES:
        add(errors, "STATE", f"invalid_resume_state:{resume_state}")
    if state.get("search_mode") not in SEARCH_MODES:
        add(errors, "SEARCH_MODE", f"invalid:{state.get('search_mode')}")
    if state.get("compute_stage") not in COMPUTE_STAGES:
        add(errors, "COMPUTE", f"invalid_stage:{state.get('compute_stage')}")
    round_value = state.get("collision_round")
    if not isinstance(round_value, int) or round_value < 1:
        add(errors, "ROUND", f"invalid:{round_value}")

    if active_state == "BLOCKED":
        if resume_state not in RESUMABLE_STATES:
            add(errors, "STATE", f"blocked_invalid_resume:{resume_state}")
        reasons = state.get("blocked_reasons")
        if not isinstance(reasons, list) or not reasons:
            add(errors, "BLOCKED", "blocked_without_reason")
        elif not all(nonempty_string(reason) for reason in reasons):
            add(errors, "BLOCKED", "blocked_reason_not_nonempty_string")
        else:
            add(errors, "EXTERNAL_BLOCKER", ";".join(reasons))
        effective_state = resume_state
    else:
        if resume_state != active_state:
            add(
                errors,
                "STATE",
                f"resume_state:{resume_state};expected_active:{active_state}",
            )
        if state.get("blocked_reasons") not in ([], None):
            add(errors, "BLOCKED", "stale_blocked_reasons")
        effective_state = active_state

    unresolved_allowed = effective_state in {"BOOT", "SCOPE_LOCK"}
    if not unresolved_allowed and (
        output_type == "UNRESOLVED"
        or contract == "UNRESOLVED"
    ):
        add(errors, "SCOPE", "unresolved_after_scope_state")

    expected_contract = {
        "DOCTORAL_DISSERTATION": "THREE_ORGANIC_A_B_C",
        "JOURNAL_ARTICLE": "ONE_MAIN_M",
    }.get(output_type)
    if expected_contract and contract != expected_contract:
        add(
            errors,
            "CONTRACT",
            f"output_type:{output_type};contract:{contract};expected:{expected_contract}",
        )

    # 证据层级由 effective_state 派生（schema 3.0 起 active_layer 不再持久化）。
    tier = evidence_tier(str(effective_state))
    if tier in {"L1", "L2"}:
        if contribution != "NONE":
            add(errors, "CONTRIBUTION", f"tier:{tier};expected:NONE")
    else:
        allowed = (
            {"A", "B", "C"}
            if output_type == "DOCTORAL_DISSERTATION"
            else {"M"} if output_type == "JOURNAL_ARTICLE" else set()
        )
        if contribution not in allowed:
            add(
                errors,
                "CONTRIBUTION",
                f"tier:L3;output_type:{output_type};invalid:{contribution}",
            )

    gates = state.get("gates")
    if not isinstance(gates, dict):
        add(errors, "GATES", "missing_object")
        gates = {}
    for gate in sorted(GATE_KEYS):
        if not isinstance(gates.get(gate), bool):
            add(errors, "GATE", f"{gate}:not_boolean")
    for gate in sorted(gates):
        if gate not in GATE_KEYS:
            add(errors, "GATE", f"{gate}:unknown_key")

    implications = {
        "prior_claims_drained": ("scope_locked",),
        "recent_frontier_complete": ("scope_locked", "prior_claims_drained"),
        "literature_registry_valid": ("recent_frontier_complete",),
        "l1_frozen": ("literature_registry_valid",),
        "k_set_selected": ("l1_frozen",),
        "l2_frozen": ("k_set_selected",),
        "architecture_frozen": ("l2_frozen",),
        "k_fulltext_complete": ("architecture_frozen",),
        "k_claims_complete": ("k_fulltext_complete",),
        "output_claims_traced": ("k_claims_complete",),
        "evidence_validated": ("output_claims_traced",),
        "n0_4_locked": ("architecture_frozen", "evidence_validated"),
    }
    for gate, prerequisites in implications.items():
        if gates.get(gate):
            for prerequisite in prerequisites:
                if not gates.get(prerequisite):
                    add(errors, "GATE_ORDER", f"{gate}_requires:{prerequisite}")

    validity_rank = {"V0": 0, "V1": 1, "V2": 2, "V3": 3, "V4": 4}
    validity_level = state.get("validity_level")
    current_validity = (
        validity_rank.get(validity_level, -1)
        if isinstance(validity_level, str)
        else -1
    )
    novelty_level = state.get("novelty_level")
    compute_authorized = gates.get("compute_authorized") is True

    if not compute_authorized:
        for artifact in find_unregistered_compute_artifacts(root, state):
            add(errors, "UNREGISTERED_COMPUTE_ARTIFACT", f"path:{artifact}")
    validate_instance_probe_registry(root, state, errors)
    validate_l3_contract(root, state, errors)
    validate_composition_audit(root, state, errors)

    # R-LAYER-13：证据深度按段供给；超段超量取证即主次颠倒。
    tier = evidence_tier(str(effective_state))
    fulltext_budget, claim_budget = resolve_evidence_depth_budget(state, tier)
    fulltext_count, claim_count, scope_issues = count_current_evidence(root, state)
    for code, detail in scope_issues:
        add(errors, code, detail)
    if fulltext_count > fulltext_budget:
        add(
            errors,
            "EVIDENCE_DEPTH_EXCEEDS_LAYER",
            f"tier:{tier};fulltext:{fulltext_count}>budget:{fulltext_budget}",
        )
    if claim_count > claim_budget:
        add(
            errors,
            "EVIDENCE_DEPTH_EXCEEDS_LAYER",
            f"tier:{tier};atomic_claims:{claim_count}>budget:{claim_budget}",
        )

    if effective_state == "CLAIM_FREEZE" and novelty_level != "N0-4C":
        add(
            errors,
            "CLAIM_FREEZE_REQUIRES_N0_4C",
            f"novelty_level:{novelty_level}",
        )
    if effective_state == "VALIDITY_AUDIT" and current_validity < 1:
        add(
            errors,
            "VALIDITY_AUDIT_REQUIRES_V1",
            f"validity_level:{validity_level}",
        )
    if effective_state == "INDEPENDENT_REVIEW" and current_validity < 2:
        add(
            errors,
            "INDEPENDENT_REVIEW_REQUIRES_V2",
            f"validity_level:{validity_level}",
        )
    if effective_state == "DIRECTION_LOCK":
        if novelty_level != "N0-4C":
            add(
                errors,
                "DIRECTION_LOCK_REQUIRES_N0_4C",
                f"novelty_level:{novelty_level}",
            )
        if current_validity < 3:
            add(
                errors,
                "DIRECTION_LOCK_REQUIRES_V3",
                f"validity_level:{validity_level}",
            )
    if effective_state == "COMPUTE":
        if novelty_level != "N0-4C":
            add(
                errors,
                "COMPUTE_REQUIRES_N0_4C",
                f"novelty_level:{novelty_level}",
            )
        if current_validity < 3:
            add(
                errors,
                "COMPUTE_REQUIRES_V3",
                f"validity_level:{validity_level}",
            )
        if not compute_authorized:
            add(
                errors,
                "COMPUTE_REQUIRES_AUTHORIZATION",
                f"compute_authorized:{gates.get('compute_authorized')}",
            )
    if effective_state == "POSTCOMPUTE_CLAIM_FREEZE":
        evidence_current = validate_compute_evidence(root, state, errors)
        validate_data_sources(root, state, errors)
        validate_baseline_execution(root, state, errors)
        if (
            state.get("compute_stage") != "S4"
            or not compute_authorized
            or not evidence_current
        ):
            add(
                errors,
                "POSTCOMPUTE_CLAIM_FREEZE_REQUIRES_COMPLETED_AUTHORIZED_COMPUTE",
                "compute_stage:{};compute_authorized:{};evidence_current:{}".format(
                    state.get("compute_stage"),
                    gates.get("compute_authorized"),
                    evidence_current,
                ),
            )
    if effective_state == "FINAL_VALIDITY_AUDIT" and (
        not positive_integer(state.get("validation_epoch"))
        or state.get("validation_epoch") < 2
        or not valid_sha256(state.get("claim_bundle_sha256"))
    ):
        add(
            errors,
            "FINAL_VALIDITY_AUDIT_REQUIRES_NEW_EPOCH_CLAIM_BUNDLE",
            "validation_epoch:{};claim_bundle_sha256:{}".format(
                state.get("validation_epoch"), state.get("claim_bundle_sha256")
            ),
        )
    if effective_state == "FINAL_LOCK":
        if novelty_level != "N0-4C":
            add(
                errors,
                "FINAL_LOCK_REQUIRES_N0_4C",
                f"novelty_level:{novelty_level}",
            )
        if current_validity < 4:
            add(
                errors,
                "FINAL_LOCK_REQUIRES_V4",
                f"validity_level:{validity_level}",
            )
        state_audit = state.get("independent_audit")
        capability_unavailable = (
            isinstance(state_audit, dict)
            and state_audit.get("capability_available") is False
        )
        if not capability_unavailable and not current_independent_audit(state):
            add(
                errors,
                "FINAL_LOCK_REQUIRES_CURRENT_INDEPENDENT_AUDIT",
                "audit_not_current_for_state_epoch_and_bundle",
            )

    if gates.get("recent_frontier_complete"):
        if recent.get("status") != "COMPLETE":
            add(errors, "RECENT_WINDOW", "gate_true_but_status_not_complete")
        if recent.get("snapshot_mode") not in {
            "NEW_SEARCH",
            "REUSED_VERIFIED_SNAPSHOT",
        }:
            add(errors, "RECENT_WINDOW", "complete_without_valid_snapshot_mode")

    prerequisites = STATE_PREREQUISITES.get(str(effective_state), ())
    for gate in prerequisites:
        if not gates.get(gate):
            add(errors, "STATE_GATE", f"{effective_state}_requires:{gate}")

    compute_stage = state.get("compute_stage")
    if compute_stage not in {"NOT_STARTED", "STOPPED"}:
        if gates.get("compute_authorized") is not True:
            add(errors, "COMPUTE", "started_without_authorization")
    if effective_state == "COMPUTE" and compute_stage in {"NOT_STARTED", "STOPPED"}:
        add(errors, "COMPUTE", f"active_compute_invalid_stage:{compute_stage}")

    artifacts = state.get("artifacts")
    if not isinstance(artifacts, dict):
        add(errors, "ARTIFACT", "missing_object")
        artifacts = {}
    checked: set[str] = set()
    for gate, artifact_keys in GATE_ARTIFACTS.items():
        if not gates.get(gate):
            continue
        for key in artifact_keys:
            if key in checked:
                continue
            checked.add(key)
            path = resolve_artifact(root, artifacts.get(key))
            if path is None:
                add(errors, "ARTIFACT", f"{key}:missing_or_unsafe_path")
            elif not path.exists():
                add(errors, "ARTIFACT", f"{key}:not_found:{path}")
            elif key == "literature_archive" and not path.is_dir():
                add(errors, "ARTIFACT", f"{key}:not_directory:{path}")
            elif key != "literature_archive" and not path.is_file():
                add(errors, "ARTIFACT", f"{key}:not_file:{path}")

    seen_states = validate_decision_log(root, state, state_mtime, errors)

    # gate 置真必须有对应状态的完成记录，否则视为自报置真。
    for gate, completion_state in GATE_COMPLETION_STATE.items():
        if gates.get(gate) and completion_state not in seen_states:
            add(
                errors,
                "GATE_COMPLETION_RECORD_MISSING",
                f"{gate}:requires_decision_log_state:{completion_state}",
            )

    # level 不得手填：N0-4C 与 n0_4_locked 必须互证。
    if (novelty_level == "N0-4C") != bool(gates.get("n0_4_locked")):
        add(
            errors,
            "SELF_DECLARED_LEVEL",
            f"novelty_level:{novelty_level};n0_4_locked:{gates.get('n0_4_locked')}",
        )

    # R-N0-17：novelty-audit 必须含与 novelty_level 对应的裁决证据（正面/负面同价）。
    validate_novelty_verdict_evidence(root, state, errors)

    validate_sealed_confirmation(root, state, errors)

    # COMPLETE 是终态，必须满足与 FINAL_LOCK 等价的条件。
    if effective_state == "COMPLETE":
        complete_problems: list[str] = []
        if novelty_level != "N0-4C":
            complete_problems.append(f"novelty_level:{novelty_level}")
        if current_validity < 4:
            complete_problems.append(f"validity_level:{validity_level}")
        state_audit = state.get("independent_audit")
        capability_unavailable = (
            isinstance(state_audit, dict)
            and state_audit.get("capability_available") is False
        )
        if not capability_unavailable and not current_independent_audit(state):
            complete_problems.append("independent_audit:not_current")
        if complete_problems:
            add(
                errors,
                "COMPLETE_REQUIRES_FINAL_LOCK_CONDITIONS",
                ";".join(complete_problems),
            )

    # gate 收口：scope 单调、next_required_action 一致性、capability 翻转 provenance。
    validate_evidence_scope_monotonic(root, state, errors)
    validate_next_action_consistent(state, errors)
    validate_capability_flip_provenance(state, errors)
    validate_atomic_claim_quality(root, state, errors)

    return errors


def issue_severity(code: str, strict_new_checks: bool) -> str:
    if code == "EXTERNAL_BLOCKER":
        return "BLOCKED"
    if code in NEW_CHECK_CODES and not strict_new_checks:
        return "WARNING"
    return "INVALID"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--current-year", type=int, default=datetime.now().year)
    parser.add_argument("--strict-new-checks", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    state_path = args.state.resolve()
    try:
        state_path.relative_to(root)
    except ValueError:
        print("workflow_state_errors=1")
        print(f"STATE_PATH\toutside_root:{state_path}")
        return 1

    try:
        state = load_json(state_path)
    except Exception as error:
        issues = [Issue("VALIDATOR_ERROR", "INVALID", "workflow_state", str(error))]
        print(render("workflow_state", issues))
        return int(choose_exit(issues))

    schema_issues = validate_schema_v2(root, state)
    if any(issue.severity == "MIGRATION" for issue in schema_issues):
        print(render("workflow_state", schema_issues))
        return int(choose_exit(schema_issues))

    try:
        state_mtime = datetime.fromtimestamp(
            state_path.stat().st_mtime, tz=timezone.utc
        )
    except OSError:
        state_mtime = None

    try:
        errors = validate(root, state, args.current_year, state_mtime)
    except Exception as error:
        errors = []
        schema_issues.append(
            Issue("VALIDATOR_ERROR", "INVALID", "workflow_state", str(error))
        )
    issues = schema_issues + [
        Issue(
            error.split("\t", 1)[0],
            issue_severity(error.split("\t", 1)[0], args.strict_new_checks),
            "workflow_state",
            error.split("\t", 1)[1] if "\t" in error else error,
        )
        for error in errors
    ]
    print(render("workflow_state", issues))
    return int(choose_exit(issues))


if __name__ == "__main__":
    raise SystemExit(main())
