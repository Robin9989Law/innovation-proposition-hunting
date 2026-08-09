#!/usr/bin/env python3
"""Validate frozen algorithm protocols, chronology evidence and fair budgets."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any

from validation_common import (
    ALGORITHM_CLAIM_TYPES,
    CLAIM_TYPES,
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
ENGLISH_BUDGET_TERMS = (
    re.compile(r"(?<![A-Za-z0-9_])strong(?![A-Za-z0-9_])", re.I),
    re.compile(r"(?<![A-Za-z0-9_])strong(?:[ -]+)baseline(?![A-Za-z0-9_])", re.I),
    re.compile(r"(?<![A-Za-z0-9_])fair(?:[ -]+(?:baseline|comparison))?(?![A-Za-z0-9_])", re.I),
    re.compile(r"(?<![A-Za-z0-9_])matched(?:[ -]+)budget(?![A-Za-z0-9_])", re.I),
    re.compile(r"(?<![A-Za-z0-9_])same(?:[ -]+)budget(?![A-Za-z0-9_])", re.I),
)
CHINESE_BUDGET_TERMS = (
    "强基线",
    "强比较基线",
    "公平基线",
    "公平比较",
    "匹配预算",
    "预算匹配",
    "同预算",
    "相同预算",
    "等预算",
)
CANONICAL_BUDGET_RISK_TERMS = {
    "strong",
    "strong baseline",
    "fair",
    "fair comparison",
    "matched budget",
    "same budget",
    "强基线",
    "公平",
    "公平比较",
    "匹配预算",
    "同预算",
}
CHINESE_FAIR_COMPARISON_PATTERN = re.compile(
    r"(?:作|做|进行|开展|报告)?\s*公平(?:的|地|性)?\s*(?:比较|对比|基线)"
)


def canonical_identifier(value: Any) -> bool:
    return nonempty_string(value) and value.strip() == value


def strict_object_from_snapshot(data: bytes, label: str) -> dict[str, Any]:
    payload = strict_json_load_bytes(data)
    if not isinstance(payload, dict):
        raise TypeError(f"{label}:top_level_not_object")
    return payload


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else None
    return None


def _implementation_module(raw_path: str) -> str | None:
    if not canonical_relative_path(raw_path):
        return None
    path = PurePosixPath(raw_path)
    if path.suffix != ".py":
        return None
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None


def python_has_top_level_symbol(data: bytes, symbol: str) -> bool:
    """Return whether Python source defines the exact public symbol at module level."""

    if not canonical_identifier(symbol):
        return False
    try:
        tree = ast.parse(data.decode("utf-8"))
    except (UnicodeError, SyntaxError):
        return False
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == symbol
        for node in tree.body
    )


def _bound_names_in_scope(node: ast.AST) -> set[str]:
    """Conservatively collect names local to one module/function lexical scope."""

    names: set[str] = set()
    body = (
        node.body
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef))
        else []
    )
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        arguments = (
            list(node.args.posonlyargs)
            + list(node.args.args)
            + list(node.args.kwonlyargs)
        )
        names.update(argument.arg for argument in arguments)
        if node.args.vararg:
            names.add(node.args.vararg.arg)
        if node.args.kwarg:
            names.add(node.args.kwarg.arg)

    class Binder(ast.NodeVisitor):
        def visit_Name(self, child: ast.Name) -> None:
            if isinstance(child.ctx, (ast.Store, ast.Del)):
                names.add(child.id)

        def visit_FunctionDef(self, child: ast.FunctionDef) -> None:
            names.add(child.name)

        def visit_AsyncFunctionDef(self, child: ast.AsyncFunctionDef) -> None:
            names.add(child.name)

        def visit_ClassDef(self, child: ast.ClassDef) -> None:
            names.add(child.name)

        def visit_Import(self, child: ast.Import) -> None:
            for alias in child.names:
                names.add(alias.asname or alias.name.split(".")[0])

        def visit_ImportFrom(self, child: ast.ImportFrom) -> None:
            for alias in child.names:
                names.add(alias.asname or alias.name)

        def visit_ExceptHandler(self, child: ast.ExceptHandler) -> None:
            if child.name:
                names.add(child.name)
            self.generic_visit(child)

        def visit_MatchAs(self, child: ast.MatchAs) -> None:
            if child.name:
                names.add(child.name)
            self.generic_visit(child)

        def visit_MatchStar(self, child: ast.MatchStar) -> None:
            if child.name:
                names.add(child.name)

    binder = Binder()
    for statement in body:
        binder.visit(statement)
    return names


def _is_literal_false(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


def _live_calls_with_scopes(
    statements: list[ast.stmt], scopes: tuple[set[str], ...]
) -> list[tuple[ast.Call, tuple[set[str], ...]]]:
    found: list[tuple[ast.Call, tuple[set[str], ...]]] = []

    def argument_names(arguments: ast.arguments) -> set[str]:
        names = {
            argument.arg
            for argument in (
                list(arguments.posonlyargs)
                + list(arguments.args)
                + list(arguments.kwonlyargs)
            )
        }
        if arguments.vararg:
            names.add(arguments.vararg.arg)
        if arguments.kwarg:
            names.add(arguments.kwarg.arg)
        return names

    def visit(node: ast.AST, active_scopes: tuple[set[str], ...]) -> None:
        if isinstance(node, ast.If) and _is_literal_false(node.test):
            for child in node.orelse:
                visit(child, active_scopes)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local_names = _bound_names_in_scope(node)
            for child in node.body:
                visit(child, active_scopes + (local_names,))
            return
        if isinstance(node, ast.Lambda):
            visit(node.body, active_scopes + (argument_names(node.args),))
            return
        if isinstance(node, ast.ClassDef):
            return  # Class execution/name resolution is deliberately not trusted.
        if isinstance(node, ast.Call):
            found.append((node, active_scopes))
        for child in ast.iter_child_nodes(node):
            visit(child, active_scopes)

    for statement in statements:
        visit(statement, scopes)
    return found


def parse_python_test_contract(
    data: bytes,
    test_path: str,
    implementation_path: str,
    implementation_symbol: str,
) -> tuple[set[str] | None, list[str]]:
    """Parse a non-executed Python test contract and prove its code binding."""

    if PurePosixPath(test_path).suffix != ".py":
        return None, ["executable_test:python_AST_contract_required"]
    module = _implementation_module(implementation_path)
    if module is None or not canonical_identifier(implementation_symbol):
        return None, ["implementation_binding:invalid_module_or_symbol"]
    try:
        text = data.decode("utf-8")
        tree = ast.parse(text, filename=test_path)
    except (UnicodeError, SyntaxError) as error:
        return None, [f"executable_test:unparseable:{type(error).__name__}"]

    declarations: list[tuple[ast.Assign, ast.AST]] = []
    for statement in tree.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == "TARGET_CLAIM_IDS"
        ):
            declarations.append((statement, statement.value))
    if len(declarations) != 1:
        return None, [
            f"TARGET_CLAIM_IDS:expected_one_top_level_literal;found:{len(declarations)}"
        ]
    declaration, value = declarations[0]
    if not isinstance(value, ast.Tuple) or not value.elts:
        return None, ["TARGET_CLAIM_IDS:expected_nonempty_tuple_literal"]
    if not all(
        isinstance(item, ast.Constant) and isinstance(item.value, str)
        for item in value.elts
    ):
        return None, ["TARGET_CLAIM_IDS:expected_literal_strings"]
    raw_targets = tuple(item.value for item in value.elts)
    if not all(canonical_identifier(target) for target in raw_targets):
        return None, ["TARGET_CLAIM_IDS:expected_canonical_strings"]
    if len(set(raw_targets)) != len(raw_targets):
        return None, ["TARGET_CLAIM_IDS:duplicate_claim_id"]

    for node in ast.walk(tree):
        if (
            node is declaration
            or node is declaration.targets[0]
            or node in value.elts
            or node is value
        ):
            continue
        if (
            isinstance(node, ast.Name)
            and node.id == "TARGET_CLAIM_IDS"
            and isinstance(node.ctx, (ast.Store, ast.Del))
        ):
            return None, ["TARGET_CLAIM_IDS:rebound_or_deleted"]
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "TARGET_CLAIM_IDS"
            and isinstance(node.ctx, (ast.Store, ast.Del))
        ):
            return None, ["TARGET_CLAIM_IDS:mutated"]
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "TARGET_CLAIM_IDS"
            and node.func.attr
            in {"append", "extend", "insert", "pop", "remove", "clear", "sort", "reverse"}
        ):
            return None, ["TARGET_CLAIM_IDS:mutation_call_forbidden"]

    bindings: list[tuple[str, str]] = []
    import_statements: set[ast.stmt] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == module:
            for alias in node.names:
                if alias.name == implementation_symbol:
                    local = alias.asname or alias.name
                    bindings.append((local, local))
                    import_statements.add(node)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module:
                    if alias.asname:
                        bindings.append((alias.asname, f"{alias.asname}.{implementation_symbol}"))
                    else:
                        bindings.append(
                            (module.split(".")[0], f"{module}.{implementation_symbol}")
                        )
                    import_statements.add(node)

    if not bindings:
        return set(raw_targets), [
            f"implementation_import_missing:{module}:{implementation_symbol}"
        ]

    # Remove only the names established by the trusted exact imports. Any other
    # module-level binder of the same name conservatively shadows the import.
    other_module_binders: set[str] = set()
    binding_roots = {root for root, _ in bindings}
    for statement in tree.body:
        if statement in import_statements:
            if isinstance(statement, ast.Import):
                for alias in statement.names:
                    local = alias.asname or alias.name.split(".")[0]
                    if local in binding_roots and alias.name != module:
                        other_module_binders.add(local)
            elif isinstance(statement, ast.ImportFrom):
                for alias in statement.names:
                    local = alias.asname or alias.name
                    if local in binding_roots and alias.name != implementation_symbol:
                        other_module_binders.add(local)
            continue
        other_module_binders.update(
            _bound_names_in_scope(ast.Module(body=[statement], type_ignores=[]))
        )
    calls = _live_calls_with_scopes(tree.body, ())
    called = False
    for call, scopes in calls:
        dotted = _dotted_name(call.func)
        for root, expected in bindings:
            if root in other_module_binders or any(root in scope for scope in scopes):
                continue
            if dotted == expected:
                called = True
                break
        if called:
            break
    if not called:
        return set(raw_targets), [
            f"implementation_call_missing:{module}:{implementation_symbol}"
        ]
    return set(raw_targets), []


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


def claim_triggers_budget(claim: dict[str, Any]) -> bool:
    risk_terms = claim.get("risk_terms")
    if isinstance(risk_terms, list):
        risk_text = "\n".join(term for term in risk_terms if isinstance(term, str))
        normalized_risks = {
            re.sub(r"[-_]+", " ", term.strip().casefold())
            for term in risk_terms
            if isinstance(term, str)
        }
        if (
            normalized_risks & CANONICAL_BUDGET_RISK_TERMS
            or any(pattern.search(risk_text) for pattern in ENGLISH_BUDGET_TERMS)
            or any(term in risk_text for term in CHINESE_BUDGET_TERMS)
            or CHINESE_FAIR_COMPARISON_PATTERN.search(risk_text) is not None
        ):
            return True
    statement = claim.get("statement")
    text = statement if isinstance(statement, str) else ""
    return any(pattern.search(text) for pattern in ENGLISH_BUDGET_TERMS) or any(
        term in text for term in CHINESE_BUDGET_TERMS
    ) or CHINESE_FAIR_COMPARISON_PATTERN.search(text) is not None


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
    root_fd: int,
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
            implementation_snapshot = read_regular_file_at(root_fd, implementation_path)
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

    manifest: dict[str, Any] | None = None
    if canonical_relative_path(output_path):
        try:
            output_snapshot = read_regular_file_at(root_fd, output_path, include_data=True)
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
                        test_snapshot = read_regular_file_at(
                            root_fd, test_path, include_data=True
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
    trigger_claims: set[str],
    state_epoch: Any,
) -> list[Issue]:
    if baseline is None:
        return (
            [
                Issue(
                    "BASELINE_BUDGET_INCOMPLETE",
                    "INVALID",
                    claim_id,
                    "baseline_budget.json:missing",
                )
                for claim_id in sorted(trigger_claims)
            ]
            if trigger_claims
            else []
        )
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
        if trigger_claims:
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
    for claim_id in sorted(trigger_claims - covered):
        issues.append(
            Issue(
                "BASELINE_BUDGET_INCOMPLETE",
                "INVALID",
                claim_id,
                "no_comparator_covers_trigger_claim",
            )
        )
    return issues


def validate_loaded(
    root_fd: int,
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
    issues.extend(validate_chronology(root_fd, protocol, algorithm_claims, trace))
    trigger_claims = {
        claim_id
        for claim_id, claim in algorithm_claims.items()
        if claim_triggers_budget(claim)
    }
    issues.extend(validate_baselines(baseline, trigger_claims, state_epoch))
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
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root_fd: int | None = None
    try:
        root_fd = open_root_fd(args.root)
        paths = {
            "workflow_state": lexical_relative_cli_path(args.root, args.state, "state"),
            "claim_inventory": lexical_relative_cli_path(
                args.root,
                args.inventory or (args.root / "claim_inventory.json"),
                "inventory",
            ),
            "protocol_contract": lexical_relative_cli_path(
                args.root,
                args.protocol or (args.root / "protocol_contract.json"),
                "protocol",
            ),
            "baseline_budget": lexical_relative_cli_path(
                args.root,
                args.baseline_budget or (args.root / "baseline_budget.json"),
                "baseline_budget",
            ),
            "claim_code_trace": lexical_relative_cli_path(
                args.root,
                args.claim_code_trace or (args.root / "claim_code_trace.json"),
                "claim_code_trace",
            ),
        }
        state, issues = load_object(
            root_fd, paths["workflow_state"], "workflow_state"
        )
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
                    root_fd, paths["claim_inventory"], "claim_inventory"
                )
                baseline, baseline_issues = load_object(
                    root_fd,
                    paths["baseline_budget"],
                    "baseline_budget",
                    required=args.baseline_only,
                )
                issues.extend(inventory_issues + baseline_issues)
                if args.baseline_only:
                    if inventory is not None and baseline is not None:
                        algorithm_claims, claim_issues = collect_algorithm_claims(
                            inventory, state.get("validation_epoch")
                        )
                        issues.extend(claim_issues)
                        trigger_claims = {
                            claim_id
                            for claim_id, claim in algorithm_claims.items()
                            if claim_triggers_budget(claim)
                        }
                        issues.extend(
                            validate_baselines(
                                baseline,
                                trigger_claims,
                                state.get("validation_epoch"),
                            )
                        )
                else:
                    protocol, protocol_issues = load_object(
                        root_fd, paths["protocol_contract"], "protocol_contract"
                    )
                    trace, trace_issues = load_object(
                        root_fd,
                        paths["claim_code_trace"],
                        "claim_code_trace",
                        required=False,
                    )
                    issues.extend(protocol_issues + trace_issues)
                    if inventory is not None and protocol is not None:
                        issues.extend(
                            validate_loaded(
                                root_fd, state, inventory, protocol, baseline, trace
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
