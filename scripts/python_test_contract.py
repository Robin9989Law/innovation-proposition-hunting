#!/usr/bin/env python3
"""Static AST contract analysis for Python test files.

从 validate_protocol_contract.py 拆出的 Python 测试文件静态分析器：
扫描测试文件、提取模块级 TARGET_CLAIM_IDS 字面量、解析实现对齐 import
绑定、做保守的可达调用/断言分析，证明"测试机器可读地绑定了 claim 与实现"。
供 validate_protocol_contract.py 与 validate_claim_code_trace.py 共用；
只依赖 validation_common，不反向 import 任何校验器。
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import Any

from validation_common import (
    Issue,
    canonical_relative_path,
    nonempty_string,
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
