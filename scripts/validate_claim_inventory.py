#!/usr/bin/env python3
"""Validate complete registration of high-risk manuscript claims."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Iterable, NamedTuple

from validation_common import CLAIM_TYPES, Issue, choose_exit, render


AUDITED_VALIDITY_LEVELS = {"V3", "V4"}
SUPPORTED_SOURCE_SUFFIXES = {".md", ".markdown", ".tex"}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
ASCII_TOKEN_LEFT = r"(?<![A-Za-z0-9_])"
ASCII_TOKEN_RIGHT = r"(?![A-Za-z0-9_])"


def english_risk_pattern(expression: str) -> re.Pattern[str]:
    return re.compile(
        ASCII_TOKEN_LEFT + expression + ASCII_TOKEN_RIGHT,
        re.IGNORECASE,
    )

ENGLISH_RISK_PATTERNS = (
    ("strong baseline", english_risk_pattern(r"strong\s+baseline")),
    ("zero regret", english_risk_pattern(r"zero\s+regret")),
    ("for any", english_risk_pattern(r"for\s+any")),
    ("interpolation", english_risk_pattern("interpolation")),
    ("guaranteed", english_risk_pattern("guaranteed")),
    ("sufficient", english_risk_pattern("sufficient")),
    ("universal", english_risk_pattern("universal")),
    ("necessary", english_risk_pattern("necessary")),
    ("provably", english_risk_pattern("provably")),
    ("lossless", english_risk_pattern("lossless")),
    ("bounded", english_risk_pattern("bounded")),
    ("online", english_risk_pattern("online")),
    ("exact", english_risk_pattern("exact")),
    ("first", english_risk_pattern("first")),
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
CHINESE_NON_RISK_CONTEXT_PATTERNS = {
    "充分": (
        re.compile(
            r"^充分利用(?:率)?"
            r"(?=$|[了着中内\s，。；：、！？）】]|缓存|资源|数据|信息|优势|能力|空间|时间)"
        ),
    ),
    "在线": (
        re.compile(
            r"^在线性(?:模型|回归|方程|代数|系统)"
            r"(?=$|[中内里下上\s，。；：、！？）】])"
        ),
        re.compile(
            r"^在线下(?:实验|场景|环境|测试|设置|数据)"
            r"(?=$|[中内里下上\s，。；：、！？）】])"
        ),
        re.compile(
            r"^在线下进行(?:实验|测试|评测|采集|训练)"
            r"(?=$|[中内里下上\s，。；：、！？）】])"
        ),
    ),
    "必要": (
        re.compile(
            r"^必要时"
            r"(?=$|[\s，。；：、！？）】]|重试|执行|进行|启动|停止|更新|返回|使用|调用)"
        ),
    ),
    "精确": (
        re.compile(
            r"^精确率"
            r"(?=$|[为是\s，。；：、！？）】]|指标|度量|分数|计算|达到|提升|下降|上升|无关|作为)"
        ),
    ),
}
GUARANTEE_DEPOSIT_PATTERN = re.compile(
    r"^保证金(?P<deposit_noun>额|制度|账户|比例|要求|条款|支付|退还|缴纳|收取)?"
    r"(?=$|[中内的\s，。；：、！？）】])"
)
GUARANTEE_DEPOSIT_VERB = re.compile(
    r"(?:缴纳|交纳|收取|退还|支付|扣除|返还|没收)[^，。；：、！？]{0,6}$"
)
FIRST_ORDINAL_CONTEXT_PATTERNS = (
    re.compile(
        r"^第一(?:步|章|节|阶段|轮|部分)"
        r"(?=$|[\s，。；：、！？）】]|"
        r"是|为|需|将|先|再|然后|开始|结束|完成|"
        r"提出|构建|介绍|讨论|分析|验证|收集|整理|执行|进行|"
        r"测试|评估|检查|开发|设计|实现|说明|描述|证明|给出)"
    ),
    re.compile(r"^第一项实验(?=$|[\s，。；：、！？）】]|检查|用于|比较|测量|验证|评估)"),
    re.compile(r"^第一篇文章(?=$|[\s，。；：、！？）】]|介绍|讨论|回顾|总结)"),
    re.compile(r"^第一套参数(?=$|[\s，。；：、！？）】]|用于|作为|包含|取值)"),
    re.compile(r"^第一款规定(?=$|[\s，。；：、！？）】]|适用|要求|说明)"),
)

MARKDOWN_THEOREM_HEADING = re.compile(
    r"^ {0,3}#{1,6}[ \t]+(?:\*\*|__)?"
    r"(?P<term>theorem|lemma|corollary)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
MARKDOWN_CHINESE_THEOREM_HEADING = re.compile(
    r"^ {0,3}#{1,6}[ \t]+(?:\*\*|__)?(?P<term>定理|引理|推论)"
)
PLAIN_THEOREM_TITLE = re.compile(
    r"^\s*(?:\*\*|__)?(?P<term>theorem|lemma|corollary)(?![A-Za-z0-9_])"
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
TEX_ENVIRONMENT_TOKEN = re.compile(
    r"\\(?P<action>begin|end)\{(?P<environment>[^{}]+)\}", re.IGNORECASE
)
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


class SourceSnapshot(NamedTuple):
    relative_path: str
    suffix: str
    text: str


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


def secure_directory_flags() -> int:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("secure_source_open_flags_unavailable")
    return (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )


def secure_file_flags() -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("secure_source_open_flags_unavailable")
    return (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )


def read_source_from_root_fd(
    root_fd: int, raw_path: str
) -> tuple[str, tuple[int, int]]:
    parts = PurePosixPath(raw_path).parts
    parent_fd = root_fd
    parent_fd_owned = False
    source_fd: int | None = None
    try:
        for component in parts[:-1]:
            next_fd = os.open(
                component,
                secure_directory_flags(),
                dir_fd=parent_fd,
            )
            if parent_fd_owned:
                os.close(parent_fd)
            parent_fd = next_fd
            parent_fd_owned = True
        source_fd = os.open(parts[-1], secure_file_flags(), dir_fd=parent_fd)
        metadata = os.fstat(source_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise IsADirectoryError("not_a_regular_file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8"), (metadata.st_dev, metadata.st_ino)
    finally:
        if source_fd is not None:
            os.close(source_fd)
        if parent_fd_owned:
            os.close(parent_fd)


def resolve_sources(
    root: Path, raw_sources: Any
) -> tuple[list[SourceSnapshot], list[Issue]]:
    if not string_list(raw_sources):
        return [], [
            Issue(
                "INVALID_INVENTORY_FIELD",
                "INVALID",
                "claim_inventory",
                "manuscript_sources:expected_nonempty_string_list",
            )
        ]

    sources: list[SourceSnapshot] = []
    issues: list[Issue] = []
    seen_declared: set[str] = set()
    seen_file_identities: set[tuple[int, int]] = set()
    root_fd = os.open(root, secure_directory_flags())
    try:
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
            suffix = PurePosixPath(raw_path).suffix.casefold()
            if suffix not in SUPPORTED_SOURCE_SUFFIXES:
                issues.append(
                    Issue(
                        "UNSUPPORTED_MANUSCRIPT_SOURCE",
                        "INVALID",
                        raw_path,
                        "expected_markdown_or_tex",
                    )
                )
                continue
            try:
                text, file_identity = read_source_from_root_fd(root_fd, raw_path)
            except FileNotFoundError:
                issues.append(
                    Issue(
                        "MISSING_MANUSCRIPT_SOURCE",
                        "INVALID",
                        raw_path,
                        "not_a_regular_file",
                    )
                )
                continue
            except OSError as error:
                if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                    issues.append(
                        Issue(
                            "UNSAFE_MANUSCRIPT_SOURCE",
                            "INVALID",
                            raw_path,
                            "symlink_or_unsafe_component",
                        )
                    )
                elif isinstance(error, IsADirectoryError):
                    issues.append(
                        Issue(
                            "MISSING_MANUSCRIPT_SOURCE",
                            "INVALID",
                            raw_path,
                            "not_a_regular_file",
                        )
                    )
                else:
                    issues.append(
                        Issue(
                            "UNREADABLE_MANUSCRIPT_SOURCE",
                            "INVALID",
                            raw_path,
                            type(error).__name__,
                        )
                    )
                continue
            except UnicodeError as error:
                issues.append(
                    Issue(
                        "UNREADABLE_MANUSCRIPT_SOURCE",
                        "INVALID",
                        raw_path,
                        type(error).__name__,
                    )
                )
                continue
            if file_identity in seen_file_identities:
                issues.append(
                    Issue(
                        "DUPLICATE_MANUSCRIPT_SOURCE",
                        "INVALID",
                        raw_path,
                        "duplicate_file_identity",
                    )
                )
                continue
            seen_file_identities.add(file_identity)
            sources.append(SourceSnapshot(raw_path, suffix, text))
    finally:
        os.close(root_fd)
    return sources, issues


def matches_for_line(line: str) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    for canonical_term, pattern in ENGLISH_RISK_PATTERNS:
        matches.extend((match.start(), canonical_term) for match in pattern.finditer(line))
    for match in CHINESE_RISK_PATTERN.finditer(line):
        term = match.group(0)
        lexical_context = line[match.start() :]
        if term == "保证":
            deposit_match = GUARANTEE_DEPOSIT_PATTERN.match(lexical_context)
            preceding_context = line[: match.start()]
            if deposit_match and (
                deposit_match.group("deposit_noun") is not None
                or GUARANTEE_DEPOSIT_VERB.search(preceding_context)
                or deposit_match.end() == len(lexical_context)
                or lexical_context[deposit_match.end()] in "，。；：、！？）】"
            ):
                continue
        if (
            term == "第一"
            and any(
                pattern.match(lexical_context)
                for pattern in FIRST_ORDINAL_CONTEXT_PATTERNS
            )
        ):
            continue
        if any(
            pattern.match(lexical_context)
            for pattern in CHINESE_NON_RISK_CONTEXT_PATTERNS.get(term, ())
        ):
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


def markdown_strip_blockquotes(line: str) -> tuple[str, int]:
    content = line
    depth = 0
    while True:
        indent_characters, indent_columns = markdown_indentation(content)
        if indent_columns > 3 or content[indent_characters : indent_characters + 1] != ">":
            return content, depth
        content = content[indent_characters + 1 :]
        depth += 1
        if content.startswith((" ", "\t")):
            content = content[1:]


def markdown_consume_blockquote_depth(line: str, depth: int) -> str | None:
    content = line
    for _ in range(depth):
        indent_characters, indent_columns = markdown_indentation(content)
        if (
            indent_columns > 3
            or content[indent_characters : indent_characters + 1] != ">"
        ):
            return None
        content = content[indent_characters + 1 :]
        if content.startswith((" ", "\t")):
            content = content[1:]
    return content


def markdown_list_item(
    content: str, base_content_indent: int
) -> tuple[str, int] | None:
    indent_characters, indent_columns = markdown_indentation(content)
    if not base_content_indent <= indent_columns <= base_content_indent + 3:
        return None
    marker_match = re.match(r"(?:[-+*]|\d{1,9}[.)])", content[indent_characters:])
    if marker_match is None:
        return None
    spacing_start = indent_characters + marker_match.end()
    spacing_characters, spacing_columns = markdown_indentation(content[spacing_start:])
    if spacing_start + spacing_characters == len(content):
        content_indent = indent_columns + marker_match.end() + 1
        return "", content_indent
    if spacing_characters == 0:
        return None
    content_start = spacing_start + spacing_characters
    marker_columns = marker_match.end()
    content_indent = indent_columns + marker_columns + spacing_columns
    return content[content_start:], content_indent


def markdown_strip_content_indent(content: str, content_indent: int) -> str | None:
    cursor = 0
    columns = 0
    while cursor < len(content) and columns < content_indent:
        character = content[cursor]
        if character == " ":
            columns += 1
        elif character == "\t":
            columns += 4 - (columns % 4)
        else:
            return None
        cursor += 1
    if columns < content_indent:
        return None
    return " " * (columns - content_indent) + content[cursor:]


def markdown_scannable_lines(lines: list[str]) -> Iterable[tuple[int, str, str]]:
    fence_character: str | None = None
    fence_length = 0
    fence_blockquote_depth = 0
    fence_list_path: tuple[int, ...] = ()
    list_path: list[int] = []
    list_blockquote_depth: int | None = None
    for line_number, line in enumerate(lines, start=1):
        if fence_character is not None:
            if fence_blockquote_depth == 0 and not fence_list_path:
                container_content = line
                inside_fence_scope = True
            else:
                consumed_content = markdown_consume_blockquote_depth(
                    line, fence_blockquote_depth
                )
                inside_fence_scope = consumed_content is not None
                container_content = consumed_content or ""
                if inside_fence_scope and fence_list_path:
                    continuation = markdown_strip_content_indent(
                        container_content, fence_list_path[-1]
                    )
                    if continuation is not None:
                        container_content = continuation
                    elif container_content.strip():
                        inside_fence_scope = False
                    else:
                        container_content = ""
            if inside_fence_scope:
                indent_characters, indent_columns = markdown_indentation(
                    container_content
                )
                candidate = (
                    container_content[indent_characters:]
                    if indent_columns <= 3
                    else ""
                )
                closing = re.match(
                    rf"{re.escape(fence_character)}{{{fence_length},}}[ \t]*\Z",
                    candidate,
                )
                if closing:
                    fence_character = None
                    fence_length = 0
                    fence_blockquote_depth = 0
                    fence_list_path = ()
                continue
            fence_character = None
            fence_length = 0
            fence_blockquote_depth = 0
            fence_list_path = ()

        container_content, blockquote_depth = markdown_strip_blockquotes(line)
        if list_path and list_blockquote_depth != blockquote_depth:
            list_path.clear()
            list_blockquote_depth = None

        if container_content.strip():
            _, leading_columns = markdown_indentation(container_content)
            while list_path and leading_columns < list_path[-1]:
                list_path.pop()
            if not list_path:
                list_blockquote_depth = None

            base_content_indent = list_path[-1] if list_path else 0
            list_item = markdown_list_item(
                container_content, base_content_indent
            )
            if list_item is not None:
                container_content, content_indent = list_item
                list_path.append(content_indent)
                list_blockquote_depth = blockquote_depth
            elif list_path:
                continuation = markdown_strip_content_indent(
                    container_content, list_path[-1]
                )
                if continuation is not None:
                    container_content = continuation
        else:
            container_content = ""

        indent_characters, indent_columns = markdown_indentation(container_content)
        candidate = (
            container_content[indent_characters:] if indent_columns <= 3 else ""
        )
        opening = re.match(r"(?P<marker>`{3,}|~{3,})", candidate)
        if opening:
            marker = opening.group("marker")
            fence_character = marker[0]
            fence_length = len(marker)
            fence_blockquote_depth = blockquote_depth
            fence_list_path = tuple(list_path)
            continue
        if indent_columns >= 4:
            continue
        yield line_number, line, candidate


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
        visible_line = strip_tex_comment(line)
        fragment_start = 0
        for token in TEX_ENVIRONMENT_TOKEN.finditer(visible_line):
            environment = token.group("environment").casefold()
            action = token.group("action").casefold()
            if code_environment is not None:
                if action == "end" and environment == code_environment:
                    code_environment = None
                    fragment_start = token.end()
                continue
            if environment not in TEX_CODE_ENVIRONMENTS or action != "begin":
                continue
            fragment = visible_line[fragment_start : token.start()]
            if fragment:
                yield line_number, line, fragment
            code_environment = environment
        if code_environment is None:
            fragment = visible_line[fragment_start:]
            if fragment:
                yield line_number, line, fragment


def scan_sources(
    sources: Iterable[SourceSnapshot],
) -> tuple[dict[str, tuple[str, int, str]], list[Issue]]:
    occurrences: dict[str, tuple[str, int, str]] = {}
    ordinals: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    issues: list[Issue] = []
    for relative_path, suffix, text in sources:
        lines = text.splitlines()
        scannable_lines = (
            tex_scannable_lines(lines)
            if suffix == ".tex"
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
    claim_type = claim.get("claim_type")
    if isinstance(claim_type, str) and claim_type not in CLAIM_TYPES:
        issues.append(
            Issue(
                "INVALID_CLAIM_TYPE",
                "INVALID",
                str(claim_id) if nonempty_string(claim_id) else item_id,
                f"claim_type:unknown:{claim_type}",
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
