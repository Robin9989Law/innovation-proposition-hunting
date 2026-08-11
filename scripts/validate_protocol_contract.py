#!/usr/bin/env python3
"""Validate frozen algorithm protocols, chronology evidence and fair budgets."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
from typing import Any, Callable

from validation_common import (
    ALGORITHM_CLAIM_TYPES,
    CLAIM_TYPES,
    Issue,
    ProjectContext,
    SafeFileSnapshot,
    StrictJSONError,
    UnsafePathError,
    canonical_relative_path,
    choose_exit,
    lexical_relative_cli_path,
    nonempty_string,
    open_root_fd,
    positive_integer,
    read_regular_file_at,
    render,
    strict_json_load_bytes,
    string_list,
)
from python_test_contract import (
    canonical_identifier,
    parse_python_test_contract,
    python_top_level_symbol_status,
    self_attesting_test_issues,
)


ALGORITHM_PROFILES = {"ALGORITHM", "MIXED"}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
PREDICTION_UNITS = {"SAMPLE", "BATCH", "BLOCK", "SEQUENCE"}
UPDATE_UNITS = {"SAMPLE", "BATCH", "BLOCK", "NONE"}
PREDICT_UPDATE_ORDERS = {
    "PREDICT_THEN_UPDATE",
    "PREDICT_ONLY",
    "BATCH_PREDICT_THEN_UPDATE",
    "BLOCK_PREDICT_THEN_UPDATE",
}
LABEL_AVAILABILITY = {
    "NEVER",
    "TRAIN_ONLY",
    "AFTER_EACH_PREDICTION",
    "AFTER_BATCH",
    "AFTER_BLOCK",
}
CHRONOLOGICAL_ORDERINGS = {
    "STRICT_EVENT_TIME",
    "INDEX_ORDER",
    "NOT_APPLICABLE",
}
SPLIT_STRATEGIES = {
    "CHRONOLOGICAL_HOLDOUT",
    "ROLLING_ORIGIN",
    "PREQUENTIAL",
    "FIXED_HOLDOUT",
}
HYPERPARAMETER_ROLES = {"TRAIN_ONLY", "DEVELOPMENT_ONLY"}
DEVELOPMENT_ROLES = {"DEVELOPMENT_ONLY", "TRAIN_AND_DEVELOPMENT"}
SEALED_ROLES = {"SEALED_CONFIRMATION_ONLY", "NOT_YET_ACCESSED"}
EVALUATION_ROLES = {"CONFIRMATORY", "NON_CONFIRMATORY"}
REQUIRED_PROTOCOL_FIELDS = (
    "prediction_unit",
    "update_unit",
    "predict_update_order",
    "label_availability",
    "chronological_ordering",
    "split_strategy",
    "hyperparameter_selection_data",
    "development_data",
    "sealed_confirmation_data",
    "test_access_count",
    "update_semantics",
)
REQUIRED_ADAPTATION_FIELDS = (
    "uses_test_labels",
    "supervised_online_adaptation",
    "pre_update_scoring",
    "operational_label_availability",
    "evaluation_role",
)
REQUIRED_CHRONOLOGY_FIELDS = (
    "command",
    "status",
    "exit_code",
    "output_file",
    "output_sha256",
    "target_claim_ids",
    "implementation_relative_path",
    "implementation_symbol",
    "implementation_sha256",
)


def strict_object_from_snapshot(data: bytes, label: str) -> dict[str, Any]:
    payload = strict_json_load_bytes(data)
    if not isinstance(payload, dict):
        raise TypeError(f"{label}:top_level_not_object")
    return payload


# 文件快照读取函数签名：与 ProjectContext.snapshot 一致。单次校验运行内
# 可按 (路径, include_data) 缓存，避免按 binding 重复读盘/重哈希。
SnapshotReader = Callable[..., SafeFileSnapshot]


def load_object(
    root_fd: int,
    relative_path: str,
    label: str,
    *,
    required: bool = True,
) -> tuple[dict[str, Any] | None, list[Issue]]:
    try:
        snapshot = read_regular_file_at(root_fd, relative_path, include_data=True)
    except FileNotFoundError:
        if not required:
            return None, []
        return None, [
            Issue(f"{label.upper()}_REQUIRED", "INVALID", label, relative_path)
        ]
    except UnsafePathError as error:
        return None, [Issue("VALIDATOR_ERROR", "INVALID", label, str(error))]
    except OSError as error:
        return None, [
            Issue("VALIDATOR_ERROR", "INVALID", label, type(error).__name__)
        ]
    assert snapshot.data is not None
    try:
        return strict_object_from_snapshot(snapshot.data, label), []
    except (StrictJSONError, TypeError) as error:
        return None, [
            Issue(f"INVALID_{label.upper()}_JSON", "INVALID", label, str(error))
        ]


def load_object_via_ctx(
    ctx: ProjectContext,
    relative_path: str,
    label: str,
    *,
    required: bool = True,
) -> tuple[dict[str, Any] | None, list[Issue]]:
    """load_object 的 ctx 版本：JSON 读取走 ProjectContext 的缓存。

    错误码与文本和 load_object 逐条对齐，仅读取通道不同。
    """

    try:
        payload = ctx.load_json(relative_path, label)
    except FileNotFoundError:
        if not required:
            return None, []
        return None, [
            Issue(f"{label.upper()}_REQUIRED", "INVALID", label, relative_path)
        ]
    except UnsafePathError as error:
        return None, [Issue("VALIDATOR_ERROR", "INVALID", label, str(error))]
    except OSError as error:
        return None, [
            Issue("VALIDATOR_ERROR", "INVALID", label, type(error).__name__)
        ]
    except (StrictJSONError, TypeError) as error:
        return None, [
            Issue(f"INVALID_{label.upper()}_JSON", "INVALID", label, str(error))
        ]
    return payload, []


def is_algorithm_claim_type(value: Any) -> bool:
    return isinstance(value, str) and value in ALGORITHM_CLAIM_TYPES


def collect_algorithm_claims(
    inventory: dict[str, Any], state_epoch: Any
) -> tuple[dict[str, dict[str, Any]], list[Issue]]:
    issues: list[Issue] = []
    if inventory.get("schema_version") != "2.0":
        issues.append(
            Issue(
                "INVALID_CLAIM_INVENTORY",
                "INVALID",
                "claim_inventory",
                f"schema_version:{inventory.get('schema_version')}",
            )
        )
    inventory_epoch = inventory.get("validation_epoch")
    if not positive_integer(inventory_epoch):
        issues.append(
            Issue(
                "INVALID_CLAIM_INVENTORY",
                "INVALID",
                "claim_inventory",
                "validation_epoch:expected_positive_integer",
            )
        )
    elif positive_integer(state_epoch) and inventory_epoch != state_epoch:
        issues.append(
            Issue(
                "VALIDATION_EPOCH_MISMATCH",
                "INVALID",
                "claim_inventory",
                f"inventory:{inventory_epoch};state:{state_epoch}",
            )
        )
    raw_claims = inventory.get("claims")
    if not isinstance(raw_claims, list):
        issues.append(
            Issue(
                "INVALID_CLAIM_INVENTORY",
                "INVALID",
                "claim_inventory",
                "claims:expected_list",
            )
        )
        return {}, issues
    claims: dict[str, dict[str, Any]] = {}
    claim_ids: list[str] = []
    for index, claim in enumerate(raw_claims):
        if not isinstance(claim, dict):
            issues.append(
                Issue(
                    "INVALID_CLAIM_INVENTORY",
                    "INVALID",
                    f"claim[{index}]",
                    "expected_object",
                )
            )
            continue
        claim_type = claim.get("claim_type")
        if not isinstance(claim_type, str) or claim_type not in CLAIM_TYPES:
            issues.append(
                Issue(
                    "INVALID_CLAIM_TYPE",
                    "INVALID",
                    str(claim.get("claim_id", f"claim[{index}]")),
                    f"claim_type:unknown:{claim_type}",
                )
            )
            continue
        if not is_algorithm_claim_type(claim_type):
            continue
        claim_id = claim.get("claim_id")
        if not nonempty_string(claim_id) or claim_id.strip() != claim_id:
            issues.append(
                Issue(
                    "INVALID_ALGORITHM_CLAIM",
                    "INVALID",
                    f"claim[{index}]",
                    "claim_id:expected_canonical_nonempty_string",
                )
            )
            continue
        claim_ids.append(claim_id)
        claims.setdefault(claim_id, claim)
    for claim_id, count in Counter(claim_ids).items():
        if count > 1:
            issues.append(
                Issue(
                    "DUPLICATE_ALGORITHM_CLAIM_ID",
                    "INVALID",
                    claim_id,
                    f"count:{count}",
                )
            )
    return claims, issues


def validate_protocol_fields(protocol: dict[str, Any], state_epoch: Any) -> list[Issue]:
    issues: list[Issue] = []
    if protocol.get("schema_version") != "2.0":
        issues.append(
            Issue(
                "INVALID_PROTOCOL_FIELD",
                "INVALID",
                "protocol_contract",
                f"schema_version:{protocol.get('schema_version')}",
            )
        )
    epoch = protocol.get("validation_epoch")
    if not positive_integer(epoch):
        issues.append(
            Issue(
                "INVALID_PROTOCOL_FIELD",
                "INVALID",
                "protocol_contract",
                "validation_epoch:expected_positive_integer",
            )
        )
    elif positive_integer(state_epoch) and epoch != state_epoch:
        issues.append(
            Issue(
                "VALIDATION_EPOCH_MISMATCH",
                "INVALID",
                "protocol_contract",
                f"protocol:{epoch};state:{state_epoch}",
            )
        )
    for field in REQUIRED_PROTOCOL_FIELDS:
        if field not in protocol:
            issues.append(
                Issue(
                    "INVALID_PROTOCOL_FIELD",
                    "INVALID",
                    "protocol_contract",
                    f"missing:{field}",
                )
            )
    enums = (
        ("prediction_unit", PREDICTION_UNITS),
        ("update_unit", UPDATE_UNITS),
        ("predict_update_order", PREDICT_UPDATE_ORDERS),
        ("label_availability", LABEL_AVAILABILITY),
        ("chronological_ordering", CHRONOLOGICAL_ORDERINGS),
        ("split_strategy", SPLIT_STRATEGIES),
        ("hyperparameter_selection_data", HYPERPARAMETER_ROLES),
        ("development_data", DEVELOPMENT_ROLES),
        ("sealed_confirmation_data", SEALED_ROLES),
    )
    for field, allowed in enums:
        if field in protocol:
            value = protocol.get(field)
            if not isinstance(value, str) or value not in allowed:
                issues.append(
                    Issue(
                        "INVALID_PROTOCOL_FIELD",
                        "INVALID",
                        "protocol_contract",
                        f"{field}:invalid_value:{value}",
                    )
                )
    accesses = protocol.get("test_access_count")
    if "test_access_count" in protocol and (
        isinstance(accesses, bool) or not isinstance(accesses, int) or accesses < 0
    ):
        issues.append(
            Issue(
                "INVALID_PROTOCOL_FIELD",
                "INVALID",
                "protocol_contract",
                "test_access_count:expected_nonnegative_integer",
            )
        )

    semantics = protocol.get("update_semantics")
    if "update_semantics" in protocol and not isinstance(semantics, dict):
        issues.append(
            Issue(
                "INVALID_PROTOCOL_FIELD",
                "INVALID",
                "protocol_contract",
                "update_semantics:expected_object",
            )
        )
    elif isinstance(semantics, dict):
        for field in REQUIRED_ADAPTATION_FIELDS:
            if field not in semantics:
                issues.append(
                    Issue(
                        "INVALID_PROTOCOL_FIELD",
                        "INVALID",
                        "update_semantics",
                        f"missing:{field}",
                    )
                )
        for field in REQUIRED_ADAPTATION_FIELDS[:-1]:
            if field in semantics and type(semantics.get(field)) is not bool:
                issues.append(
                    Issue(
                        "INVALID_PROTOCOL_FIELD",
                        "INVALID",
                        "update_semantics",
                        f"{field}:expected_boolean",
                    )
                )
        role = semantics.get("evaluation_role")
        if "evaluation_role" in semantics and (
            not isinstance(role, str) or role not in EVALUATION_ROLES
        ):
            issues.append(
                Issue(
                    "INVALID_PROTOCOL_FIELD",
                    "INVALID",
                    "update_semantics",
                    f"evaluation_role:invalid_value:{role}",
                )
            )
        if semantics.get("uses_test_labels") is True:
            valid_adaptation = (
                semantics.get("supervised_online_adaptation") is True
                and semantics.get("pre_update_scoring") is True
                and semantics.get("operational_label_availability") is True
                and semantics.get("evaluation_role") == "NON_CONFIRMATORY"
                and protocol.get("label_availability")
                in {"AFTER_EACH_PREDICTION", "AFTER_BATCH", "AFTER_BLOCK"}
            )
            if not valid_adaptation:
                issues.append(
                    Issue(
                        "INVALID_TEST_LABEL_UPDATE",
                        "INVALID",
                        "update_semantics",
                        "requires_supervised_online_adaptation,pre_update_scoring,"
                        "operational_label_availability,and_non_confirmatory_role",
                    )
                )
        expected_modes = {
            "SAMPLE": ("SAMPLE", "PREDICT_THEN_UPDATE", "AFTER_EACH_PREDICTION"),
            "BATCH": ("BATCH", "BATCH_PREDICT_THEN_UPDATE", "AFTER_BATCH"),
            "BLOCK": ("BLOCK", "BLOCK_PREDICT_THEN_UPDATE", "AFTER_BLOCK"),
            "SEQUENCE": ("NONE", "PREDICT_ONLY", "NEVER"),
        }
        prediction_unit = protocol.get("prediction_unit")
        if prediction_unit in expected_modes:
            expected_update, expected_order, expected_label = expected_modes[prediction_unit]
            if (
                protocol.get("update_unit") != expected_update
                or protocol.get("predict_update_order") != expected_order
            ):
                issues.append(
                    Issue(
                        "INVALID_PROTOCOL_MATRIX",
                        "INVALID",
                        "protocol_contract",
                        f"{prediction_unit}:requires:{expected_update}:{expected_order}",
                    )
                )
            if prediction_unit == "SEQUENCE" and (
                protocol.get("label_availability") != expected_label
                or semantics.get("uses_test_labels") is not False
                or semantics.get("supervised_online_adaptation") is not False
                or semantics.get("operational_label_availability") is not False
            ):
                issues.append(
                    Issue(
                        "INVALID_PROTOCOL_MATRIX",
                        "INVALID",
                        "update_semantics",
                        "SEQUENCE:requires_no_labels_or_adaptation",
                    )
                )
            if (
                semantics.get("uses_test_labels") is True
                or semantics.get("supervised_online_adaptation") is True
            ) and protocol.get("label_availability") != expected_label:
                issues.append(
                    Issue(
                        "INVALID_PROTOCOL_MATRIX",
                        "INVALID",
                        "update_semantics",
                        f"{prediction_unit}:supervised_label_requires:{expected_label}",
                    )
                )
        availability = protocol.get("label_availability")
        operational_expected = availability in {
            "AFTER_EACH_PREDICTION",
            "AFTER_BATCH",
            "AFTER_BLOCK",
        }
        if (
            type(semantics.get("operational_label_availability")) is bool
            and semantics.get("operational_label_availability")
            is not operational_expected
        ):
            issues.append(
                Issue(
                    "INVALID_PROTOCOL_MATRIX",
                    "INVALID",
                    "update_semantics",
                    "operational_label_availability_disagrees_with_label_availability",
                )
            )
        if semantics.get("supervised_online_adaptation") is True and (
            semantics.get("uses_test_labels") is not True
            or availability == "NEVER"
        ):
            issues.append(
                Issue(
                    "INVALID_PROTOCOL_MATRIX",
                    "INVALID",
                    "update_semantics",
                    "supervised_online_adaptation_requires_test_labels_and_available_labels",
                )
            )
    return issues


def chronology_issue(detail: str, item_id: str = "chronology_test") -> Issue:
    return Issue("ONLINE_CHRONOLOGY_UNVERIFIED", "INVALID", item_id, detail)


def validate_chronology(
    snapshot_fn: SnapshotReader,
    protocol: dict[str, Any],
    algorithm_claims: dict[str, dict[str, Any]],
    trace: dict[str, Any] | None,
) -> list[Issue]:
    if protocol.get("prediction_unit") != "SAMPLE":
        return []
    issues: list[Issue] = []
    if protocol.get("update_unit") != "SAMPLE":
        issues.append(chronology_issue("sample_prediction_requires_sample_update_unit"))
    if protocol.get("predict_update_order") != "PREDICT_THEN_UPDATE":
        issues.append(chronology_issue("sample_prediction_requires_predict_then_update"))
    chronology = protocol.get("chronology_test")
    if not isinstance(chronology, dict):
        return issues + [chronology_issue("chronology_test:missing_or_invalid_object")]
    for field in REQUIRED_CHRONOLOGY_FIELDS:
        if field not in chronology:
            issues.append(chronology_issue(f"missing:{field}"))
    if not nonempty_string(chronology.get("command")):
        issues.append(chronology_issue("command:expected_nonempty_string"))
    if chronology.get("status") != "PASS":
        issues.append(chronology_issue(f"status:expected_PASS;found:{chronology.get('status')}"))
    exit_code = chronology.get("exit_code")
    if type(exit_code) is not int:
        issues.append(
            Issue(
                "INVALID_EXIT_CODE_TYPE",
                "INVALID",
                "chronology_test",
                f"exit_code:expected_integer;found:{type(exit_code).__name__}",
            )
        )
    elif exit_code != 0:
        issues.append(chronology_issue(f"exit_code:expected_0;found:{exit_code}"))
    target_ids = chronology.get("target_claim_ids")
    if not string_list(target_ids) or not all(
        canonical_identifier(target) for target in target_ids
    ):
        issues.append(
            chronology_issue(
                "target_claim_ids:expected_nonempty_canonical_string_list"
            )
        )
        target_ids = []
    elif len(set(target_ids)) != len(target_ids):
        issues.append(chronology_issue("target_claim_ids:duplicates"))
    missing_targets = sorted(set(algorithm_claims) - set(target_ids))
    if missing_targets:
        issues.append(chronology_issue(f"missing_algorithm_claims:{','.join(missing_targets)}"))
    orphan_targets = sorted(set(target_ids) - set(algorithm_claims))
    if orphan_targets:
        issues.append(chronology_issue(f"orphan_algorithm_claims:{','.join(orphan_targets)}"))

    trace_bindings: dict[str, list[dict[str, Any]]] = {}
    if isinstance(trace, dict):
        raw_traces = trace.get("traces")
        if isinstance(raw_traces, list):
            for binding in raw_traces:
                if not isinstance(binding, dict) or not canonical_identifier(
                    binding.get("claim_id")
                ):
                    continue
                trace_bindings.setdefault(binding["claim_id"], []).append(binding)

    output_path = chronology.get("output_file")
    output_hash = chronology.get("output_sha256")
    implementation_path = chronology.get("implementation_relative_path")
    implementation_symbol = chronology.get("implementation_symbol")
    implementation_hash = chronology.get("implementation_sha256")
    for field, value in (
        ("output_file", output_path),
        ("implementation_relative_path", implementation_path),
    ):
        if not canonical_relative_path(value):
            issues.append(chronology_issue(f"{field}:unsafe_or_noncanonical"))
    for field, value in (
        ("output_sha256", output_hash),
        ("implementation_sha256", implementation_hash),
    ):
        if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
            issues.append(chronology_issue(f"{field}:expected_lowercase_sha256"))
    if not canonical_identifier(implementation_symbol):
        issues.append(chronology_issue("implementation_symbol:expected_canonical_identifier"))

    implementation_snapshot = None
    if canonical_relative_path(implementation_path):
        try:
            implementation_snapshot = snapshot_fn(
                implementation_path, include_data=True
            )
        except (FileNotFoundError, UnsafePathError, OSError) as error:
            issues.append(
                chronology_issue(
                    f"implementation_unavailable:{type(error).__name__}:{error}"
                )
            )
        else:
            if (
                isinstance(implementation_hash, str)
                and implementation_snapshot.sha256 != implementation_hash
            ):
                issues.append(
                    chronology_issue(
                        f"implementation_hash_mismatch:declared:{implementation_hash};"
                        f"current:{implementation_snapshot.sha256}"
                    )
                )
            assert implementation_snapshot.data is not None
            if canonical_identifier(implementation_symbol):
                symbol_status = python_top_level_symbol_status(
                    implementation_snapshot.data, implementation_symbol
                )
                if symbol_status != "VALID":
                    issues.append(
                        Issue(
                            "INVALID_IMPLEMENTATION_SYMBOL",
                            "INVALID",
                            "chronology_test",
                            symbol_status,
                        )
                    )

    manifest: dict[str, Any] | None = None
    if canonical_relative_path(output_path):
        try:
            output_snapshot = snapshot_fn(output_path, include_data=True)
        except (FileNotFoundError, UnsafePathError, OSError) as error:
            issues.append(chronology_issue(f"output_unavailable:{type(error).__name__}:{error}"))
        else:
            if isinstance(output_hash, str) and output_snapshot.sha256 != output_hash:
                issues.append(
                    chronology_issue(
                        "output_hash_mismatch:"
                        f"declared:{output_hash};current:{output_snapshot.sha256}"
                    )
                )
            assert output_snapshot.data is not None
            try:
                manifest = strict_object_from_snapshot(
                    output_snapshot.data, "chronology_test_output"
                )
            except (StrictJSONError, TypeError) as error:
                issues.append(chronology_issue(f"output_manifest_invalid:{error}"))
            else:
                if manifest.get("schema_version") != "2.0":
                    issues.append(
                        Issue(
                            "INVALID_EVIDENCE_SCHEMA",
                            "INVALID",
                            "chronology_test_output",
                            "schema_version:expected_string_2.0;"
                            f"found:{manifest.get('schema_version')}",
                        )
                    )
                if manifest.get("command") != chronology.get("command"):
                    issues.append(chronology_issue("output_manifest_command_mismatch"))
                manifest_exit = manifest.get("exit_code")
                if type(manifest_exit) is not int:
                    issues.append(
                        Issue(
                            "INVALID_EXIT_CODE_TYPE",
                            "INVALID",
                            "chronology_test_output",
                            "exit_code:expected_integer;"
                            f"found:{type(manifest_exit).__name__}",
                        )
                    )
                if manifest.get("status") != "PASS" or (
                    type(manifest_exit) is int and manifest_exit != 0
                ):
                    issues.append(chronology_issue("output_manifest_not_PASS_exit_0"))
                manifest_targets = manifest.get("target_claim_ids")
                valid_manifest_targets = (
                    string_list(manifest_targets)
                    and all(canonical_identifier(target) for target in manifest_targets)
                    and len(set(manifest_targets)) == len(manifest_targets)
                )
                if not valid_manifest_targets or set(manifest_targets) != set(target_ids):
                    issues.append(chronology_issue("output_manifest_target_claim_mismatch"))
                elif not set(manifest_targets).issubset(algorithm_claims):
                    issues.append(chronology_issue("output_manifest_orphan_target_claim"))
                if (
                    manifest.get("implementation_relative_path") != implementation_path
                    or manifest.get("implementation_sha256") != implementation_hash
                ):
                    issues.append(chronology_issue("output_manifest_implementation_mismatch"))

                test_path = manifest.get("executable_test_relative_path")
                test_hash = manifest.get("executable_test_sha256")
                if not canonical_relative_path(test_path):
                    issues.append(chronology_issue("executable_test_path:unsafe_or_noncanonical"))
                elif not isinstance(test_hash, str) or SHA256_PATTERN.fullmatch(test_hash) is None:
                    issues.append(chronology_issue("executable_test_sha256:invalid"))
                else:
                    try:
                        test_snapshot = snapshot_fn(
                            test_path, include_data=True
                        )
                    except (FileNotFoundError, UnsafePathError, OSError) as error:
                        issues.append(
                            chronology_issue(
                                "executable_test_unavailable:"
                                f"{type(error).__name__}:{error}"
                            )
                        )
                    else:
                        if test_snapshot.sha256 != test_hash:
                            issues.append(
                                chronology_issue(
                                    "executable_test_hash_mismatch:"
                                    f"declared:{test_hash};current:{test_snapshot.sha256}"
                                )
                            )
                        assert test_snapshot.data is not None
                        symbols = {
                            binding.get("implementation_symbol")
                            for claim_id in target_ids
                            for binding in trace_bindings.get(claim_id, [])
                            if canonical_identifier(binding.get("implementation_symbol"))
                        }
                        if len(symbols) != 1:
                            issues.append(
                                chronology_issue(
                                    "trace_implementation_symbol_not_unique"
                                )
                            )
                        else:
                            test_targets, contract_errors = parse_python_test_contract(
                                test_snapshot.data,
                                test_path,
                                implementation_path,
                                next(iter(symbols)),
                            )
                            if contract_errors:
                                issues.append(
                                    chronology_issue(
                                        "executable_test_implementation_mismatch:"
                                        + ";".join(contract_errors)
                                    )
                                )
                            if test_targets != set(target_ids):
                                issues.append(
                                    chronology_issue(
                                        "executable_test_target_claim_mismatch"
                                    )
                                )

    for claim_id in target_ids:
        bindings = trace_bindings.get(claim_id, [])
        if len(bindings) != 1:
            issues.append(
                chronology_issue(
                    f"trace_binding_count:{claim_id}:{len(bindings)}", claim_id
                )
            )
            continue
        binding = bindings[0]
        if (
            binding.get("implementation_relative_path") != implementation_path
            or binding.get("implementation_symbol") != implementation_symbol
            or binding.get("implementation_sha256") != implementation_hash
            or binding.get("pass_output_relative_path") != output_path
            or binding.get("pass_output_sha256") != output_hash
        ):
            issues.append(chronology_issue("trace_and_chronology_evidence_mismatch", claim_id))
        if isinstance(manifest, dict) and (
            binding.get("executable_test_relative_path")
            != manifest.get("executable_test_relative_path")
            or binding.get("executable_test_sha256")
            != manifest.get("executable_test_sha256")
        ):
            issues.append(chronology_issue("trace_and_chronology_test_mismatch", claim_id))
    if trace is None:
        issues.append(chronology_issue("claim_code_trace_unavailable"))
    return issues


def validate_chronology_self_attestation(
    snapshot_fn: SnapshotReader,
    protocol: dict[str, Any],
    strict_new_checks: bool = False,
) -> list[Issue]:
    """protocol chronology_test 登记测试的反自证检查。

    严格 AST 契约只在 prediction_unit=SAMPLE 时执行（validate_chronology）；
    本检查对任意 prediction_unit 登记的 chronology_test 生效，经 output
    manifest 找到可执行测试文件后做静态 TARGET_CLAIM_IDS/import 绑定检查。
    """

    chronology = protocol.get("chronology_test")
    if not isinstance(chronology, dict):
        return []
    output_path = chronology.get("output_file")
    if not canonical_relative_path(output_path):
        return []
    try:
        output_snapshot = snapshot_fn(output_path, include_data=True)
    except (FileNotFoundError, UnsafePathError, OSError):
        return []
    assert output_snapshot.data is not None
    try:
        manifest = strict_object_from_snapshot(
            output_snapshot.data, "chronology_test_output"
        )
    except (StrictJSONError, TypeError):
        return []
    test_path = manifest.get("executable_test_relative_path")
    if not canonical_relative_path(test_path):
        return []
    try:
        test_snapshot = snapshot_fn(test_path, include_data=True)
    except (FileNotFoundError, UnsafePathError, OSError):
        return []
    assert test_snapshot.data is not None
    raw_targets = chronology.get("target_claim_ids")
    registered = set(raw_targets) if string_list(raw_targets) else set()
    implementation_path = chronology.get("implementation_relative_path")
    implementation_paths = (
        {implementation_path}
        if canonical_relative_path(implementation_path)
        else set()
    )
    return self_attesting_test_issues(
        test_snapshot.data,
        test_path,
        registered,
        implementation_paths,
        strict_new_checks=strict_new_checks,
    )


def validate_loaded(
    snapshot_fn: SnapshotReader,
    state: dict[str, Any],
    inventory: dict[str, Any],
    protocol: dict[str, Any],
    baseline: dict[str, Any] | None,
    trace: dict[str, Any] | None,
) -> list[Issue]:
    state_epoch = state.get("validation_epoch")
    issues = validate_protocol_fields(protocol, state_epoch)
    algorithm_claims, claim_issues = collect_algorithm_claims(inventory, state_epoch)
    issues.extend(claim_issues)
    issues.extend(validate_chronology(snapshot_fn, protocol, algorithm_claims, trace))
    issues.extend(_baseline_budget_issues(baseline, algorithm_claims, state_epoch))
    return issues


def _baseline_budget_issues(
    baseline: dict[str, Any] | None,
    algorithm_claims: dict[str, dict[str, Any]],
    state_epoch: Any,
) -> list[Issue]:
    # 延迟导入打破循环：validate_baseline_budget 依赖本模块的
    # collect_algorithm_claims / load_object_via_ctx。baseline 硬校验已
    # 迁出（去 trigger 门控），这里委托给新模块以保持完整运行口径一致。
    from validate_baseline_budget import validate_baselines

    return validate_baselines(baseline, algorithm_claims, state_epoch)


def validate_with_context(
    ctx: ProjectContext,
    *,
    baseline_only: bool = False,
    inventory: str | None = None,
    protocol: str | None = None,
    baseline_budget: str | None = None,
    claim_code_trace: str | None = None,
    strict_new_checks: bool = False,
) -> list[Issue]:
    """库函数入口：复用 ProjectContext 完成全部校验，供 CLI 与批量调用共用。

    state 直接取 ctx.state（构建 ctx 时已 strict 解析）；各 JSON 走
    ctx.load_json；实现/测试/输出文件走 ctx.snapshot（按路径缓存）。
    各可选参数为 CLI 显式覆盖的相对路径；缺省按 state["artifacts"] 解析。
    strict_new_checks 将 NEW_CHECK_CODES 中的新检查码从 WARNING 升为
    INVALID。baseline_only 为兼容入口，转发 validate_baseline_budget。
    """

    state = ctx.state
    if baseline_only:
        # 兼容入口（deprecated）：baseline 硬校验已迁到
        # validate_baseline_budget.py；该模块自带相同的 profile 门控，
        # 这里只做 thin 转发以保持 CLI 行为一致。
        from validate_baseline_budget import (
            validate_with_context as validate_baseline_budget,
        )

        return validate_baseline_budget(
            ctx, inventory_path=inventory, baseline_budget=baseline_budget
        )
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
        inventory or ctx.artifact_relative_path("claim_inventory"),
        "claim_inventory",
    )
    baseline, baseline_issues = load_object_via_ctx(
        ctx,
        baseline_budget or ctx.artifact_relative_path("baseline_budget"),
        "baseline_budget",
        required=False,
    )
    issues.extend(inventory_issues + baseline_issues)
    protocol_data, protocol_issues = load_object_via_ctx(
        ctx,
        protocol or ctx.artifact_relative_path("protocol_contract"),
        "protocol_contract",
    )
    trace, trace_issues = load_object_via_ctx(
        ctx,
        claim_code_trace or ctx.artifact_relative_path("claim_code_trace"),
        "claim_code_trace",
        required=False,
    )
    issues.extend(protocol_issues + trace_issues)
    if inventory_data is not None and protocol_data is not None:
        issues.extend(
            validate_loaded(
                ctx.snapshot, state, inventory_data, protocol_data, baseline, trace
            )
        )
    if protocol_data is not None:
        issues.extend(
            validate_chronology_self_attestation(
                ctx.snapshot, protocol_data, strict_new_checks
            )
        )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--baseline-budget", type=Path)
    parser.add_argument("--claim-code-trace", type=Path)
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--strict-new-checks", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root_fd: int | None = None
    try:
        root_fd = open_root_fd(args.root)
        state_path = lexical_relative_cli_path(args.root, args.state, "state")
        # 显式 CLI 覆盖：先做与旧版一致的词法校验，缺省则交由
        # validate_with_context 按 state["artifacts"] 解析。
        overrides = {
            "inventory": ("inventory", args.inventory),
            "protocol": ("protocol", args.protocol),
            "baseline_budget": ("baseline_budget", args.baseline_budget),
            "claim_code_trace": ("claim_code_trace", args.claim_code_trace),
        }
        resolved = {
            key: (
                lexical_relative_cli_path(args.root, raw, label)
                if raw is not None
                else None
            )
            for key, (label, raw) in overrides.items()
        }
        # state 预读沿用旧的 root_fd 通道，确保 state 缺失/损坏时的
        # 错误码与文本与旧版完全一致；ctx 随后会再解析一次同一文件。
        state, issues = load_object(root_fd, state_path, "workflow_state")
        if state is not None:
            with ProjectContext(args.root, args.state) as ctx:
                issues.extend(
                    validate_with_context(
                        ctx,
                        baseline_only=args.baseline_only,
                        strict_new_checks=args.strict_new_checks,
                        **resolved,
                    )
                )
    except Exception as error:
        issues = [
            Issue(
                "VALIDATOR_ERROR",
                "INVALID",
                "protocol_contract",
                str(error),
            )
        ]
    finally:
        if root_fd is not None:
            os.close(root_fd)

    print(render("protocol_contract", issues, args.json))
    return int(choose_exit(issues))


if __name__ == "__main__":
    raise SystemExit(main())
