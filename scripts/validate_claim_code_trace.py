#!/usr/bin/env python3
"""Validate algorithm claims against pseudocode, code, tests and PASS outputs."""

from __future__ import annotations

import argparse
from collections import Counter
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any

from validation_common import (
    Issue,
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
from validate_protocol_contract import (
    ALGORITHM_PROFILES,
    collect_algorithm_claims,
    parse_python_test_contract,
    python_top_level_symbol_status,
)


SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
REQUIRED_TRACE_FIELDS = (
    "claim_id",
    "manuscript_location",
    "pseudocode_symbol",
    "implementation_relative_path",
    "implementation_symbol",
    "implementation_sha256",
    "executable_test_relative_path",
    "executable_test_sha256",
    "pass_output_relative_path",
    "pass_output_sha256",
)


def strict_object(data: bytes, label: str) -> dict[str, Any]:
    payload = strict_json_load_bytes(data)
    if not isinstance(payload, dict):
        raise TypeError(f"{label}:top_level_not_object")
    return payload


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
        return None, [Issue("UNSAFE_TRACE_PATH", "INVALID", label, str(error))]
    except OSError as error:
        return None, [
            Issue("VALIDATOR_ERROR", "INVALID", label, type(error).__name__)
        ]
    assert snapshot.data is not None
    try:
        return strict_object(snapshot.data, label), []
    except (StrictJSONError, TypeError) as error:
        return None, [
            Issue(f"INVALID_{label.upper()}_JSON", "INVALID", label, str(error))
        ]


def canonical_identifier(value: Any) -> bool:
    return nonempty_string(value) and value.strip() == value


def exact_token_present(data: bytes, token: str) -> bool:
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        return False
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_.-]){re.escape(token)}(?![A-Za-z0-9_.-])"
    )
    return pattern.search(text) is not None


def read_bound_file(
    root_fd: int,
    item_id: str,
    raw_path: Any,
    declared_hash: Any,
    *,
    kind: str,
    include_data: bool,
) -> tuple[bytes | None, list[Issue]]:
    issues: list[Issue] = []
    if not canonical_relative_path(raw_path):
        return None, [
            Issue(
                "UNSAFE_TRACE_PATH",
                "INVALID",
                item_id,
                f"{kind}:path_must_be_canonical_and_relative",
            )
        ]
    if not isinstance(declared_hash, str) or SHA256_PATTERN.fullmatch(declared_hash) is None:
        issues.append(
            Issue(
                "INVALID_TRACE_FIELD",
                "INVALID",
                item_id,
                f"{kind}_sha256:expected_lowercase_sha256",
            )
        )
    try:
        snapshot = read_regular_file_at(root_fd, raw_path, include_data=include_data)
    except FileNotFoundError:
        return None, issues + [
            Issue("MISSING_TRACE_FILE", "INVALID", item_id, f"{kind}:{raw_path}")
        ]
    except UnsafePathError as error:
        return None, issues + [
            Issue("UNSAFE_TRACE_PATH", "INVALID", item_id, f"{kind}:{error}")
        ]
    except OSError as error:
        return None, issues + [
            Issue(
                "UNREADABLE_TRACE_FILE",
                "INVALID",
                item_id,
                f"{kind}:{type(error).__name__}",
            )
        ]
    mismatch_codes = {
        "implementation": "IMPLEMENTATION_HASH_MISMATCH",
        "executable_test": "EXECUTABLE_TEST_HASH_MISMATCH",
        "pass_output": "PASS_OUTPUT_HASH_MISMATCH",
        "manuscript": "MANUSCRIPT_HASH_MISMATCH",
    }
    if (
        isinstance(declared_hash, str)
        and SHA256_PATTERN.fullmatch(declared_hash)
        and snapshot.sha256 != declared_hash
    ):
        issues.append(
            Issue(
                mismatch_codes[kind],
                "INVALID",
                item_id,
                f"declared:{declared_hash};current:{snapshot.sha256}",
            )
        )
    return snapshot.data, issues


def parse_location(value: Any) -> tuple[str, int] | None:
    if not nonempty_string(value) or ":" not in value:
        return None
    raw_path, raw_line = value.rsplit(":", 1)
    if not canonical_relative_path(raw_path):
        return None
    try:
        line = int(raw_line)
    except ValueError:
        return None
    if line < 1 or str(line) != raw_line:
        return None
    return raw_path, line


def validate_manuscript_binding(
    root_fd: int,
    claim: dict[str, Any],
    binding: dict[str, Any],
    item_id: str,
) -> list[Issue]:
    issues: list[Issue] = []
    location = binding.get("manuscript_location")
    parsed = parse_location(location)
    if parsed is None:
        return [
            Issue(
                "INVALID_TRACE_FIELD",
                "INVALID",
                item_id,
                "manuscript_location:expected_canonical_relative_path_and_line",
            )
        ]
    locations = claim.get("locations")
    if not string_list(locations) or location not in locations:
        issues.append(
            Issue(
                "TRACE_MANUSCRIPT_LOCATION_MISMATCH",
                "INVALID",
                item_id,
                f"location_not_registered:{location}",
            )
        )
    source_path, line_number = parsed
    try:
        snapshot = read_regular_file_at(root_fd, source_path, include_data=True)
    except FileNotFoundError:
        return issues + [
            Issue("MISSING_TRACE_FILE", "INVALID", item_id, f"manuscript:{source_path}")
        ]
    except UnsafePathError as error:
        return issues + [
            Issue("UNSAFE_TRACE_PATH", "INVALID", item_id, f"manuscript:{error}")
        ]
    except OSError as error:
        return issues + [
            Issue(
                "UNREADABLE_TRACE_FILE",
                "INVALID",
                item_id,
                f"manuscript:{type(error).__name__}",
            )
        ]
    assert snapshot.data is not None
    try:
        text = snapshot.data.decode("utf-8")
    except UnicodeError as error:
        return issues + [
            Issue(
                "INVALID_TRACE_SOURCE_ENCODING",
                "INVALID",
                item_id,
                f"manuscript:{type(error).__name__}",
            )
        ]
    if line_number > len(text.splitlines()):
        issues.append(
            Issue(
                "TRACE_MANUSCRIPT_LOCATION_MISMATCH",
                "INVALID",
                item_id,
                f"line_out_of_range:{line_number}",
            )
        )
    pseudocode_symbol = binding.get("pseudocode_symbol")
    if canonical_identifier(pseudocode_symbol) and not exact_token_present(
        snapshot.data, pseudocode_symbol
    ):
        issues.append(
            Issue(
                "PSEUDOCODE_SYMBOL_NOT_FOUND",
                "INVALID",
                item_id,
                pseudocode_symbol,
            )
        )
    return issues


def validate_pass_manifest(
    data: bytes | None,
    binding: dict[str, Any],
    item_id: str,
) -> list[Issue]:
    if data is None:
        return []
    try:
        manifest = strict_object(data, "pass_output")
    except (StrictJSONError, TypeError) as error:
        return [
            Issue("INVALID_PASS_OUTPUT", "INVALID", item_id, str(error))
        ]
    issues: list[Issue] = []
    if manifest.get("schema_version") != "2.0":
        issues.append(
            Issue(
                "INVALID_EVIDENCE_SCHEMA",
                "INVALID",
                item_id,
                f"schema_version:expected_string_2.0;found:{manifest.get('schema_version')}",
            )
        )
    exit_code = manifest.get("exit_code")
    if type(exit_code) is not int:
        issues.append(
            Issue(
                "INVALID_EXIT_CODE_TYPE",
                "INVALID",
                item_id,
                f"exit_code:expected_integer;found:{type(exit_code).__name__}",
            )
        )
    if manifest.get("status") != "PASS" or (
        type(exit_code) is int and exit_code != 0
    ):
        issues.append(
            Issue(
                "TRACE_OUTPUT_NOT_PASS",
                "INVALID",
                item_id,
                f"status:{manifest.get('status')};exit_code:{manifest.get('exit_code')}",
            )
        )
    claim_id = binding.get("claim_id")
    target_ids = manifest.get("target_claim_ids")
    if (
        not string_list(target_ids)
        or not all(canonical_identifier(target) for target in target_ids)
        or len(set(target_ids)) != len(target_ids)
        or claim_id not in target_ids
    ):
        issues.append(
            Issue(
                "TRACE_OUTPUT_CLAIM_ID_MISSING",
                "INVALID",
                str(claim_id),
                "PASS_manifest_must_list_exact_target_claim_id",
            )
        )
    for field in (
        "implementation_relative_path",
        "implementation_sha256",
        "executable_test_relative_path",
        "executable_test_sha256",
    ):
        if manifest.get(field) != binding.get(field):
            issues.append(
                Issue(
                    "TRACE_OUTPUT_BINDING_MISMATCH",
                    "INVALID",
                    item_id,
                    field,
                )
            )
    return issues


def validate_binding(
    root_fd: int,
    claim: dict[str, Any],
    binding: Any,
    index: int,
) -> tuple[str | None, list[Issue]]:
    item_id = f"trace[{index}]"
    if not isinstance(binding, dict):
        return None, [
            Issue("INVALID_CLAIM_CODE_TRACE", "INVALID", item_id, "expected_object")
        ]
    issues: list[Issue] = []
    for field in REQUIRED_TRACE_FIELDS:
        if field not in binding:
            issues.append(
                Issue(
                    "INVALID_TRACE_FIELD",
                    "INVALID",
                    item_id,
                    f"missing:{field}",
                )
            )
    claim_id = binding.get("claim_id")
    if canonical_identifier(claim_id):
        item_id = claim_id
    else:
        issues.append(
            Issue(
                "INVALID_TRACE_FIELD",
                "INVALID",
                item_id,
                "claim_id:expected_canonical_nonempty_string",
            )
        )
        claim_id = None
    for field in ("pseudocode_symbol", "implementation_symbol"):
        if field in binding and not canonical_identifier(binding.get(field)):
            issues.append(
                Issue(
                    "INVALID_TRACE_FIELD",
                    "INVALID",
                    item_id,
                    f"{field}:expected_canonical_nonempty_string",
                )
            )
    issues.extend(validate_manuscript_binding(root_fd, claim, binding, item_id))

    implementation_data, implementation_issues = read_bound_file(
        root_fd,
        item_id,
        binding.get("implementation_relative_path"),
        binding.get("implementation_sha256"),
        kind="implementation",
        include_data=True,
    )
    issues.extend(implementation_issues)
    implementation_symbol = binding.get("implementation_symbol")
    if implementation_data is not None and canonical_identifier(implementation_symbol):
        symbol_status = python_top_level_symbol_status(
            implementation_data, implementation_symbol
        )
        if symbol_status == "MISSING":
            issues.append(
                Issue(
                    "IMPLEMENTATION_SYMBOL_NOT_FOUND",
                    "INVALID",
                    item_id,
                    implementation_symbol,
                )
            )
        elif symbol_status != "VALID":
            issues.append(
                Issue(
                    "INVALID_IMPLEMENTATION_SYMBOL",
                    "INVALID",
                    item_id,
                    "final_module_binding_is_not_a_function_or_class_definition",
                )
            )

    _, test_issues = read_bound_file(
        root_fd,
        item_id,
        binding.get("executable_test_relative_path"),
        binding.get("executable_test_sha256"),
        kind="executable_test",
        include_data=True,
    )
    issues.extend(test_issues)

    output_data, output_issues = read_bound_file(
        root_fd,
        item_id,
        binding.get("pass_output_relative_path"),
        binding.get("pass_output_sha256"),
        kind="pass_output",
        include_data=True,
    )
    issues.extend(output_issues)
    issues.extend(validate_pass_manifest(output_data, binding, item_id))
    return claim_id, issues


def grouped_bindings(
    raw_bindings: list[Any], path_field: str
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for binding in raw_bindings:
        if not isinstance(binding, dict):
            continue
        claim_id = binding.get("claim_id")
        path = binding.get(path_field)
        if not canonical_identifier(claim_id) or not canonical_relative_path(path):
            continue
        groups.setdefault(path, []).append(binding)
    return groups


def validate_test_reference_groups(
    root_fd: int,
    raw_bindings: list[Any],
    algorithm_claims: dict[str, dict[str, Any]],
) -> list[Issue]:
    issues: list[Issue] = []
    for test_path, bindings in grouped_bindings(
        raw_bindings, "executable_test_relative_path"
    ).items():
        expected_targets = {binding["claim_id"] for binding in bindings}
        if not expected_targets.issubset(algorithm_claims):
            issues.append(
                Issue(
                    "TRACE_TARGET_SET_MISMATCH",
                    "INVALID",
                    test_path,
                    "test_reference_set_contains_non_algorithm_claim",
                )
            )
        try:
            snapshot = read_regular_file_at(root_fd, test_path, include_data=True)
        except (FileNotFoundError, UnsafePathError, OSError):
            continue  # Per-binding path validation already reports the exact failure.
        assert snapshot.data is not None
        declared_targets: set[str] | None = None
        target_contract_reported = False
        for binding in bindings:
            parsed_targets, contract_errors = parse_python_test_contract(
                snapshot.data,
                test_path,
                binding.get("implementation_relative_path"),
                binding.get("implementation_symbol"),
            )
            if declared_targets is None and parsed_targets is not None:
                declared_targets = parsed_targets
            target_errors = [
                error
                for error in contract_errors
                if error.startswith("TARGET_CLAIM_IDS")
                or error.startswith("executable_test:")
            ]
            implementation_errors = [
                error for error in contract_errors if error not in target_errors
            ]
            if target_errors and not target_contract_reported:
                issues.append(
                    Issue(
                        "INVALID_TEST_TARGET_CONTRACT",
                        "INVALID",
                        test_path,
                        ";".join(target_errors),
                    )
                )
                target_contract_reported = True
            if implementation_errors:
                issues.append(
                    Issue(
                        "TRACE_TEST_IMPLEMENTATION_MISMATCH",
                        "INVALID",
                        binding["claim_id"],
                        ";".join(implementation_errors),
                    )
                )
        if declared_targets != expected_targets:
            missing = expected_targets - (declared_targets or set())
            if missing:
                issues.append(
                    Issue(
                        "TRACE_TEST_CLAIM_ID_MISSING",
                        "INVALID",
                        test_path,
                        f"missing:{','.join(sorted(missing))}",
                    )
                )
            if not target_contract_reported:
                issues.append(
                    Issue(
                        "INVALID_TEST_TARGET_CONTRACT",
                        "INVALID",
                        test_path,
                        "declared_targets_must_equal_trace_reference_set",
                    )
                )
    return issues


def validate_output_reference_groups(
    root_fd: int,
    raw_bindings: list[Any],
    algorithm_claims: dict[str, dict[str, Any]],
) -> list[Issue]:
    issues: list[Issue] = []
    for output_path, bindings in grouped_bindings(
        raw_bindings, "pass_output_relative_path"
    ).items():
        expected_targets = {binding["claim_id"] for binding in bindings}
        try:
            snapshot = read_regular_file_at(root_fd, output_path, include_data=True)
        except (FileNotFoundError, UnsafePathError, OSError):
            continue
        assert snapshot.data is not None
        try:
            manifest = strict_object(snapshot.data, "pass_output")
        except (StrictJSONError, TypeError):
            continue
        raw_targets = manifest.get("target_claim_ids")
        valid_targets = (
            string_list(raw_targets)
            and all(canonical_identifier(target) for target in raw_targets)
            and len(set(raw_targets)) == len(raw_targets)
        )
        declared_targets = set(raw_targets) if valid_targets else set()
        if (
            not valid_targets
            or declared_targets != expected_targets
            or not declared_targets.issubset(algorithm_claims)
        ):
            issues.append(
                Issue(
                    "TRACE_TARGET_SET_MISMATCH",
                    "INVALID",
                    output_path,
                    "manifest_targets_must_equal_trace_reference_set_and_inventory",
                )
            )
    return issues


def validate_protocol_cross_binding(
    root_fd: int,
    protocol: dict[str, Any] | None,
    bindings: dict[str, dict[str, Any]],
    algorithm_claims: dict[str, dict[str, Any]],
) -> list[Issue]:
    if not isinstance(protocol, dict) or protocol.get("prediction_unit") != "SAMPLE":
        return []
    chronology = protocol.get("chronology_test")
    if not isinstance(chronology, dict):
        return [
            Issue(
                "ONLINE_CHRONOLOGY_UNVERIFIED",
                "INVALID",
                "chronology_test",
                "missing_or_invalid_object",
            )
        ]
    target_ids = chronology.get("target_claim_ids")
    targets = target_ids if string_list(target_ids) else []
    issues: list[Issue] = []
    manifest: dict[str, Any] | None = None
    output_path = chronology.get("output_file")
    if canonical_relative_path(output_path):
        try:
            snapshot = read_regular_file_at(root_fd, output_path, include_data=True)
            assert snapshot.data is not None
            manifest = strict_object(snapshot.data, "chronology_test_output")
        except (FileNotFoundError, UnsafePathError, OSError, StrictJSONError, TypeError):
            manifest = None
    for claim_id in sorted(algorithm_claims):
        binding = bindings.get(claim_id)
        if claim_id not in targets or binding is None:
            issues.append(
                Issue(
                    "ONLINE_CHRONOLOGY_UNVERIFIED",
                    "INVALID",
                    claim_id,
                    "claim_not_bound_to_chronology_test",
                )
            )
            continue
        if (
            binding.get("implementation_relative_path")
            != chronology.get("implementation_relative_path")
            or binding.get("implementation_symbol")
            != chronology.get("implementation_symbol")
            or binding.get("implementation_sha256")
            != chronology.get("implementation_sha256")
            or binding.get("pass_output_relative_path") != output_path
            or binding.get("pass_output_sha256") != chronology.get("output_sha256")
        ):
            issues.append(
                Issue(
                    "ONLINE_CHRONOLOGY_UNVERIFIED",
                    "INVALID",
                    claim_id,
                    "trace_and_chronology_implementation_mismatch",
                )
            )
        if not isinstance(manifest, dict) or (
            manifest.get("command") != chronology.get("command")
            or binding.get("executable_test_relative_path")
            != manifest.get("executable_test_relative_path")
            or binding.get("executable_test_sha256")
            != manifest.get("executable_test_sha256")
        ):
            issues.append(
                Issue(
                    "ONLINE_CHRONOLOGY_UNVERIFIED",
                    "INVALID",
                    claim_id,
                    "trace_and_chronology_test_or_command_mismatch",
                )
            )
    return issues


def validate_loaded(
    root_fd: int,
    state: dict[str, Any],
    inventory: dict[str, Any],
    registry: dict[str, Any],
    protocol: dict[str, Any] | None,
) -> list[Issue]:
    state_epoch = state.get("validation_epoch")
    algorithm_claims, issues = collect_algorithm_claims(inventory, state_epoch)
    if registry.get("schema_version") != "2.0":
        issues.append(
            Issue(
                "INVALID_CLAIM_CODE_TRACE",
                "INVALID",
                "claim_code_trace",
                f"schema_version:{registry.get('schema_version')}",
            )
        )
    epoch = registry.get("validation_epoch")
    if not positive_integer(epoch):
        issues.append(
            Issue(
                "INVALID_CLAIM_CODE_TRACE",
                "INVALID",
                "claim_code_trace",
                "validation_epoch:expected_positive_integer",
            )
        )
    elif positive_integer(state_epoch) and epoch != state_epoch:
        issues.append(
            Issue(
                "VALIDATION_EPOCH_MISMATCH",
                "INVALID",
                "claim_code_trace",
                f"trace:{epoch};state:{state_epoch}",
            )
        )
    raw_bindings = registry.get("traces")
    if not isinstance(raw_bindings, list):
        return issues + [
            Issue(
                "INVALID_CLAIM_CODE_TRACE",
                "INVALID",
                "claim_code_trace",
                "traces:expected_list",
            )
        ]

    observed_ids: list[str] = []
    unique_bindings: dict[str, dict[str, Any]] = {}
    for index, raw_binding in enumerate(raw_bindings):
        raw_claim_id = raw_binding.get("claim_id") if isinstance(raw_binding, dict) else None
        valid_raw_claim_id = canonical_identifier(raw_claim_id)
        if valid_raw_claim_id and raw_claim_id not in algorithm_claims:
            observed_ids.append(raw_claim_id)
            issues.append(
                Issue(
                    "ORPHAN_CLAIM_CODE_TRACE",
                    "INVALID",
                    raw_claim_id,
                    "claim_id_not_an_algorithm_claim_in_inventory",
                )
            )
            continue
        claim = algorithm_claims.get(raw_claim_id, {}) if valid_raw_claim_id else {}
        claim_id, binding_issues = validate_binding(
            root_fd, claim, raw_binding, index
        )
        issues.extend(binding_issues)
        if claim_id is not None:
            observed_ids.append(claim_id)
            if isinstance(raw_binding, dict):
                unique_bindings.setdefault(claim_id, raw_binding)
    counts = Counter(observed_ids)
    for claim_id, count in counts.items():
        if count > 1:
            issues.append(
                Issue(
                    "DUPLICATE_CLAIM_CODE_TRACE",
                    "INVALID",
                    claim_id,
                    f"count:{count}",
                )
            )
    for claim_id in sorted(set(algorithm_claims) - set(observed_ids)):
        issues.append(
            Issue(
                "MISSING_CLAIM_CODE_TRACE",
                "INVALID",
                claim_id,
                "algorithm_claim_requires_exactly_one_trace",
            )
        )
    issues.extend(
        validate_test_reference_groups(root_fd, raw_bindings, algorithm_claims)
    )
    issues.extend(
        validate_output_reference_groups(root_fd, raw_bindings, algorithm_claims)
    )
    issues.extend(
        validate_protocol_cross_binding(
            root_fd, protocol, unique_bindings, algorithm_claims
        )
    )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root_fd: int | None = None
    try:
        root_fd = open_root_fd(args.root)
        state_path = lexical_relative_cli_path(args.root, args.state, "state")
        inventory_path = lexical_relative_cli_path(
            args.root,
            args.inventory or (args.root / "claim_inventory.json"),
            "inventory",
        )
        trace_path = lexical_relative_cli_path(
            args.root,
            args.trace or (args.root / "claim_code_trace.json"),
            "trace",
        )
        protocol_path = lexical_relative_cli_path(
            args.root,
            args.protocol or (args.root / "protocol_contract.json"),
            "protocol",
        )
        state, issues = load_object(root_fd, state_path, "workflow_state")
        if state is not None:
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
            elif profile in ALGORITHM_PROFILES:
                inventory, inventory_issues = load_object(
                    root_fd, inventory_path, "claim_inventory"
                )
                registry, registry_issues = load_object(
                    root_fd, trace_path, "claim_code_trace"
                )
                protocol, protocol_issues = load_object(
                    root_fd, protocol_path, "protocol_contract", required=False
                )
                issues.extend(inventory_issues + registry_issues + protocol_issues)
                if inventory is not None and registry is not None:
                    issues.extend(
                        validate_loaded(root_fd, state, inventory, registry, protocol)
                    )
    except Exception as error:
        issues = [
            Issue("VALIDATOR_ERROR", "INVALID", "claim_code_trace", str(error))
        ]
    finally:
        if root_fd is not None:
            os.close(root_fd)

    print(render("claim_code_trace", issues, args.json))
    return int(choose_exit(issues))


if __name__ == "__main__":
    raise SystemExit(main())
