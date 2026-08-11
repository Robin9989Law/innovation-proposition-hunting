#!/usr/bin/env python3
"""Validate the executable state machine for innovation-proposition-hunting."""

from __future__ import annotations

import argparse
import json
import os
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
)
from validate_artifact_hashes import valid_sha256
from validate_schema_v2 import validate as validate_schema_v2


STATES = {
    "BOOT",
    "SCOPE_LOCK",
    "PRIOR_CLAIM_DRAIN",
    "RECENT_FRONTIER",
    "LITERATURE_REGISTER",
    "IMPORTANT_FULLTEXT",
    "SOURCE_CLAIM_REGISTER",
    "SYNTHESIZE_COLLISION",
    "OUTPUT_CLAIM_BIND",
    "EVIDENCE_VALIDATE",
    "LAYER_DECISION",
    "N0_AUDIT",
    "CLAIM_FREEZE",
    "VALIDITY_AUDIT",
    "INDEPENDENT_REVIEW",
    "DIRECTION_LOCK",
    "COMPUTE",
    "POSTCOMPUTE_CLAIM_FREEZE",
    "FINAL_VALIDITY_AUDIT",
    "FINAL_LOCK",
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
LAYERS = {"UNRESOLVED", "L1", "L2", "ARCHITECTURE", "L3"}
CONTRIBUTIONS = {"NONE", "M", "A", "B", "C"}
SEARCH_MODES = {"SEARCH_OPEN", "SYNTHESIS_LOCK", "EXCEPTION_REOPEN"}
COMPUTE_STAGES = {"NOT_STARTED", "S0", "S1", "S2", "S3", "S4", "STOPPED"}
SNAPSHOT_MODES = {"NOT_SET", "NEW_SEARCH", "REUSED_VERIFIED_SNAPSHOT"}
GATE_KEYS = {
    "scope_locked",
    "prior_claims_drained",
    "recent_frontier_complete",
    "literature_registry_valid",
    "important_fulltext_complete",
    "source_claims_complete",
    "output_claims_traced",
    "evidence_validated",
    "l1_frozen",
    "l2_frozen",
    "architecture_frozen",
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
    "IMPORTANT_FULLTEXT": (
        "scope_locked",
        "prior_claims_drained",
        "recent_frontier_complete",
        "literature_registry_valid",
    ),
    "SOURCE_CLAIM_REGISTER": (
        "scope_locked",
        "prior_claims_drained",
        "recent_frontier_complete",
        "literature_registry_valid",
        "important_fulltext_complete",
    ),
    "SYNTHESIZE_COLLISION": (
        "scope_locked",
        "prior_claims_drained",
        "recent_frontier_complete",
        "literature_registry_valid",
        "important_fulltext_complete",
        "source_claims_complete",
    ),
    "OUTPUT_CLAIM_BIND": (
        "scope_locked",
        "prior_claims_drained",
        "recent_frontier_complete",
        "literature_registry_valid",
        "important_fulltext_complete",
        "source_claims_complete",
    ),
    "EVIDENCE_VALIDATE": (
        "scope_locked",
        "prior_claims_drained",
        "recent_frontier_complete",
        "literature_registry_valid",
        "important_fulltext_complete",
        "source_claims_complete",
        "output_claims_traced",
    ),
    "LAYER_DECISION": ("scope_locked", "evidence_validated"),
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
    "literature_registry_valid": ("literature_registry",),
    "important_fulltext_complete": ("literature_archive",),
    "source_claims_complete": ("claim_registry",),
    "output_claims_traced": ("output_support",),
    "evidence_validated": (
        "literature_registry",
        "claim_registry",
        "output_support",
        "validation_log",
    ),
    "l1_frozen": ("l1_card",),
    "l2_frozen": ("l2_card",),
    "architecture_frozen": ("contribution_architecture",),
    "n0_4_locked": ("hierarchy_novelty_audit",),
}

# gate -> 置真该 gate 的状态。置真必须能在 decision_log 中找到对应状态的完成
# 记录（条目 state 允许 "BLOCKED@<STATE>" 形式），否则视为"自报置真"。
GATE_COMPLETION_STATE = {
    "scope_locked": "SCOPE_LOCK",
    "prior_claims_drained": "PRIOR_CLAIM_DRAIN",
    "recent_frontier_complete": "RECENT_FRONTIER",
    "literature_registry_valid": "LITERATURE_REGISTER",
    "important_fulltext_complete": "IMPORTANT_FULLTEXT",
    "source_claims_complete": "SOURCE_CLAIM_REGISTER",
    "output_claims_traced": "OUTPUT_CLAIM_BIND",
    "evidence_validated": "EVIDENCE_VALIDATE",
    "l1_frozen": "LAYER_DECISION",
    "l2_frozen": "LAYER_DECISION",
    "architecture_frozen": "LAYER_DECISION",
    "n0_4_locked": "N0_AUDIT",
}

TRACK_STATES = {
    "NOVELTY": {
        "BOOT",
        "SCOPE_LOCK",
        "PRIOR_CLAIM_DRAIN",
        "RECENT_FRONTIER",
        "LITERATURE_REGISTER",
        "IMPORTANT_FULLTEXT",
        "SOURCE_CLAIM_REGISTER",
        "SYNTHESIZE_COLLISION",
        "OUTPUT_CLAIM_BIND",
        "EVIDENCE_VALIDATE",
        "LAYER_DECISION",
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
        "TRACK_STATE_MISMATCH",
        "LAST_COMPLETED_NOT_LOGGED",
        "COMPLETE_REQUIRES_FINAL_LOCK_CONDITIONS",
        "UNREGISTERED_COMPUTE_ARTIFACT",
    }
)


# compute_authorized=false 时视为"未授权计算产物"的路径模式（根相对 glob）。
COMPUTE_ARTIFACT_GLOBS = ("s0_*", "s0_outputs/**/*")


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
    layer = state.get("active_layer")
    contribution = state.get("active_contribution")
    active_state = state.get("active_state")
    resume_state = state.get("resume_state")

    if output_type not in OUTPUT_TYPES:
        add(errors, "OUTPUT_TYPE", f"invalid:{output_type}")
    if contract not in CONTRACTS:
        add(errors, "CONTRACT", f"invalid:{contract}")
    if layer not in LAYERS:
        add(errors, "LAYER", f"invalid:{layer}")
    if contribution not in CONTRIBUTIONS:
        add(errors, "CONTRIBUTION", f"invalid:{contribution}")
    if active_state not in STATES:
        add(errors, "STATE", f"invalid_active_state:{active_state}")
    if resume_state not in STATES:
        add(errors, "STATE", f"invalid_resume_state:{resume_state}")
    if state.get("last_completed_state") not in STATES | {"NONE"}:
        add(
            errors,
            "STATE",
            f"invalid_last_completed:{state.get('last_completed_state')}",
        )
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
        or layer == "UNRESOLVED"
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

    if layer in {"L1", "L2", "ARCHITECTURE", "UNRESOLVED"}:
        if contribution != "NONE":
            add(errors, "CONTRIBUTION", f"layer:{layer};expected:NONE")
    elif layer == "L3":
        allowed = (
            {"A", "B", "C"}
            if output_type == "DOCTORAL_DISSERTATION"
            else {"M"} if output_type == "JOURNAL_ARTICLE" else set()
        )
        if contribution not in allowed:
            add(
                errors,
                "CONTRIBUTION",
                f"layer:L3;output_type:{output_type};invalid:{contribution}",
            )

    gates = state.get("gates")
    if not isinstance(gates, dict):
        add(errors, "GATES", "missing_object")
        gates = {}
    for gate in sorted(GATE_KEYS):
        if not isinstance(gates.get(gate), bool):
            add(errors, "GATE", f"{gate}:not_boolean")

    implications = {
        "prior_claims_drained": ("scope_locked",),
        "recent_frontier_complete": ("scope_locked", "prior_claims_drained"),
        "literature_registry_valid": ("recent_frontier_complete",),
        "important_fulltext_complete": ("literature_registry_valid",),
        "source_claims_complete": ("important_fulltext_complete",),
        "output_claims_traced": ("source_claims_complete",),
        "evidence_validated": ("output_claims_traced",),
        "l2_frozen": ("l1_frozen",),
        "architecture_frozen": ("l1_frozen", "l2_frozen"),
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

    if layer == "L2" and not gates.get("l1_frozen"):
        add(errors, "LAYER_GATE", "L2_requires:l1_frozen")
    if layer == "ARCHITECTURE" and not gates.get("l2_frozen"):
        add(errors, "LAYER_GATE", "ARCHITECTURE_requires:l2_frozen")
    if layer == "L3" and not gates.get("architecture_frozen"):
        add(errors, "LAYER_GATE", "L3_requires:architecture_frozen")
    if effective_state == "N0_AUDIT" and layer != "L3":
        add(errors, "STATE_LAYER", "N0_AUDIT_requires:L3")

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

    # active_track 与 active_state 必须同轴。
    track = state.get("active_track")
    if (
        isinstance(track, str)
        and track in TRACK_STATES
        and effective_state != "COMPLETE"
        and effective_state not in TRACK_STATES[track]
    ):
        add(
            errors,
            "TRACK_STATE_MISMATCH",
            f"active_track:{track};effective_state:{effective_state}",
        )

    # last_completed_state 必须在 decision_log 中有对应完成记录。
    last_completed = state.get("last_completed_state")
    if (
        seen_states
        and isinstance(last_completed, str)
        and last_completed != "NONE"
        and last_completed not in seen_states
    ):
        add(
            errors,
            "LAST_COMPLETED_NOT_LOGGED",
            f"last_completed_state:{last_completed}",
        )

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
