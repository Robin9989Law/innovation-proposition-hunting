from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import mock

from tests.helpers import (
    REPOSITORY_ROOT,
    append_text,
    load_json,
    make_valid_project,
    run_script,
    run_validator,
    write_json,
)


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

ALLOWED_CLAIM_TYPES = (
    "THEOREM",
    "LEMMA",
    "COROLLARY",
    "PROPOSITION",
    "DEFINITION",
    "ALGORITHM",
    "ALGORITHM_GUARANTEE",
    "ALGORITHM_PERFORMANCE",
    "ONLINE_ALGORITHM",
    "METHOD",
    "ONLINE",
    "PROTOCOL",
    "EMPIRICAL",
    "BASELINE",
    "COMPLEXITY",
)


def load_claim_validator_module():
    module_path = REPOSITORY_ROOT / "scripts" / "validate_claim_inventory.py"
    module_name = "claim_validator_under_test"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load claim validator module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    scripts_path = str(module_path.parent)
    sys.path.insert(0, scripts_path)
    previous_module = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts_path)
        if previous_module is None:
            del sys.modules[module_name]
        else:
            sys.modules[module_name] = previous_module
    return module


def expected_occurrence_id(
    relative_path: str, line: str, term: str, ordinal: int
) -> str:
    normalized = " ".join(line.split()).casefold()
    raw = f"{relative_path}\0{term.casefold()}\0{normalized}\0{ordinal}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def claim(
    occurrence_ids: list[str],
    *,
    claim_id: str = "C-0001",
    statement: str = "The exact inverse is recovered.",
    validation_epoch: int = 1,
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "statement": statement,
        "claim_type": "THEOREM",
        "locations": ["manuscript.md:1"],
        "evidence_responsibility": "Supply a proof of the published statement.",
        "risk_terms": ["exact"],
        "status": "FROZEN",
        "validation_epoch": validation_epoch,
        "occurrence_ids": occurrence_ids,
    }


def set_inventory(
    project: Path,
    *,
    claims: list[dict[str, Any]],
    sources: list[str] | None = None,
    validation_epoch: int = 1,
) -> None:
    write_json(
        project / "claim_inventory.json",
        {
            "schema_version": "2.0",
            "validation_epoch": validation_epoch,
            "manuscript_sources": sources or ["manuscript.md"],
            "claims": claims,
        },
    )


class ClaimInventoryTests(unittest.TestCase):
    def make_project(
        self, *, validity_level: str = "V2"
    ) -> tuple[object, Path]:
        temporary_directory, project = make_valid_project(
            claim_profile="THEORY", validity_level=validity_level
        )
        self.addCleanup(temporary_directory.cleanup)
        return temporary_directory, project

    def test_unregistered_exact_claim_fails_before_independent_audit(self) -> None:
        _, project = self.make_project(validity_level="V2")
        (project / "manuscript.md").write_text(
            "The exact inverse recovers every anomaly losslessly.\n",
            encoding="utf-8",
        )
        set_inventory(project, claims=[])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("UNREGISTERED_HIGH_RISK_CLAIM", completed.stdout)

    def test_claim_type_is_a_closed_enum(self) -> None:
        _, project = self.make_project()
        inventory = load_json(project / "claim_inventory.json")
        inventory["claims"][1]["claim_type"] = "NOT_ALGORITHM"
        write_json(project / "claim_inventory.json", inventory)

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode)
        self.assertIn("INVALID_CLAIM_TYPE", completed.stdout)

    def test_algorithm_profile_rejects_theorem_phrasing(self) -> None:
        """R-EMPIRICAL-07：ALGORITHM profile 下经验 claim 用定理级措辞即升格。"""
        temporary_directory, project = make_valid_project(claim_profile="ALGORITHM")
        self.addCleanup(temporary_directory.cleanup)
        inventory = load_json(project / "claim_inventory.json")
        for claim in inventory["claims"]:
            if claim.get("claim_type") == "ALGORITHM":
                claim["statement"] = (
                    claim.get("statement", "") + " This is provably optimal."
                )
                break
        write_json(project / "claim_inventory.json", inventory)

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("CLAIM_STRENGTH_EXCEEDS_PROFILE", completed.stdout)

    def test_theory_profile_allows_theorem_phrasing(self) -> None:
        """THEORY profile 有 theory obligations 审查，不报措辞升格。"""
        temporary_directory, project = make_valid_project(claim_profile="THEORY")
        self.addCleanup(temporary_directory.cleanup)
        inventory = load_json(project / "claim_inventory.json")
        for claim in inventory["claims"]:
            if claim.get("claim_type") == "THEOREM":
                claim["statement"] = (
                    claim.get("statement", "") + " This is provably optimal."
                )
                break
        write_json(project / "claim_inventory.json", inventory)

        completed = run_script("validate_claim_inventory.py", project)

        self.assertNotIn("CLAIM_STRENGTH_EXCEEDS_PROFILE", completed.stdout)

    def test_documented_claim_type_enum_members_are_accepted(self) -> None:
        for claim_type in ALLOWED_CLAIM_TYPES:
            with self.subTest(claim_type=claim_type):
                _, project = self.make_project()
                inventory = load_json(project / "claim_inventory.json")
                inventory["claims"][1]["claim_type"] = claim_type
                write_json(project / "claim_inventory.json", inventory)

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    0, completed.returncode, completed.stdout + completed.stderr
                )

    def test_english_terms_are_case_insensitive(self) -> None:
        for term in ("EXACT", "Universal", "BoUnDeD"):
            with self.subTest(term=term):
                _, project = self.make_project(validity_level="V1")
                (project / "manuscript.md").write_text(
                    f"This is a {term} conclusion.\n", encoding="utf-8"
                )
                set_inventory(project, claims=[])

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("UNREGISTERED_HIGH_RISK_CLAIM", completed.stdout)

    def test_english_terms_use_ascii_identifier_boundaries(self) -> None:
        _, project = self.make_project(validity_level="V2")
        claimed_line = "该方法EXACT恢复并支持ONLINE学习。"
        identifier_line = "inexact online_update firstOrder bounded2"
        (project / "manuscript.md").write_text(
            f"{claimed_line}\n{identifier_line}\n", encoding="utf-8"
        )
        expected = [
            expected_occurrence_id("manuscript.md", claimed_line, "exact", 1),
            expected_occurrence_id("manuscript.md", claimed_line, "online", 1),
        ]
        set_inventory(project, claims=[claim(expected)])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("claim_inventory_status=READY", completed.stdout)

    def test_chinese_equivalents_are_scanned(self) -> None:
        _, project = self.make_project(validity_level="V0")
        (project / "manuscript.md").write_text(
            "该结论是精确、普适、普遍且有界的。\n", encoding="utf-8"
        )
        set_inventory(project, claims=[])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("claim_inventory_issues=4", completed.stdout)
        self.assertEqual(4, completed.stdout.count("UNREGISTERED_HIGH_RISK_CLAIM"))

    def test_chinese_lexical_context_disambiguation_table(self) -> None:
        cases = (
            ("linear_model", "在线性模型中报告描述性统计。", ()),
            ("online_performance", "本文提供在线性能界。", ("在线",)),
            ("online_learning", "该方法用于在线学习。", ("在线",)),
            ("offline_experiment", "我们在线下实验中比较方法。", ()),
            ("offline_scene", "在线下场景中采集数据。", ()),
            ("online_lower_bound", "该算法达到在线下界。", ("在线",)),
            ("security_deposit", "需要缴纳保证金。", ()),
            ("guarantee_finance", "该约束保证金融系统稳定。", ("保证",)),
            ("guarantee_metal", "该约束保证金属结构稳定。", ("保证",)),
            ("make_full_use", "我们充分利用缓存。", ()),
            ("sufficient_condition", "充分条件成立。", ("充分",)),
            ("when_necessary", "必要时重试。", ()),
            ("necessary_condition", "必要条件如下。", ("必要",)),
            ("precision_metric", "采用精确率作为指标。", ()),
            ("precision_then_exact", "精确率指标不影响精确界。", ("精确",)),
            ("first_kind", "我们提出第一种无需标签的方法。", ("第一",)),
            ("first_class", "我们提出第一类无需标签的方法。", ("第一",)),
            ("first_instance", "这是第一个满足该界的算法。", ("第一",)),
            ("first_suite", "我们开发了第一套公开评测协议。", ("第一",)),
            ("first_gait_model", "我们提出第一步态识别模型。", ("第一",)),
            ("first_step", "第一步是整理数据。", ()),
            ("first_step_with_claim_cue", "第一步提出候选方法。", ()),
            ("first_chapter", "第一章介绍背景。", ()),
            ("first_chapter_with_claim_cue", "第一章提出研究问题。", ()),
            ("first_section", "第一节讨论设置。", ()),
            ("first_stage", "第一阶段收集数据。", ()),
            ("first_stage_with_claim_cue", "第一阶段构建模型。", ()),
            ("numbered_item", "第一项实验检查缓存。", ()),
            ("numbered_paper", "第一篇文章介绍背景。", ()),
            ("numbered_suite", "第一套参数用于调试。", ()),
            ("numbered_clause", "第一款规定适用于本节。", ()),
        )
        for label, line, expected_terms in cases:
            with self.subTest(label=label):
                _, project = self.make_project(validity_level="V2")
                (project / "manuscript.md").write_text(
                    line + "\n", encoding="utf-8"
                )
                set_inventory(project, claims=[])

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1 if expected_terms else 0,
                    completed.returncode,
                    completed.stdout + completed.stderr,
                )
                self.assertEqual(
                    len(expected_terms),
                    completed.stdout.count("UNREGISTERED_HIGH_RISK_CLAIM"),
                )
                ordinals: dict[str, int] = {}
                for term in expected_terms:
                    ordinals[term] = ordinals.get(term, 0) + 1
                    identifier = expected_occurrence_id(
                        "manuscript.md", line, term, ordinals[term]
                    )
                    self.assertIn(identifier, completed.stdout)
                    self.assertIn(f"term:{term}", completed.stdout)

    def test_theorem_headings_and_tex_environments_are_scanned(self) -> None:
        _, project = self.make_project(validity_level="V2")
        (project / "manuscript.md").write_text(
            "# Theorem 1\n## 引理 2\n**Corollary 3.**\n定理 4.\n",
            encoding="utf-8",
        )
        (project / "appendix.tex").write_text(
            "\\begin{corollary}\n\\begin{lemma*}\n", encoding="utf-8"
        )
        set_inventory(project, claims=[], sources=["manuscript.md", "appendix.tex"])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("claim_inventory_issues=6", completed.stdout)

    def test_markdown_code_and_malformed_headings_are_ignored(self) -> None:
        _, project = self.make_project(validity_level="V2")
        (project / "manuscript.md").write_text(
            "    # Theorem in indented code\n"
            "\t# Lemma in tab-indented code\n"
            "  \tCorollary 7 in mixed tab-indented code\n"
            "#Theorem without required heading space\n"
            "```markdown\n"
            "# Corollary inside a backtick fence\n"
            "The exact result inside code.\n"
            "```\n"
            "~~~tex\n"
            "\\begin{theorem}\n"
            "~~~\n",
            encoding="utf-8",
        )
        set_inventory(project, claims=[])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("claim_inventory_status=READY", completed.stdout)

    def test_markdown_real_heading_after_fence_is_scanned(self) -> None:
        _, project = self.make_project(validity_level="V2")
        (project / "manuscript.md").write_text(
            "```\n# Theorem inside code\n```\n# Theorem outside code\n",
            encoding="utf-8",
        )
        set_inventory(project, claims=[])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual(1, completed.stdout.count("UNREGISTERED_HIGH_RISK_CLAIM"))

    def test_markdown_containers_preserve_fences_and_content_indentation(self) -> None:
        _, project = self.make_project(validity_level="V2")
        list_prose = "  The exact result after the list fence."
        quote_heading = "> # Theorem after the quoted fence."
        list_heading = "- # Lemma list item."
        continuation = "     The universal list continuation."
        (project / "manuscript.md").write_text(
            "- ````markdown\n"
            "  The exact result inside list code.\n"
            "  ```\n"
            "  Still bounded inside list code.\n"
            "  ````\n"
            f"{list_prose}\n"
            "> ~~~\n"
            "> The exact result inside quoted code.\n"
            "> ~~~\n"
            f"{quote_heading}\n"
            f"{list_heading}\n"
            "123. Context.\n"
            f"{continuation}\n",
            encoding="utf-8",
        )
        expected = [
            expected_occurrence_id("manuscript.md", list_prose, "exact", 1),
            expected_occurrence_id("manuscript.md", quote_heading, "theorem", 1),
            expected_occurrence_id("manuscript.md", list_heading, "lemma", 1),
            expected_occurrence_id(
                "manuscript.md", continuation, "universal", 1
            ),
        ]
        set_inventory(project, claims=[claim(expected)])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("claim_inventory_status=READY", completed.stdout)

    def test_markdown_unclosed_fences_end_with_their_container_scope(self) -> None:
        cases = (
            (
                "blockquote",
                "> ```\n> The exact hidden result.\n# Theorem 1\n",
                "# Theorem 1",
                "theorem",
            ),
            (
                "list",
                "- ```\n  The exact hidden result.\n# Lemma 1\n",
                "# Lemma 1",
                "lemma",
            ),
            (
                "root",
                "```\nThe exact hidden result.\n# Corollary 1\n",
                None,
                None,
            ),
        )
        for label, manuscript, visible_line, term in cases:
            with self.subTest(label=label):
                _, project = self.make_project(validity_level="V2")
                (project / "manuscript.md").write_text(
                    manuscript, encoding="utf-8"
                )
                expected = (
                    [
                        expected_occurrence_id(
                            "manuscript.md", visible_line, term, 1
                        )
                    ]
                    if visible_line is not None and term is not None
                    else []
                )
                set_inventory(
                    project,
                    claims=[claim(expected)] if expected else [],
                )

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    0, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("claim_inventory_status=READY", completed.stdout)

    def test_markdown_nested_list_fences_follow_the_full_container_path(self) -> None:
        cases = (
            (
                "reviewer_example",
                (
                    "- item",
                    "  - ```",
                    "    The exact hidden result.",
                    "    ```",
                    "# Theorem 1",
                ),
                (("# Theorem 1", "theorem"),),
            ),
            (
                "three_levels_and_sibling",
                (
                    "- outer",
                    "  - middle",
                    "    - ````",
                    "      The exact hidden result.",
                    "      ````",
                    "    The universal middle prose.",
                    "  The bounded outer prose.",
                    "- The necessary sibling item.",
                ),
                (
                    ("    The universal middle prose.", "universal"),
                    ("  The bounded outer prose.", "bounded"),
                    ("- The necessary sibling item.", "necessary"),
                ),
            ),
            (
                "blockquote_nested_list",
                (
                    "> - outer",
                    ">   - ```",
                    ">     The exact hidden result.",
                    ">     ```",
                    ">   The universal outer prose.",
                    "# Lemma 1",
                ),
                (
                    (">   The universal outer prose.", "universal"),
                    ("# Lemma 1", "lemma"),
                ),
            ),
        )
        for label, lines, expected_claims in cases:
            with self.subTest(label=label):
                _, project = self.make_project(validity_level="V2")
                (project / "manuscript.md").write_text(
                    "\n".join(lines) + "\n", encoding="utf-8"
                )
                expected = [
                    expected_occurrence_id("manuscript.md", line, term, 1)
                    for line, term in expected_claims
                ]
                set_inventory(project, claims=[claim(expected)])

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    0, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("claim_inventory_status=READY", completed.stdout)

    def test_markdown_empty_list_markers_and_extra_quotes_bound_fences(self) -> None:
        marker_cases = (
            ("dash", "-", 2),
            ("asterisk", "*", 2),
            ("plus", "+", 2),
            ("ordered_dot", "1.", 3),
            ("ordered_parenthesis", "1)", 3),
            ("dash_trailing_spaces", "-   ", 2),
            ("ordered_trailing_spaces", "1.   ", 3),
        )
        cases = [
            (
                f"empty_{label}",
                (
                    marker,
                    " " * content_indent + "```",
                    " " * content_indent + "The exact hidden result.",
                    "# Theorem 1",
                ),
                (("# Theorem 1", "theorem"),),
            )
            for label, marker, content_indent in marker_cases
        ]
        cases.extend(
            (
                (
                    "nested_empty_list",
                    (
                        "- outer",
                        "  -",
                        "    ```",
                        "    The exact hidden result.",
                        "  The universal outer result.",
                        "# Lemma 1",
                    ),
                    (
                        ("  The universal outer result.", "universal"),
                        ("# Lemma 1", "lemma"),
                    ),
                ),
                (
                    "extra_blockquotes_are_fence_content",
                    (
                        "> ```",
                        "> > The exact hidden result.",
                        "> > > The universal hidden result.",
                        "> ```",
                        "# Corollary 1",
                    ),
                    (("# Corollary 1", "corollary"),),
                ),
                (
                    "extra_blockquotes_inside_empty_list_fence",
                    (
                        "> -",
                        ">   ```",
                        ">   > The exact hidden result.",
                        ">   > > The universal hidden result.",
                        ">   ```",
                        "# Theorem 2",
                    ),
                    (("# Theorem 2", "theorem"),),
                ),
            )
        )
        for label, lines, expected_claims in cases:
            with self.subTest(label=label):
                _, project = self.make_project(validity_level="V2")
                (project / "manuscript.md").write_text(
                    "\n".join(lines) + "\n", encoding="utf-8"
                )
                expected = [
                    expected_occurrence_id("manuscript.md", line, term, 1)
                    for line, term in expected_claims
                ]
                set_inventory(project, claims=[claim(expected)])

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    0, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("claim_inventory_status=READY", completed.stdout)

    def test_tex_comments_and_code_environments_are_ignored(self) -> None:
        _, project = self.make_project(validity_level="V2")
        (project / "appendix.tex").write_text(
            "% \\begin{theorem}\n"
            "\\begin{verbatim}\n\\begin{theorem}\n\\end{verbatim}\n"
            "\\begin{lstlisting}\n\\begin{lemma}\n\\end{lstlisting}\n"
            "\\begin{minted}{tex}\n\\begin{corollary}\n\\end{minted}\n",
            encoding="utf-8",
        )
        set_inventory(project, claims=[], sources=["appendix.tex"])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("claim_inventory_status=READY", completed.stdout)

    def test_tex_real_theorem_after_code_environment_is_scanned(self) -> None:
        _, project = self.make_project(validity_level="V2")
        (project / "appendix.tex").write_text(
            "\\begin{verbatim}\n\\begin{theorem}\n\\end{verbatim}\n"
            "\\begin{theorem} % real environment\n",
            encoding="utf-8",
        )
        set_inventory(project, claims=[], sources=["appendix.tex"])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual(1, completed.stdout.count("UNREGISTERED_HIGH_RISK_CLAIM"))

    def test_tex_code_environments_scan_only_outside_ordered_segments(self) -> None:
        _, project = self.make_project(validity_level="V2")
        same_line = (
            r"The exact prefix. \begin{verbatim} exact hidden "
            r"\end{verbatim} The exact suffix."
        )
        ordinary_then_code = (
            r"\begin{theorem}\begin{lstlisting}exact hidden"
            r"\end{lstlisting}\begin{lemma}"
        )
        cross_line_open = r"The universal prefix. \begin{minted*}{tex}"
        hidden_line = r"exact hidden \begin{corollary}"
        cross_line_close = (
            r"\end{minted*} The bounded suffix. "
            r"\begin{verbatim*}lossless hidden\end{verbatim*} "
            r"The necessary suffix. % exact comment"
        )
        multiple_transitions = (
            r"\begin{lstlisting}exact hidden\end{lstlisting} "
            r"The guaranteed result. "
            r"\begin{minted}{tex}bounded hidden\end{minted} "
            r"The sufficient result."
        )
        lines = (
            same_line,
            ordinary_then_code,
            cross_line_open,
            hidden_line,
            cross_line_close,
            multiple_transitions,
        )
        (project / "appendix.tex").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        expected = [
            expected_occurrence_id("appendix.tex", same_line, "exact", 1),
            expected_occurrence_id("appendix.tex", same_line, "exact", 2),
            expected_occurrence_id("appendix.tex", ordinary_then_code, "theorem", 1),
            expected_occurrence_id("appendix.tex", ordinary_then_code, "lemma", 1),
            expected_occurrence_id("appendix.tex", cross_line_open, "universal", 1),
            expected_occurrence_id("appendix.tex", cross_line_close, "bounded", 1),
            expected_occurrence_id("appendix.tex", cross_line_close, "necessary", 1),
            expected_occurrence_id(
                "appendix.tex", multiple_transitions, "guaranteed", 1
            ),
            expected_occurrence_id(
                "appendix.tex", multiple_transitions, "sufficient", 1
            ),
        ]
        set_inventory(project, claims=[claim(expected)], sources=["appendix.tex"])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("claim_inventory_status=READY", completed.stdout)

    def test_tex_code_environments_are_opaque_and_non_nesting(self) -> None:
        environments = (
            ("verbatim", ""),
            ("verbatim*", ""),
            ("lstlisting", ""),
            ("lstlisting*", ""),
            ("minted", "{python}"),
            ("minted*", "{python}"),
        )
        for environment, arguments in environments:
            with self.subTest(environment=environment):
                _, project = self.make_project(validity_level="V2")
                opening = rf"\begin{{{environment}}}{arguments}"
                literal_begin = (
                    rf"\begin{{{environment}}}{arguments} "
                    "The bounded hidden result."
                )
                closing = (
                    rf"\end{{{environment}}} The exact visible suffix. "
                    r"\begin{verbatim} The universal hidden result. "
                    r"\end{verbatim} The necessary visible suffix."
                )
                (project / "appendix.tex").write_text(
                    "\n".join((opening, literal_begin, closing)) + "\n",
                    encoding="utf-8",
                )
                expected = [
                    expected_occurrence_id("appendix.tex", closing, "exact", 1),
                    expected_occurrence_id(
                        "appendix.tex", closing, "necessary", 1
                    ),
                ]
                set_inventory(
                    project,
                    claims=[claim(expected)],
                    sources=["appendix.tex"],
                )

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    0, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("claim_inventory_status=READY", completed.stdout)

    def test_normal_prose_without_risk_terms_is_ready(self) -> None:
        _, project = self.make_project(validity_level="V2")

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("claim_inventory_status=READY", completed.stdout)

    def test_registered_case_variant_uses_stable_occurrence_id(self) -> None:
        _, project = self.make_project(validity_level="V2")
        line = "The EXACT inverse is recovered."
        (project / "manuscript.md").write_text(line + "\n", encoding="utf-8")
        occurrence = expected_occurrence_id("manuscript.md", line, "exact", 1)
        set_inventory(project, claims=[claim([occurrence], statement=line)])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_duplicate_identical_lines_have_distinct_ordinals(self) -> None:
        _, project = self.make_project(validity_level="V2")
        line = "The exact inverse is recovered."
        (project / "manuscript.md").write_text(
            f"{line}\n{line}\n", encoding="utf-8"
        )
        first = expected_occurrence_id("manuscript.md", line, "exact", 1)
        second = expected_occurrence_id("manuscript.md", line, "exact", 2)
        self.assertNotEqual(first, second)
        set_inventory(project, claims=[claim([first, second])])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_occurrence_cannot_be_bound_to_two_claims(self) -> None:
        _, project = self.make_project(validity_level="V2")
        line = "The exact inverse is recovered."
        (project / "manuscript.md").write_text(line + "\n", encoding="utf-8")
        occurrence = expected_occurrence_id("manuscript.md", line, "exact", 1)
        set_inventory(
            project,
            claims=[
                claim([occurrence], claim_id="C-0001"),
                claim([occurrence], claim_id="C-0002"),
            ],
        )

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("DUPLICATE_OCCURRENCE_BINDING", completed.stdout)

    def test_inventory_binding_must_reference_a_scanned_occurrence(self) -> None:
        _, project = self.make_project(validity_level="V2")
        set_inventory(project, claims=[claim(["f" * 64])])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("ORPHAN_OCCURRENCE_BINDING", completed.stdout)

    def test_every_required_claim_field_is_enforced(self) -> None:
        for field in REQUIRED_CLAIM_FIELDS:
            with self.subTest(field=field):
                _, project = self.make_project(validity_level="V2")
                malformed = claim([])
                malformed.pop(field)
                set_inventory(project, claims=[malformed])

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("INVALID_CLAIM_FIELD", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_claim_field_types_are_strictly_validated(self) -> None:
        malformed_values = {
            "claim_id": 7,
            "statement": [],
            "claim_type": {},
            "locations": "manuscript.md:1",
            "evidence_responsibility": 3,
            "risk_terms": "exact",
            "status": [],
            "validation_epoch": True,
            "occurrence_ids": "f" * 64,
        }
        for field, value in malformed_values.items():
            with self.subTest(field=field):
                _, project = self.make_project(validity_level="V2")
                malformed = claim([])
                malformed[field] = value
                set_inventory(project, claims=[malformed])

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("INVALID_CLAIM_FIELD", completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_duplicate_claim_ids_are_invalid(self) -> None:
        _, project = self.make_project(validity_level="V2")
        set_inventory(project, claims=[claim([]), claim([])])

        completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("DUPLICATE_CLAIM_ID", completed.stdout)

    def test_claim_and_inventory_epochs_must_match_state(self) -> None:
        for target in ("claim", "inventory"):
            with self.subTest(target=target):
                _, project = self.make_project(validity_level="V2")
                claims = [claim([], validation_epoch=2)] if target == "claim" else []
                set_inventory(
                    project,
                    claims=claims,
                    validation_epoch=2 if target == "inventory" else 1,
                )

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn("VALIDATION_EPOCH_MISMATCH", completed.stdout)

    def test_malformed_json_and_top_level_types_are_stably_invalid(self) -> None:
        _, project = self.make_project(validity_level="V2")
        for raw, code in (
            ("{not json\n", "INVALID_CLAIM_INVENTORY_JSON"),
            ("[]\n", "INVALID_CLAIM_INVENTORY"),
        ):
            with self.subTest(raw=raw):
                (project / "claim_inventory.json").write_text(raw, encoding="utf-8")

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn(code, completed.stdout)
                self.assertNotIn("Traceback", completed.stderr)

    def test_inventory_structure_types_are_stably_invalid(self) -> None:
        cases = (
            ({"schema_version": "1.0", "manuscript_sources": [], "claims": []},
             "INVALID_INVENTORY_FIELD"),
            ({"schema_version": "2.0", "manuscript_sources": "manuscript.md", "claims": []},
             "INVALID_INVENTORY_FIELD"),
            ({"schema_version": "2.0", "manuscript_sources": ["manuscript.md"], "claims": {}},
             "INVALID_INVENTORY_FIELD"),
        )
        _, project = self.make_project(validity_level="V2")
        for payload, code in cases:
            with self.subTest(payload=payload):
                write_json(project / "claim_inventory.json", payload)

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn(code, completed.stdout)

    def test_source_paths_are_relative_supported_and_unique(self) -> None:
        _, project = self.make_project(validity_level="V2")
        cases = (
            (["../outside.md"], "UNSAFE_MANUSCRIPT_SOURCE"),
            ([str((project / "manuscript.md").resolve())], "UNSAFE_MANUSCRIPT_SOURCE"),
            (["workflow_state.json"], "UNSUPPORTED_MANUSCRIPT_SOURCE"),
            (["manuscript.md", "manuscript.md"], "DUPLICATE_MANUSCRIPT_SOURCE"),
            (["missing.md"], "MISSING_MANUSCRIPT_SOURCE"),
        )
        for sources, code in cases:
            with self.subTest(sources=sources):
                set_inventory(project, claims=[], sources=sources)

                completed = run_script("validate_claim_inventory.py", project)

                self.assertEqual(
                    1, completed.returncode, completed.stdout + completed.stderr
                )
                self.assertIn(code, completed.stdout)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_source_symlink_outside_root_is_rejected(self) -> None:
        _, project = self.make_project(validity_level="V2")
        with TemporaryDirectory(prefix="claim-inventory-outside-") as directory:
            outside = Path(directory) / "outside.md"
            outside.write_text("The exact result.\n", encoding="utf-8")
            (project / "linked.md").symlink_to(outside)
            set_inventory(project, claims=[], sources=["linked.md"])

            completed = run_script("validate_claim_inventory.py", project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("UNSAFE_MANUSCRIPT_SOURCE", completed.stdout)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_source_snapshot_survives_post_check_symlink_swap(self) -> None:
        module = load_claim_validator_module()
        _, project = self.make_project(validity_level="V2")
        source = project / "manuscript.md"
        source.write_text("Descriptive statistics only.\n", encoding="utf-8")
        set_inventory(project, claims=[])
        state = load_json(project / "workflow_state.json")
        inventory = load_json(project / "claim_inventory.json")
        original_scan = module.scan_sources
        with TemporaryDirectory(prefix="claim-inventory-outside-") as directory:
            outside = Path(directory) / "outside.md"
            outside.write_text("The exact external result.\n", encoding="utf-8")

            def swap_then_scan(sources):
                source.unlink()
                source.symlink_to(outside)
                return original_scan(sources)

            with mock.patch.object(
                module, "scan_sources", side_effect=swap_then_scan
            ):
                issues = module.validate(project.resolve(), state, inventory)

        self.assertEqual([], issues)

    def test_trusted_source_descriptors_are_all_closed(self) -> None:
        module = load_claim_validator_module()
        _, project = self.make_project(validity_level="V2")
        opened: list[int] = []
        closed: list[int] = []
        real_open = os.open
        real_close = os.close

        def tracked_open(*args, **kwargs):
            descriptor = real_open(*args, **kwargs)
            opened.append(descriptor)
            return descriptor

        def tracked_close(descriptor):
            closed.append(descriptor)
            return real_close(descriptor)

        with mock.patch.object(os, "open", side_effect=tracked_open), mock.patch.object(
            os, "close", side_effect=tracked_close
        ):
            sources, issues = module.resolve_sources(
                project.resolve(), ["manuscript.md"]
            )

        self.assertEqual([], issues)
        self.assertTrue(sources)
        self.assertTrue(opened)
        self.assertCountEqual(opened, closed)
        for descriptor in opened:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs unavailable")
    def test_fifo_source_is_rejected_without_blocking(self) -> None:
        _, project = self.make_project(validity_level="V2")
        fifo = project / "stream.md"
        os.mkfifo(fifo)
        set_inventory(project, claims=[], sources=["stream.md"])

        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY_ROOT / "scripts" / "validate_claim_inventory.py"),
                    "--root",
                    str(project),
                    "--state",
                    str(project / "workflow_state.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except subprocess.TimeoutExpired:
            self.fail("claim validator blocked while opening a FIFO source")

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("MISSING_MANUSCRIPT_SOURCE", completed.stdout)
        self.assertIn("not_a_regular_file", completed.stdout)

    def test_inventory_and_state_cli_paths_must_stay_within_root(self) -> None:
        _, project = self.make_project(validity_level="V2")
        with TemporaryDirectory(prefix="claim-inventory-outside-") as directory:
            outside = Path(directory)
            outside_inventory = outside / "claim_inventory.json"
            outside_inventory.write_bytes((project / "claim_inventory.json").read_bytes())
            outside_state = outside / "workflow_state.json"
            outside_state.write_bytes((project / "workflow_state.json").read_bytes())
            cases = (
                ("--inventory", outside_inventory),
                ("--state", outside_state),
            )
            for option, path in cases:
                with self.subTest(option=option):
                    completed = run_script(
                        "validate_claim_inventory.py",
                        project,
                        (option, str(path)),
                    )

                    self.assertEqual(
                        1, completed.returncode, completed.stdout + completed.stderr
                    )
                    self.assertIn("VALIDATOR_ERROR", completed.stdout)
                    self.assertIn("outside_root", completed.stdout)

    def test_post_audit_claim_promotion_is_rejected_by_validate_all(self) -> None:
        _, project = self.make_project(validity_level="V3")
        append_text(project / "manuscript.md", "The result is universally bounded.\n")

        completed = run_validator(project)

        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("CLAIM_PROMOTION_UNAUDITED", completed.stdout)

    def test_validate_all_claim_scan_is_read_only(self) -> None:
        _, project = self.make_project(validity_level="V2")
        before = {
            path.relative_to(project).as_posix(): path.read_bytes()
            for path in project.rglob("*")
            if path.is_file()
        }

        completed = run_validator(project)

        after = {
            path.relative_to(project).as_posix(): path.read_bytes()
            for path in project.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertIn("claim_inventory_status=READY", completed.stdout)


if __name__ == "__main__":
    unittest.main()
