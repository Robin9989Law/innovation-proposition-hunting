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
# 新增检查码：默认 WARNING（不计入退出码），--strict-new-checks 升为 INVALID。
# 不在此集合内的码维持原有严重级语义。
NEW_CHECK_CODES = frozenset({"SELF_ATTESTING_TEST"})


def issue_severity(code: str, strict_new_checks: bool) -> str:
    if code in NEW_CHECK_CODES and not strict_new_checks:
        return "WARNING"
    return "INVALID"


def canonical_identifier(value: Any) -> bool:
    return nonempty_string(value) and value.strip() == value


def strict_object_from_snapshot(data: bytes, label: str) -> dict[str, Any]:
    payload = strict_json_load_bytes(data)
    if not isinstance(payload, dict):
        raise TypeError(f"{label}:top_level_not_object")
    return payload


# 文件快照读取函数签名：与 ProjectContext.snapshot 一致。单次校验运行内
# 可按 (路径, include_data) 缓存，避免按 binding 重复读盘/重哈希。
SnapshotReader = Callable[..., SafeFileSnapshot]


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


def _literal_truth(node: ast.AST) -> bool | None:
    """Evaluate only Python literal syntax and return its truth value."""

    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None
    try:
        return bool(value)
    except (TypeError, ValueError):
        return None


def _literal_empty_iterable(node: ast.AST) -> bool:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False
    return isinstance(value, (tuple, list, set, dict, str, bytes)) and not value


def _pattern_is_irrefutable(pattern: ast.pattern) -> bool:
    if isinstance(pattern, ast.MatchAs):
        return pattern.pattern is None or _pattern_is_irrefutable(pattern.pattern)
    if isinstance(pattern, ast.MatchOr):
        return any(_pattern_is_irrefutable(item) for item in pattern.patterns)
    return False


def _class_global_names(statements: list[ast.stmt]) -> set[str]:
    """Collect globals from class code, including recursively executed classes."""

    names: set[str] = set()

    class GlobalVisitor(ast.NodeVisitor):
        def visit_Global(self, node: ast.Global) -> None:
            names.update(node.names)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            return

        def visit_Lambda(self, node: ast.Lambda) -> None:
            return

    visitor = GlobalVisitor()
    for statement in statements:
        visitor.visit(statement)
    return names


def _direct_class_global_names(statements: list[ast.stmt]) -> set[str]:
    """Collect globals belonging to one class scope, not nested class scopes."""

    names: set[str] = set()

    class DirectGlobalVisitor(ast.NodeVisitor):
        def visit_Global(self, node: ast.Global) -> None:
            names.update(node.names)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            return

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            return

        def visit_Lambda(self, node: ast.Lambda) -> None:
            return

    visitor = DirectGlobalVisitor()
    for statement in statements:
        visitor.visit(statement)
    return names


def _direct_function_global_names(node: ast.AST) -> set[str]:
    """Collect globals in one function scope without entering nested scopes."""

    names: set[str] = set()

    class DirectGlobalVisitor(ast.NodeVisitor):
        def visit_Global(self, child: ast.Global) -> None:
            names.update(child.names)

        def visit_FunctionDef(self, child: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, child: ast.AsyncFunctionDef) -> None:
            return

        def visit_ClassDef(self, child: ast.ClassDef) -> None:
            return

        def visit_Lambda(self, child: ast.Lambda) -> None:
            return

    DirectGlobalVisitor().visit(node)
    return names


class _ModuleBindingVisitor(ast.NodeVisitor):
    """Find a module-scope binding without descending into nested scopes."""

    def __init__(
        self,
        name: str,
        *,
        ignored_nodes: set[ast.AST] | None = None,
        skip_static_false: bool = False,
    ) -> None:
        self.name = name
        self.ignored_nodes = ignored_nodes or set()
        self.skip_static_false = skip_static_false
        self.found = False

    def visit(self, node: ast.AST) -> Any:
        if node in self.ignored_nodes:
            return None
        return super().visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == self.name and isinstance(node.ctx, (ast.Store, ast.Del)):
            self.found = True

    def _visit_definition_header(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        if node.name == self.name:
            self.found = True
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        if node.returns is not None:
            self.visit(node.returns)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_definition_header(node)
        self._visit_function_body_module_effects(node.body)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_definition_header(node)
        self._visit_function_body_module_effects(node.body)

    def _visit_function_body_module_effects(self, body: list[ast.stmt]) -> None:
        direct_globals = {
            name
            for statement in body
            for name in _direct_function_global_names(statement)
        }
        if self.name in direct_globals:
            for statement in body:
                self.visit(statement)
            return
        self._visit_nested_function_effects(body)

    def _visit_nested_function_effects(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._visit_function_body_module_effects(statement.body)
                continue
            if isinstance(statement, ast.ClassDef):
                self._visit_class_body_module_effects(statement.body)
                self._visit_nested_function_effects(statement.body)
                continue
            if isinstance(statement, ast.If) and self.skip_static_false:
                truth = _literal_truth(statement.test)
                branches = (
                    statement.orelse
                    if truth is False
                    else statement.body
                    if truth is True
                    else [*statement.body, *statement.orelse]
                )
                self._visit_nested_function_effects(branches)
                continue
            if (
                isinstance(statement, ast.While)
                and self.skip_static_false
                and _literal_truth(statement.test) is False
            ):
                self._visit_nested_function_effects(statement.orelse)
                continue
            for child in ast.iter_child_nodes(statement):
                if isinstance(child, ast.stmt):
                    self._visit_nested_function_effects([child])

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name == self.name:
            self.found = True
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self._visit_class_body_module_effects(node.body)
        self._visit_nested_function_effects(node.body)

    def _visit_class_body_module_effects(self, body: list[ast.stmt]) -> None:
        if self.name in _direct_class_global_names(body):
            for statement in body:
                self.visit(statement)
            return
        if self.name in _class_global_names(body):
            self._visit_nested_class_effects(body)

    def _visit_nested_class_effects(self, statements: list[ast.stmt]) -> None:
        """Inspect executed nested class bodies without treating class locals as module binds."""

        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(statement, ast.ClassDef):
                self._visit_class_body_module_effects(statement.body)
                continue
            if isinstance(statement, ast.If):
                truth = _literal_truth(statement.test)
                if self.skip_static_false and truth is False:
                    self._visit_nested_class_effects(statement.orelse)
                elif self.skip_static_false and truth is True:
                    self._visit_nested_class_effects(statement.body)
                else:
                    self._visit_nested_class_effects(statement.body)
                    self._visit_nested_class_effects(statement.orelse)
                continue
            if isinstance(statement, ast.While):
                truth = _literal_truth(statement.test)
                if self.skip_static_false and truth is False:
                    self._visit_nested_class_effects(statement.orelse)
                else:
                    self._visit_nested_class_effects(statement.body)
                    self._visit_nested_class_effects(statement.orelse)
                continue
            for child in ast.iter_child_nodes(statement):
                if isinstance(child, ast.stmt):
                    self._visit_nested_class_effects([child])

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return  # Lambda parameters and walrus targets are local to the lambda.

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if (alias.asname or alias.name.split(".")[0]) == self.name:
                self.found = True

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*" or (alias.asname or alias.name) == self.name:
                self.found = True

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name == self.name:
            self.found = True
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name == self.name:
            self.found = True
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name == self.name:
            self.found = True

    def visit_If(self, node: ast.If) -> None:
        if not self.skip_static_false:
            self.generic_visit(node)
            return
        truth = _literal_truth(node.test)
        self.visit(node.test)
        branch = node.orelse if truth is False else node.body if truth is True else None
        for statement in branch if branch is not None else (*node.body, *node.orelse):
            self.visit(statement)

    def visit_While(self, node: ast.While) -> None:
        if not self.skip_static_false or _literal_truth(node.test) is not False:
            self.generic_visit(node)
            return
        self.visit(node.test)
        for statement in node.orelse:
            self.visit(statement)


def _module_binds_name(
    nodes: list[ast.stmt],
    name: str,
    *,
    ignored_nodes: set[ast.AST] | None = None,
    skip_static_false: bool = False,
) -> bool:
    visitor = _ModuleBindingVisitor(
        name,
        ignored_nodes=ignored_nodes,
        skip_static_false=skip_static_false,
    )
    for node in nodes:
        visitor.visit(node)
    return visitor.found


def python_top_level_symbol_status(data: bytes, symbol: str) -> str:
    """Classify whether the final provable module binding is a definition."""

    if not canonical_identifier(symbol):
        return "MISSING"
    try:
        tree = ast.parse(data.decode("utf-8"))
    except (UnicodeError, SyntaxError):
        return "MISSING"
    definitions = [
        index
        for index, node in enumerate(tree.body)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == symbol
    ]
    if not definitions:
        return "MISSING"
    final_definition = definitions[-1]
    definition = tree.body[final_definition]
    if isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if definition.decorator_list:
            return "INVALID_FINAL_BINDING"
    elif isinstance(definition, ast.ClassDef):
        safe_bases = not definition.bases or (
            len(definition.bases) == 1
            and isinstance(definition.bases[0], ast.Name)
            and definition.bases[0].id == "object"
        )
        if definition.decorator_list or definition.keywords or not safe_bases:
            return "INVALID_FINAL_BINDING"
    if _module_binds_name(
        tree.body[final_definition + 1 :], symbol, skip_static_false=True
    ):
        return "INVALID_FINAL_BINDING"
    return "VALID"


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


def _reachable_nodes_with_scopes(
    statements: list[ast.stmt], scopes: tuple[set[str], ...]
) -> list[tuple[ast.AST, tuple[set[str], ...]]]:
    """Conservatively enumerate reachable AST nodes with lexical scopes."""

    found: list[tuple[ast.AST, tuple[set[str], ...]]] = []
    fallthrough = "FALLTHROUGH"
    function_scope_stack: list[dict[str, tuple[Any, ...]]] = [{}]
    executed_functions: set[int] = set()

    def visit_function_header(
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        active_scopes: tuple[set[str], ...],
    ) -> None:
        for decorator in node.decorator_list:
            visit_expression(decorator, active_scopes)
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ):
            visit_expression(argument.annotation, active_scopes)
        if node.args.vararg:
            visit_expression(node.args.vararg.annotation, active_scopes)
        if node.args.kwarg:
            visit_expression(node.args.kwarg.annotation, active_scopes)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            visit_expression(default, active_scopes)
        visit_expression(node.returns, active_scopes)

    def visit_called_function(
        function: ast.AST, active_scopes: tuple[set[str], ...]
    ) -> None:
        if not isinstance(function, ast.Name):
            return
        binding: tuple[Any, ...] | None = None
        for index in range(len(function_scope_stack) - 1, -1, -1):
            binding = function_scope_stack[index].get(function.id)
            if binding is not None:
                break
            if index > 0 and function.id in active_scopes[index - 1]:
                return
        if binding is None:
            return
        node, lexical_scopes, parent_function_scopes = binding
        if id(node) in executed_functions:
            return
        executed_functions.add(id(node))
        saved_function_scopes = list(function_scope_stack)
        try:
            function_scope_stack[:] = [*parent_function_scopes, {}]
            visit_block(
                node.body,
                lexical_scopes + (_bound_names_in_scope(node),),
            )
        finally:
            function_scope_stack[:] = saved_function_scopes

    def visit_expression(
        node: ast.AST | None, active_scopes: tuple[set[str], ...]
    ) -> None:
        if node is None:
            return
        found.append((node, active_scopes))
        if isinstance(node, ast.Lambda):
            return  # Lambda bodies are not accepted as executable trace evidence.
        if isinstance(node, ast.BoolOp):
            stop_truth = False if isinstance(node.op, ast.And) else True
            for value in node.values:
                visit_expression(value, active_scopes)
                if _literal_truth(value) is stop_truth:
                    break
            return
        if isinstance(node, ast.IfExp):
            visit_expression(node.test, active_scopes)
            truth = _literal_truth(node.test)
            if truth is True:
                visit_expression(node.body, active_scopes)
            elif truth is False:
                visit_expression(node.orelse, active_scopes)
            else:
                visit_expression(node.body, active_scopes)
                visit_expression(node.orelse, active_scopes)
            return
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, ast.stmt):
                visit_expression(child, active_scopes)
        if isinstance(node, ast.Call):
            visit_called_function(node.func, active_scopes)

    def visit_block(
        block: list[ast.stmt], active_scopes: tuple[set[str], ...]
    ) -> set[str]:
        outcomes: set[str] = set()
        can_continue = True
        for statement in block:
            if not can_continue:
                break
            statement_outcomes = visit_statement(statement, active_scopes)
            outcomes.update(statement_outcomes - {fallthrough})
            can_continue = fallthrough in statement_outcomes
        if can_continue:
            outcomes.add(fallthrough)
        return outcomes

    def visit_statement(
        node: ast.stmt, active_scopes: tuple[set[str], ...]
    ) -> set[str]:
        found.append((node, active_scopes))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit_function_header(node, active_scopes)
            function_scope_stack[-1][node.name] = (
                node,
                active_scopes,
                tuple(function_scope_stack),
            )
            return {fallthrough}
        if isinstance(node, ast.ClassDef):
            return {fallthrough}  # Class bodies are not trusted as call proof.
        if isinstance(node, ast.If):
            visit_expression(node.test, active_scopes)
            truth = _literal_truth(node.test)
            if truth is False:
                return visit_block(node.orelse, active_scopes)
            if truth is True:
                return visit_block(node.body, active_scopes)
            return visit_block(node.body, active_scopes) | visit_block(
                node.orelse, active_scopes
            )
        if isinstance(node, ast.While):
            visit_expression(node.test, active_scopes)
            truth = _literal_truth(node.test)
            if truth is False:
                return visit_block(node.orelse, active_scopes)
            body_outcomes = visit_block(node.body, active_scopes)
            if truth is True:
                outcomes = body_outcomes & {"RETURN", "RAISE"}
                if "BREAK" in body_outcomes:
                    outcomes.add(fallthrough)
                return outcomes
            else_outcomes = visit_block(node.orelse, active_scopes)
            return (
                {fallthrough}
                | (body_outcomes & {"RETURN", "RAISE"})
                | (else_outcomes - {"BREAK", "CONTINUE"})
            )
        if isinstance(node, (ast.For, ast.AsyncFor)):
            visit_expression(node.target, active_scopes)
            visit_expression(node.iter, active_scopes)
            if _literal_empty_iterable(node.iter):
                return visit_block(node.orelse, active_scopes)
            body_outcomes = visit_block(node.body, active_scopes)
            else_outcomes = visit_block(node.orelse, active_scopes)
            outcomes = (
                (body_outcomes & {"RETURN", "RAISE"})
                | (else_outcomes - {"BREAK", "CONTINUE"})
            )
            if "BREAK" in body_outcomes:
                outcomes.add(fallthrough)
            return outcomes
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                visit_expression(item.context_expr, active_scopes)
                visit_expression(item.optional_vars, active_scopes)
            return visit_block(node.body, active_scopes)
        if isinstance(node, (ast.Try, ast.TryStar)):
            body_outcomes = visit_block(node.body, active_scopes)
            handler_outcomes: set[str] = set()
            for handler in node.handlers:
                if handler.type is not None:
                    visit_expression(handler.type, active_scopes)
                handler_outcomes.update(visit_block(handler.body, active_scopes))
            if fallthrough in body_outcomes:
                else_outcomes = visit_block(node.orelse, active_scopes)
                body_outcomes = (body_outcomes - {fallthrough}) | else_outcomes
            protected_outcomes = body_outcomes | handler_outcomes
            final_outcomes = visit_block(node.finalbody, active_scopes)
            return (final_outcomes - {fallthrough}) | (
                protected_outcomes if fallthrough in final_outcomes else set()
            )
        if isinstance(node, ast.Match):
            visit_expression(node.subject, active_scopes)
            outcomes: set[str] = set()
            for case in node.cases:
                visit_expression(case.guard, active_scopes)
                outcomes.update(visit_block(case.body, active_scopes))
            last_case_is_irrefutable = bool(node.cases) and (
                node.cases[-1].guard is None
                and _pattern_is_irrefutable(node.cases[-1].pattern)
            )
            if not last_case_is_irrefutable:
                outcomes.add(fallthrough)
            return outcomes
        if isinstance(node, ast.Assert):
            visit_expression(node.test, active_scopes)
            truth = _literal_truth(node.test)
            if truth is True:
                return {fallthrough}
            visit_expression(node.msg, active_scopes)
            return {"RAISE"} if truth is False else {fallthrough}
        if isinstance(node, ast.Return):
            visit_expression(node.value, active_scopes)
            return {"RETURN"}
        if isinstance(node, ast.Raise):
            visit_expression(node.exc, active_scopes)
            visit_expression(node.cause, active_scopes)
            return {"RAISE"}
        if isinstance(node, ast.Break):
            return {"BREAK"}
        if isinstance(node, ast.Continue):
            return {"CONTINUE"}
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                visit_expression(child, active_scopes)
        return {fallthrough}

    visit_block(statements, scopes)
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

    if _module_binds_name(
        tree.body,
        "TARGET_CLAIM_IDS",
        ignored_nodes={declaration.targets[0]},
        skip_static_false=True,
    ):
        return None, ["TARGET_CLAIM_IDS:rebound_or_deleted"]
    for node in ast.walk(tree):
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
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"setattr", "delattr"}
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "TARGET_CLAIM_IDS"
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
        for root in binding_roots:
            if _module_binds_name(
                [statement], root, skip_static_false=True
            ):
                other_module_binders.add(root)
    reachable_nodes = _reachable_nodes_with_scopes(tree.body, ())
    calls = [
        (node, scopes)
        for node, scopes in reachable_nodes
        if isinstance(node, ast.Call)
    ]
    mutated_bindings: set[tuple[str, str]] = set()
    for node, scopes in reachable_nodes:
        for root, expected in bindings:
            if root in other_module_binders or any(root in scope for scope in scopes):
                continue
            expected_parts = expected.split(".")
            protected_attributes = {
                ".".join(expected_parts[:length])
                for length in range(2, len(expected_parts) + 1)
            }
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, (ast.Store, ast.Del))
                and _dotted_name(node) in protected_attributes
            ):
                mutated_bindings.add((root, expected))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"setattr", "delattr"}
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
                and (
                    f"{_dotted_name(node.args[0])}.{node.args[1].value}"
                    in protected_attributes
                )
            ):
                mutated_bindings.add((root, expected))
    called = False
    for call, scopes in calls:
        dotted = _dotted_name(call.func)
        for root, expected in bindings:
            if (
                root in other_module_binders
                or any(root in scope for scope in scopes)
                or (root, expected) in mutated_bindings
            ):
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


def _module_level_target_claim_ids(tree: ast.Module) -> set[str]:
    """提取模块级 TARGET_CLAIM_IDS 字面量赋值（list/tuple，元素均为 str）。

    取最后一次可字面求值的赋值（Python 模块语义）；动态值或多次赋值由
    严格契约 parse_python_test_contract 另行拒绝。
    """

    declared: set[str] = set()
    for statement in tree.body:
        target: ast.AST | None = None
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            target, value = statement.target, statement.value
        if not (
            isinstance(target, ast.Name)
            and target.id == "TARGET_CLAIM_IDS"
            and value is not None
        ):
            continue
        try:
            literal = ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            continue
        if isinstance(literal, (list, tuple)) and all(
            isinstance(item, str) for item in literal
        ):
            declared = set(literal)
    return declared


def _test_imports_implementation(tree: ast.Module, implementation_path: str) -> bool:
    """宽松判定测试文件是否 import 了登记的实现模块。

    允许 sys.path.insert 后的裸 stem 导入、完整点分路径导入、
    from 导入及相对导入：Import/ImportFrom 的模块名首/末段或
    from 导入的名字与实现文件 stem 匹配即可。
    """

    module = _implementation_module(implementation_path)
    if module is None:
        return False
    stem = module.split(".")[-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if alias.name == module or parts[0] == stem or parts[-1] == stem:
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                parts = node.module.split(".")
                if node.module == module or parts[0] == stem or parts[-1] == stem:
                    return True
            if any(alias.name == stem for alias in node.names):
                return True
    return False


def self_attesting_test_issues(
    data: bytes,
    test_path: str,
    registered_claim_ids: set[str],
    implementation_paths: set[str],
    *,
    strict_new_checks: bool = False,
) -> list[Issue]:
    """静态反自证检查：登记/绑定的测试必须机器可读地绑定 claim 与实现。

    测试文件必须含模块级 TARGET_CLAIM_IDS 字面量（非空且与登记/绑定的
    claim_ids 有交集），并 import 登记的实现模块；否则报
    SELF_ATTESTING_TEST（默认 WARNING，--strict-new-checks 升 INVALID）。
    无法解析的测试文件由严格契约或执行证据另行报告，这里不重复。
    """

    severity = issue_severity("SELF_ATTESTING_TEST", strict_new_checks)
    try:
        tree = ast.parse(data.decode("utf-8"), filename=test_path)
    except (UnicodeError, SyntaxError):
        return []
    issues: list[Issue] = []
    declared = _module_level_target_claim_ids(tree)
    if not declared:
        issues.append(
            Issue(
                "SELF_ATTESTING_TEST",
                severity,
                test_path,
                "TARGET_CLAIM_IDS:missing_or_empty_module_literal",
            )
        )
    elif registered_claim_ids and declared.isdisjoint(registered_claim_ids):
        issues.append(
            Issue(
                "SELF_ATTESTING_TEST",
                severity,
                test_path,
                "TARGET_CLAIM_IDS:no_intersection_with_registered_claims:"
                + ",".join(sorted(registered_claim_ids)),
            )
        )
    if implementation_paths and not any(
        _test_imports_implementation(tree, path) for path in implementation_paths
    ):
        issues.append(
            Issue(
                "SELF_ATTESTING_TEST",
                severity,
                test_path,
                "implementation_import:missing",
            )
        )
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
    if baseline_only:
        # 兼容入口（deprecated）：baseline 硬校验已迁到
        # validate_baseline_budget.py，这里做 thin 转发。
        from validate_baseline_budget import (
            validate_with_context as validate_baseline_budget,
        )

        issues.extend(
            validate_baseline_budget(
                ctx, inventory_path=inventory, baseline_budget=baseline_budget
            )
        )
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
