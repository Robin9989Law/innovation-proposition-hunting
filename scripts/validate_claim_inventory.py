#!/usr/bin/env python3
"""Validate complete registration of high-risk manuscript claims."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable

from validation_common import Issue, choose_exit, render


AUDITED_VALIDITY_LEVELS = {"V3", "V4"}
SUPPORTED_SOURCE_SUFFIXES = {".md", ".markdown", ".tex"}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")

ENGLISH_RISK_PATTERNS = (
    ("strong baseline", re.compile(r"\bstrong\s+baseline\b", re.IGNORECASE)),
    ("zero regret", re.compile(r"\bzero\s+regret\b", re.IGNORECASE)),
    ("for any", re.compile(r"\bfor\s+any\b", re.IGNORECASE)),
    ("interpolation", re.compile(r"\binterpolation\b", re.IGNORECASE)),
    ("guaranteed", re.compile(r"\bguaranteed\b", re.IGNORECASE)),
    ("sufficient", re.compile(r"\bsufficient\b", re.IGNORECASE)),
    ("universal", re.compile(r"\buniversal\b", re.IGNORECASE)),
    ("necessary", re.compile(r"\bnecessary\b", re.IGNORECASE)),
    ("provably", re.compile(r"\bprovably\b", re.IGNORECASE)),
    ("lossless", re.compile(r"\blossless\b", re.IGNORECASE)),
    ("bounded", re.compile(r"\bbounded\b", re.IGNORECASE)),
    ("online", re.compile(r"\bonline\b", re.IGNORECASE)),
    ("exact", re.compile(r"\bexact\b", re.IGNORECASE)),
    ("first", re.compile(r"\bfirst\b", re.IGNORECASE)),
)

CHINESE_RISK_TERMS = (
    "强基线",
    "零遗憾",
    "对任意",
    "可证明",
    "普遍适用",
    "普遍",
    "普适",
    "通用",
    "精确",
    "有界",
    "保证",
    "必要",
    "充分",
    "无损",
    "在线",
    "插值",
    "首次",
    "第一",
    "任意",
)
CHINESE_RISK_PATTERN = re.compile(
    "|".join(re.escape(term) for term in CHINESE_RISK_TERMS)
)
CHINESE_LEXICAL_CONTEXT_RULES = {
    "保证": (
        ("保证金融", True),
        ("保证金", False),
    ),
    "充分": (("充分利用", False),),
    "在线": (
        ("在线性能", True),
        ("在线下界", True),
        ("在线性模型", False),
        ("在线性回归", False),
        ("在线性方程", False),
        ("在线性代数", False),
        ("在线性系统", False),
        ("在线下实验", False),
        ("在线下场景", False),
        ("在线下环境", False),
        ("在线下测试", False),
        ("在线下设置", False),
        ("在线下数据", False),
        ("在线下进行", False),
    ),
    "必要": (("必要时", False),),
    "精确": (("精确率", False),),
}
FIRST_CLAIM_CLASSIFIERS = ("种", "个", "项", "篇", "套", "款")
FIRST_CLAIM_CUES = (
    "提出",
    "开发",
    "构建",
    "设计",
    "实现",
    "发布",
    "发现",
    "证明",
    "给出",
    "首创",
    "开创",
)
FIRST_CLAIM_OBJECTS = (
    "方法",
    "算法",
    "模型",
    "定理",
    "引理",
    "推论",
    "结论",
    "结果",
    "协议",
    "框架",
    "系统",
    "工具",
    "数据集",
    "基准",
    "评测",
    "证明",
    "理论",
    "机制",
    "贡献",
    "方案",
)

MARKDOWN_THEOREM_HEADING = re.compile(
    r"^ {0,3}#{1,6}[ \t]+(?:\*\*|__)?"
    r"(?P<term>theorem|lemma|corollary)\b",
    re.IGNORECASE,
)
MARKDOWN_CHINESE_THEOREM_HEADING = re.compile(
    r"^ {0,3}#{1,6}[ \t]+(?:\*\*|__)?(?P<term>定理|引理|推论)"
)
PLAIN_THEOREM_TITLE = re.compile(
    r"^\s*(?:\*\*|__)?(?P<term>theorem|lemma|corollary)\b"
    r"(?:\s+(?:[A-Z]|[IVX]+|\d+(?:\.\d+)*)|\s*[:：.(（])",
    re.IGNORECASE,
)
PLAIN_CHINESE_THEOREM_TITLE = re.compile(
    r"^\s*(?:\*\*|__)?(?P<term>定理|引理|推论)"
    r"(?:\s*[0-9一二三四五六七八九十]+|\s*[:：.(（])"
)
TEX_THEOREM_ENVIRONMENT = re.compile(
    r"\\begin\{(?P<term>theorem|lemma|corollary)\*?\}", re.IGNORECASE
)
TEX_ENVIRONMENT_BEGIN = re.compile(r"\\begin\{(?P<environment>[^{}]+)\}")
TEX_CODE_ENVIRONMENTS = {
    "bverbatim",
    "lverbatim",
    "lstlisting",
    "lstlisting*",
    "minted",
    "minted*",
    "saveverbatim",
    "verbatim",
    "verbatim*",
}

REQUIRED_CLAIM_FIELDS = (
    "claim_id",
    "statement",
    "claim_type",
    "locations",
    "evidence_responsibility",
    "risk_terms",
    "status",
    "validation_epoch",
)


def occurrence_id(relative_path: str, line: str, term: str, ordinal: int) -> str:
    normalized = " ".join(line.split()).casefold()
    raw = f"{relative_path}\0{term.casefold()}\0{normalized}\0{ordinal}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def string_list(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(nonempty_string(item) for item in value)
    )


def valid_epoch(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 1


def load_object(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{label}:top_level_not_object")
    return payload


def require_within_root(root: Path, path: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label}:outside_root:{path}") from error


def source_path_is_canonical(raw_path: str) -> bool:
    posix_path = PurePosixPath(raw_path)
    return (
        bool(raw_path)
        and "\\" not in raw_path
        and not posix_path.is_absolute()
        and posix_path.parts
        and all(part not in {"", ".", ".."} for part in posix_path.parts)
        and posix_path.as_posix() == raw_path
    )


def resolve_sources(
    root: Path, raw_sources: Any
) -> tuple[list[tuple[str, Path]], list[Issue]]:
    if not string_list(raw_sources):
        return [], [
            Issue(
                "INVALID_INVENTORY_FIELD",
                "INVALID",
                "claim_inventory",
                "manuscript_sources:expected_nonempty_string_list",
            )
        ]

    sources: list[tuple[str, Path]] = []
    issues: list[Issue] = []
    seen_declared: set[str] = set()
    seen_resolved: set[Path] = set()
    for raw_path in raw_sources:
        if raw_path in seen_declared:
            issues.append(
                Issue(
                    "DUPLICATE_MANUSCRIPT_SOURCE",
                    "INVALID",
                    raw_path,
                    "duplicate_declared_path",
                )
            )
            continue
        seen_declared.add(raw_path)
        if not source_path_is_canonical(raw_path):
            issues.append(
                Issue(
                    "UNSAFE_MANUSCRIPT_SOURCE",
                    "INVALID",
                    raw_path,
                    "path_must_be_canonical_and_relative",
                )
            )
            continue
        if PurePosixPath(raw_path).suffix.casefold() not in SUPPORTED_SOURCE_SUFFIXES:
            issues.append(
                Issue(
                    "UNSUPPORTED_MANUSCRIPT_SOURCE",
                    "INVALID",
                    raw_path,
                    "expected_markdown_or_tex",
                )
            )
            continue

        resolved = (root / raw_path).resolve()
        try:
            require_within_root(root, resolved, "manuscript_source")
        except ValueError:
            issues.append(
                Issue(
                    "UNSAFE_MANUSCRIPT_SOURCE",
                    "INVALID",
                    raw_path,
                    "resolved_path_outside_root",
                )
            )
            continue
        if resolved in seen_resolved:
            issues.append(
                Issue(
                    "DUPLICATE_MANUSCRIPT_SOURCE",
                    "INVALID",
                    raw_path,
                    "duplicate_resolved_path",
                )
            )
            continue
        seen_resolved.add(resolved)
        if not resolved.is_file():
            issues.append(
                Issue(
                    "MISSING_MANUSCRIPT_SOURCE",
                    "INVALID",
                    raw_path,
                    "not_a_regular_file",
                )
            )
            continue
        sources.append((raw_path, resolved))
    return sources, issues


def matches_for_line(line: str) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    for canonical_term, pattern in ENGLISH_RISK_PATTERNS:
        matches.extend((match.start(), canonical_term) for match in pattern.finditer(line))
    for match in CHINESE_RISK_PATTERN.finditer(line):
        term = match.group(0)
        following = line[match.end() :]
        if term == "第一":
            classifier = next(
                (
                    candidate
                    for candidate in FIRST_CLAIM_CLASSIFIERS
                    if following.startswith(candidate)
                ),
                None,
            )
            if classifier is None:
                continue
            remainder = following[len(classifier) :]
            if not any(cue in line for cue in FIRST_CLAIM_CUES) and not any(
                research_object in remainder
                for research_object in FIRST_CLAIM_OBJECTS
            ):
                continue
        lexical_context = line[match.start() :]
        context_decision = next(
            (
                is_risk
                for context, is_risk in sorted(
                    CHINESE_LEXICAL_CONTEXT_RULES.get(term, ()),
                    key=lambda rule: len(rule[0]),
                    reverse=True,
                )
                if lexical_context.startswith(context)
            ),
            True,
        )
        if not context_decision:
            continue
        matches.append((match.start(), term))
    for pattern in (
        MARKDOWN_THEOREM_HEADING,
        MARKDOWN_CHINESE_THEOREM_HEADING,
        PLAIN_THEOREM_TITLE,
        PLAIN_CHINESE_THEOREM_TITLE,
        TEX_THEOREM_ENVIRONMENT,
    ):
        matches.extend(
            (match.start(), match.group("term").casefold())
            for match in pattern.finditer(line)
        )
    return sorted(matches, key=lambda item: (item[0], item[1]))


def markdown_indentation(line: str) -> tuple[int, int]:
    character_count = 0
    column_count = 0
    for character in line:
        if character == " ":
            column_count += 1
        elif character == "\t":
            column_count += 4 - (column_count % 4)
        else:
            break
        character_count += 1
    return character_count, column_count


def markdown_scannable_lines(lines: list[str]) -> Iterable[tuple[int, str, str]]:
    fence_character: str | None = None
    fence_length = 0
    for line_number, line in enumerate(lines, start=1):
        indent_characters, indent_columns = markdown_indentation(line)
        candidate = line[indent_characters:] if indent_columns <= 3 else ""
        if fence_character is not None:
            closing = re.match(
                rf"{re.escape(fence_character)}{{{fence_length},}}[ \t]*\Z",
                candidate,
            )
            if closing:
                fence_character = None
                fence_length = 0
            continue

        opening = re.match(r"(?P<marker>`{3,}|~{3,})", candidate)
        if opening:
            marker = opening.group("marker")
            fence_character = marker[0]
            fence_length = len(marker)
            continue
        if indent_columns >= 4:
            continue
        yield line_number, line, line


def strip_tex_comment(line: str) -> str:
    for index, character in enumerate(line):
        if character != "%":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return line[:index]
    return line


def tex_scannable_lines(lines: list[str]) -> Iterable[tuple[int, str, str]]:
    code_environment: str | None = None
    for line_number, line in enumerate(lines, start=1):
        if code_environment is not None:
            if re.search(
                rf"\\end\{{{re.escape(code_environment)}\}}", line, re.IGNORECASE
            ):
                code_environment = None
            continue

        visible_line = strip_tex_comment(line)
        environment_match = TEX_ENVIRONMENT_BEGIN.search(visible_line)
        if environment_match:
            environment = environment_match.group("environment").casefold()
            if environment in TEX_CODE_ENVIRONMENTS:
                if not re.search(
                    rf"\\end\{{{re.escape(environment)}\}}",
                    visible_line[environment_match.end() :],
                    re.IGNORECASE,
                ):
                    code_environment = environment
                continue
        yield line_number, line, visible_line


def scan_sources(
    sources: Iterable[tuple[str, Path]],
) -> tuple[dict[str, tuple[str, int, str]], list[Issue]]:
    occurrences: dict[str, tuple[str, int, str]] = {}
    ordinals: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    issues: list[Issue] = []
    for relative_path, source_path in sources:
        try:
            lines = source_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as error:
            issues.append(
                Issue(
                    "UNREADABLE_MANUSCRIPT_SOURCE",
                    "INVALID",
                    relative_path,
                    type(error).__name__,
                )
            )
            continue
        scannable_lines = (
            tex_scannable_lines(lines)
            if source_path.suffix.casefold() == ".tex"
            else markdown_scannable_lines(lines)
        )
        for line_number, line, visible_line in scannable_lines:
            normalized = " ".join(line.split()).casefold()
            for _, term in matches_for_line(visible_line):
                key = (relative_path, term.casefold(), normalized)
                ordinals[key] += 1
                identifier = occurrence_id(
                    relative_path, line, term, ordinals[key]
                )
                occurrences[identifier] = (relative_path, line_number, term)
    return occurrences, issues


def validate_claim_fields(
    claim: Any, index: int, state_epoch: Any
) -> tuple[list[Issue], str | None, list[str]]:
    item_id = f"claim[{index}]"
    if not isinstance(claim, dict):
        return [
            Issue(
                "INVALID_CLAIM",
                "INVALID",
                item_id,
                "expected_object",
            )
        ], None, []

    issues: list[Issue] = []
    for field in REQUIRED_CLAIM_FIELDS:
        if field not in claim:
            issues.append(
                Issue(
                    "INVALID_CLAIM_FIELD",
                    "INVALID",
                    item_id,
                    f"missing:{field}",
                )
            )

    claim_id = claim.get("claim_id")
    if "claim_id" in claim and not nonempty_string(claim_id):
        issues.append(
            Issue("INVALID_CLAIM_FIELD", "INVALID", item_id, "claim_id:expected_nonempty_string")
        )
    for field in ("statement", "claim_type", "evidence_responsibility", "status"):
        if field in claim and not nonempty_string(claim.get(field)):
            issues.append(
                Issue(
                    "INVALID_CLAIM_FIELD",
                    "INVALID",
                    str(claim_id) if nonempty_string(claim_id) else item_id,
                    f"{field}:expected_nonempty_string",
                )
            )
    if "locations" in claim and not string_list(claim.get("locations")):
        issues.append(
            Issue(
                "INVALID_CLAIM_FIELD",
                "INVALID",
                str(claim_id) if nonempty_string(claim_id) else item_id,
                "locations:expected_nonempty_string_list",
            )
        )
    if "risk_terms" in claim and not string_list(claim.get("risk_terms")):
        issues.append(
            Issue(
                "INVALID_CLAIM_FIELD",
                "INVALID",
                str(claim_id) if nonempty_string(claim_id) else item_id,
                "risk_terms:expected_nonempty_string_list",
            )
        )
    claim_epoch = claim.get("validation_epoch")
    if "validation_epoch" in claim and not valid_epoch(claim_epoch):
        issues.append(
            Issue(
                "INVALID_CLAIM_FIELD",
                "INVALID",
                str(claim_id) if nonempty_string(claim_id) else item_id,
                "validation_epoch:expected_positive_integer",
            )
        )
    elif valid_epoch(state_epoch) and claim_epoch != state_epoch:
        issues.append(
            Issue(
                "VALIDATION_EPOCH_MISMATCH",
                "INVALID",
                str(claim_id) if nonempty_string(claim_id) else item_id,
                f"claim:{claim_epoch};state:{state_epoch}",
            )
        )

    raw_occurrence_ids = claim.get("occurrence_ids")
    occurrence_ids: list[str] = []
    if not isinstance(raw_occurrence_ids, list) or not all(
        isinstance(identifier, str) and SHA256_PATTERN.fullmatch(identifier)
        for identifier in raw_occurrence_ids
    ):
        issues.append(
            Issue(
                "INVALID_CLAIM_FIELD",
                "INVALID",
                str(claim_id) if nonempty_string(claim_id) else item_id,
                "occurrence_ids:expected_sha256_list",
            )
        )
    else:
        occurrence_ids = raw_occurrence_ids
    return issues, str(claim_id) if nonempty_string(claim_id) else None, occurrence_ids


def validate(root: Path, state: dict[str, Any], inventory: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    if inventory.get("schema_version") != "2.0":
        issues.append(
            Issue(
                "INVALID_INVENTORY_FIELD",
                "INVALID",
                "claim_inventory",
                f"schema_version:{inventory.get('schema_version')}",
            )
        )

    state_epoch = state.get("validation_epoch")
    if not valid_epoch(state_epoch):
        issues.append(
            Issue(
                "INVALID_STATE_VALIDATION_EPOCH",
                "INVALID",
                "workflow_state",
                f"validation_epoch:{state_epoch}",
            )
        )
    if "validation_epoch" in inventory:
        inventory_epoch = inventory.get("validation_epoch")
        if not valid_epoch(inventory_epoch):
            issues.append(
                Issue(
                    "INVALID_INVENTORY_FIELD",
                    "INVALID",
                    "claim_inventory",
                    "validation_epoch:expected_positive_integer",
                )
            )
        elif valid_epoch(state_epoch) and inventory_epoch != state_epoch:
            issues.append(
                Issue(
                    "VALIDATION_EPOCH_MISMATCH",
                    "INVALID",
                    "claim_inventory",
                    f"inventory:{inventory_epoch};state:{state_epoch}",
                )
            )

    sources, source_issues = resolve_sources(root, inventory.get("manuscript_sources"))
    issues.extend(source_issues)
    occurrences, scan_issues = scan_sources(sources)
    issues.extend(scan_issues)

    raw_claims = inventory.get("claims")
    claims: list[Any] = []
    if not isinstance(raw_claims, list):
        issues.append(
            Issue(
                "INVALID_INVENTORY_FIELD",
                "INVALID",
                "claim_inventory",
                "claims:expected_list",
            )
        )
    else:
        claims = raw_claims

    bindings: defaultdict[str, list[str]] = defaultdict(list)
    claim_ids: list[str] = []
    for index, claim_value in enumerate(claims):
        claim_issues, claim_id, occurrence_ids = validate_claim_fields(
            claim_value, index, state_epoch
        )
        issues.extend(claim_issues)
        binding_label = claim_id or f"claim[{index}]"
        if claim_id is not None:
            claim_ids.append(claim_id)
        for identifier in occurrence_ids:
            bindings[identifier].append(binding_label)

    for claim_id, count in sorted(Counter(claim_ids).items()):
        if count > 1:
            issues.append(
                Issue(
                    "DUPLICATE_CLAIM_ID",
                    "INVALID",
                    claim_id,
                    f"count:{count}",
                )
            )

    for identifier, owners in sorted(bindings.items()):
        if len(owners) > 1:
            issues.append(
                Issue(
                    "DUPLICATE_OCCURRENCE_BINDING",
                    "INVALID",
                    identifier,
                    "claims:" + ",".join(owners),
                )
            )
        if identifier not in occurrences:
            issues.append(
                Issue(
                    "ORPHAN_OCCURRENCE_BINDING",
                    "INVALID",
                    identifier,
                    "not_found_in_declared_sources",
                )
            )

    promotion_code = (
        "CLAIM_PROMOTION_UNAUDITED"
        if state.get("validity_level") in AUDITED_VALIDITY_LEVELS
        else "UNREGISTERED_HIGH_RISK_CLAIM"
    )
    for identifier, (relative_path, line_number, term) in sorted(
        occurrences.items(), key=lambda item: (item[1][0], item[1][1], item[1][2], item[0])
    ):
        if identifier not in bindings:
            issues.append(
                Issue(
                    promotion_code,
                    "INVALID",
                    identifier,
                    f"{relative_path}:{line_number};term:{term}",
                )
            )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    state_path = args.state.resolve()
    inventory_path = (
        args.inventory.resolve()
        if args.inventory is not None
        else (root / "claim_inventory.json").resolve()
    )
    try:
        if not root.is_dir():
            raise ValueError(f"root:not_directory:{root}")
        require_within_root(root, state_path, "state")
        require_within_root(root, inventory_path, "inventory")
        state = load_object(state_path, "workflow_state")
        try:
            inventory_payload = json.loads(inventory_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError) as error:
            issues = [
                Issue(
                    "INVALID_CLAIM_INVENTORY_JSON",
                    "INVALID",
                    "claim_inventory",
                    type(error).__name__,
                )
            ]
        else:
            if not isinstance(inventory_payload, dict):
                issues = [
                    Issue(
                        "INVALID_CLAIM_INVENTORY",
                        "INVALID",
                        "claim_inventory",
                        "top_level_not_object",
                    )
                ]
            else:
                issues = validate(root, state, inventory_payload)
    except Exception as error:
        issues = [
            Issue(
                "VALIDATOR_ERROR",
                "INVALID",
                "claim_inventory",
                str(error),
            )
        ]

    print(render("claim_inventory", issues, args.json))
    return int(choose_exit(issues))


if __name__ == "__main__":
    raise SystemExit(main())
