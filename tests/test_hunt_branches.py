import io
import runpy
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hunt  # noqa: E402
from test_hunt import base, paper, ring, walk_to_open  # noqa: E402


def cli(*args: str) -> str:
    argv = sys.argv
    buf = io.StringIO()
    sys.argv = ["hunt", *args]
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            code = hunt.main()
    finally:
        sys.argv = argv
    if code != 0:
        raise AssertionError(code)
    return buf.getvalue()


def cli_fail(*args: str) -> SystemExit:
    argv = sys.argv
    sys.argv = ["hunt", *args]
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            hunt.main()
    except SystemExit as caught:
        return caught
    finally:
        sys.argv = argv
    raise AssertionError("命令应当停下来")


def triangle(anchor: str = "跳") -> dict:
    return base(
        paper(anchor, "负荷时移跳", "负荷，时移。", cited_by=["前", "后", "丙"], year=2019),
        ring("前", "负荷时移前", "负荷，时移。", references=[anchor, "后", "丙"], year=2025),
        ring("后", "负荷时移后", "负荷，时移。", references=[anchor, "前", "丙"], year=2024),
        ring("丙", "负荷时移丙", "负荷，时移。", references=[anchor, "前", "后"], year=2026),
    )


class FileTests(unittest.TestCase):
    def test_missing_or_broken_file_is_refused(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(SystemExit) as missing:
                hunt.load_state(root)
            self.assertIn("还没有名单", str(missing.exception))
            self.assertIn("neighbor_hunt.json", str(missing.exception))
            (root / hunt.STATE_NAME).write_text("[1, 2]", encoding="utf-8")
            with self.assertRaises(SystemExit) as broken:
                hunt.load_state(root)
            self.assertIn("坏了", str(broken.exception))

    def test_old_keys_are_refused_and_nulls_are_cleared(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / hunt.STATE_NAME
            path.write_text(
                '{"papers": [], "topic": {"跳": {"前": "yes"}}, "core_id": "前", "decisions": {}}',
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as caught:
                hunt.load_state(root)
            self.assertIn("旧格式", str(caught.exception))
            path.write_text(
                '{"papers": [], "topic": {}, "open_problem": "旧缝", "decisions": {}}',
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as caught:
                hunt.load_state(root)
            self.assertIn("旧格式", str(caught.exception))
            path.write_text(
                '{"papers": [], "topic": {}, "core_id": null, "open_problem": null, "decisions": {}}',
                encoding="utf-8",
            )
            loaded = hunt.load_state(root)
            self.assertNotIn("core_id", loaded)
            self.assertNotIn("open_problem", loaded)
            self.assertEqual({}, loaded["cores"])
            self.assertEqual({}, loaded["openings"])
            self.assertIsNone(loaded["fate"])
            self.assertEqual(hunt.date.today().year, loaded["this_year"])

    def test_save_roundtrip_keeps_chinese(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = hunt.blank_state("负荷", "时移", 2026)
            hunt.save_state(root, state)
            text = (root / hunt.STATE_NAME).read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertIn("负荷", text)
            self.assertEqual(state_path_name(root), hunt.STATE_NAME)
            loaded = hunt.load_state(root)
            self.assertEqual(["负荷"], loaded["object_names"])
            self.assertEqual(2026, loaded["this_year"])


def state_path_name(root: Path) -> str:
    return hunt.state_path(root).name


class NameAndPaperTests(unittest.TestCase):
    def test_names_ids_and_years_are_checked(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            hunt.require_name("   ")
        self.assertIn("不能是空的", str(caught.exception))
        self.assertEqual("负荷", hunt.require_name(" 负荷 "))
        self.assertEqual([], hunt.split_ids(None))
        self.assertEqual([], hunt.split_ids("  "))
        self.assertEqual(["甲", "乙"], hunt.split_ids(" 甲 , 乙 "))
        with self.assertRaises(SystemExit) as empty_part:
            hunt.split_ids("甲,,乙")
        self.assertIn("空段", str(empty_part.exception))
        with self.assertRaises(SystemExit) as spaced:
            hunt.split_ids("甲 乙,丙")
        self.assertIn("空格", str(spaced.exception))
        with self.assertRaises(SystemExit) as repeated:
            hunt.split_ids("甲,甲")
        self.assertIn("重复", str(repeated.exception))
        with self.assertRaises(SystemExit):
            hunt.require_id("  ")
        with self.assertRaises(SystemExit):
            hunt.require_id("甲 乙")
        with self.assertRaises(SystemExit):
            hunt.require_id("甲,乙")
        self.assertEqual("甲", hunt.require_id(" 甲 "))
        with self.assertRaises(SystemExit) as early:
            hunt.require_year(1799)
        self.assertIn("四位数字", str(early.exception))
        with self.assertRaises(SystemExit):
            hunt.require_year(2101)
        self.assertEqual(1800, hunt.require_year(1800))
        self.assertEqual(2100, hunt.require_year(2100))

    def test_add_paper_rejects_bad_rows_and_keeps_old_ring_short(self) -> None:
        state = base()
        with self.assertRaises(SystemExit) as bad_role:
            hunt.add_paper(state, paper_id="甲", year=2026, title="负荷时移", abstract="负荷，时移。", role="旁观")
        self.assertIn("candidate", str(bad_role.exception))
        hunt.add_paper(state, paper_id="甲", year=2026, title=" 负荷时移 ", abstract=" 负荷，时移。 ", references="乙")
        self.assertEqual("负荷时移", state["papers"][0]["title"])
        self.assertEqual(["乙"], state["papers"][0]["references"])
        with self.assertRaises(SystemExit) as duplicate:
            hunt.add_paper(state, paper_id="甲", year=2026, title="负荷时移", abstract="负荷，时移。")
        self.assertIn("已经在名单里", str(duplicate.exception))
        with self.assertRaises(SystemExit):
            hunt.add_paper(state, paper_id="乙", year=2024, title="", abstract="负荷，时移。")
        with self.assertRaises(SystemExit):
            hunt.add_paper(state, paper_id="乙", year=2024, title="负荷时移", abstract="")
        hunt.add_paper(state, paper_id="旧", year=1800, role="ring")
        self.assertEqual("", hunt.paper_by_id(state, "旧")["title"])
        self.assertIsNone(hunt.paper_by_id(state, "没有"))

    def test_window_and_empty_text(self) -> None:
        state = base()
        self.assertEqual(2024, hunt.recent_cutoff(state))
        self.assertEqual("2024–2026", hunt.window_label(state))
        self.assertTrue(hunt.is_recent(state, {"year": 2024}))
        self.assertFalse(hunt.is_recent(state, {"year": 2023}))
        blank = paper("空", "   ", "  ")
        self.assertEqual(([], []), hunt.slot_hits(state, blank))
        self.assertFalse(hunt.slot_hit(state, blank))
        state["papers"].append(blank)
        result = hunt.present(state)
        self.assertEqual("unclear", result["kind"])
        self.assertEqual(1, result["dropped"])
        folded = base(paper("甲", "ＡＢ 时移", "负荷在摘要里。"))
        folded["object_names"] = ["负 荷"]
        folded["action_names"] = ["ab"]
        self.assertEqual("ab", hunt.normalize("Ａ Ｂ"))
        self.assertTrue(hunt.slot_hit(folded, folded["papers"][0]))
        self.assertIn("负 荷", hunt._near_prompt(folded, folded["papers"][0]))
        self.assertIn("ab", hunt._near_prompt(folded, folded["papers"][0]))

    def test_slot_match_ignores_case_and_lists_every_hit(self) -> None:
        state = base(paper("甲", "Load shift", "data center load can shift."))
        state["object_names"] = ["LOAD", "data center"]
        state["action_names"] = ["Shift"]
        objects, actions = hunt.slot_hits(state, state["papers"][0])
        self.assertEqual(["LOAD", "data center"], objects)
        self.assertEqual(["Shift"], actions)
        self.assertIn("LOAD、data center", hunt._near_prompt(state, state["papers"][0]))


class GraphTests(unittest.TestCase):
    def test_ring_ids_skip_self_and_repeats(self) -> None:
        item = paper("甲", "负荷时移", "负荷，时移。", references=["甲", "乙", "乙"], cited_by=["乙", "丙"])
        self.assertEqual(["乙", "丙"], hunt.ring_ids(item))

    def test_links_ignore_missing_ids_and_one_direction_is_enough(self) -> None:
        state = base(paper("甲", "负荷时移甲", "负荷，时移。", references=["乙", "甲"]))
        links = hunt.neighbor_links(state, ["甲", "乙"])
        self.assertEqual({"乙"}, links["甲"])
        self.assertEqual({"甲"}, links["乙"])
        state["papers"].append(paper("乙", "负荷时移乙", "负荷，时移。", cited_by=["甲"]))
        links = hunt.neighbor_links(state, ["甲", "乙", "缺"])
        self.assertEqual({"乙"}, links["甲"])
        self.assertEqual({"甲"}, links["乙"])
        self.assertEqual(set(), links["缺"])
        self.assertEqual(0, hunt._min_degree({}, set()))

    def test_citation_counts_once_and_self_loops_do_not_count(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。", references=["甲", "乙", "乙"], cited_by=["甲"], year=2026),
            paper("乙", "负荷时移乙", "负荷，时移。", cited_by=["甲"], year=2026),
            paper("丙", "负荷时移丙", "负荷，时移。", cited_by=["甲"], year=2025),
        )
        counts = hunt.in_degrees(state, ["甲", "乙", "丙", "缺"])
        self.assertEqual(1, counts["乙"])
        self.assertEqual(0, counts["甲"])
        self.assertEqual(1, counts["丙"])
        self.assertEqual(0, counts["缺"])
        only_cited = base(
            paper("甲", "负荷时移甲", "负荷，时移。", cited_by=["乙"], year=2024),
            paper("乙", "负荷时移乙", "负荷，时移。", cited_by=["丙"], year=2025),
            paper("丙", "负荷时移丙", "负荷，时移。", cited_by=["甲"], year=2026),
        )
        self.assertEqual(
            {"甲": 1, "乙": 1, "丙": 1},
            hunt.in_degrees(only_cited, ["甲", "乙", "丙"]),
        )

    def test_shortest_path_skips_outside_nodes_and_stops_when_cut(self) -> None:
        links = {
            "甲": {"乙", "外"},
            "乙": {"甲", "丙"},
            "丙": {"乙"},
            "外": {"甲"},
            "孤": set(),
        }
        self.assertEqual(["丙"], hunt.shortest_path(links, "丙", "丙", ["甲", "乙", "丙"]))
        self.assertEqual(["甲", "乙", "丙"], hunt.shortest_path(links, "甲", "丙", ["甲", "乙", "丙"]))
        self.assertEqual(["甲"], hunt.shortest_path(links, "甲", "孤", ["甲", "乙", "丙", "孤"]))

    def test_core_tie_breaks_on_year_then_list_order(self) -> None:
        same_year = base(
            paper("跳", "负荷时移跳", "负荷，时移。", cited_by=["丙", "甲", "乙"], year=2019),
            ring("丙", "负荷时移丙", "负荷，时移。", references=["跳", "甲", "乙"], year=2026),
            ring("甲", "负荷时移甲", "负荷，时移。", references=["跳", "丙", "乙"], year=2026),
            ring("乙", "负荷时移乙", "负荷，时移。", references=["跳", "丙", "甲"], year=2026),
        )
        hunt.decide(same_year, "跳", "是最近的")
        result = hunt.present(same_year)
        self.assertEqual(["丙", "甲", "乙"], result["circle"])
        self.assertEqual("丙", result["core_id"])
        older = base(
            paper("跳", "负荷时移跳", "负荷，时移。", cited_by=["丙", "甲", "乙"], year=2019),
            ring("丙", "负荷时移丙", "负荷，时移。", references=["跳", "甲", "乙"], year=2026),
            ring("甲", "负荷时移甲", "负荷，时移。", references=["跳", "丙", "乙"], year=2026),
            ring("乙", "负荷时移乙", "负荷，时移。", references=["跳", "丙", "甲"], year=2024),
        )
        hunt.decide(older, "跳", "是最近的")
        result = hunt.present(older)
        self.assertEqual("乙", result["core_id"])
        self.assertEqual([], hunt.tight_kernel(base(), [])[0])

    def test_missing_anchor_and_off_path_without_a_paper(self) -> None:
        state = base()
        with self.assertRaises(SystemExit) as caught:
            hunt.after_anchor(state, "没有")
        self.assertIn("不在名单里", str(caught.exception))
        self.assertEqual("", hunt._off_path_block(state, ["甲"], ["甲"]))
        shown = hunt._off_path_block(state, ["甲", "乙"], ["甲"])
        self.assertIn("- 乙 ", shown)
        lines = hunt._four_lines(state, "没有", ["甲"], "甲", 2, 0, 0, 0)
        self.assertIn("对象「」", lines)
        note = hunt._switch_sentence([("甲", "别的原因")])
        self.assertIn("别的原因", note)


class PhraseTests(unittest.TestCase):
    def test_exact_phrases_keep_their_punctuation_rules(self) -> None:
        self.assertEqual("yes", hunt.parse_hotspot("「是最近的」"))
        self.assertEqual("yes", hunt.parse_hotspot("是最近的！"))
        self.assertEqual("no", hunt.parse_topic("「不算这个圈子」"))
        self.assertEqual("已经被攻克", hunt.parse_fate("「已经被攻克」"))
        for words in ("是最近的?", "算这个圈子？", "没有价值吗"):
            with self.assertRaises(SystemExit, msg=words):
                if "圈子" in words:
                    hunt.parse_topic(words)
                elif "价值" in words:
                    hunt.parse_fate(words)
                else:
                    hunt.parse_hotspot(words)
        self.assertFalse(hunt.is_hotspot({}))
        self.assertFalse(hunt.is_hotspot({"hotspot": "no"}))
        self.assertTrue(hunt.is_candidate({"id": "甲"}))
        self.assertEqual({}, hunt.topic_of(base(), "没有"))
        self.assertFalse(hunt.rejected_anywhere(base(), "甲"))

    def test_commands_before_their_turn_are_refused(self) -> None:
        state = triangle()
        with self.assertRaises(SystemExit) as topic_early:
            hunt.mark_topic(state, "前", "算这个圈子")
        self.assertIn("还没到这一步", str(topic_early.exception))
        with self.assertRaises(SystemExit) as fate_early:
            hunt.mark_fate(state, "没有价值")
        self.assertIn("还没到这一步", str(fate_early.exception))
        with self.assertRaises(SystemExit) as core_early:
            hunt.mark_core(state, "是核心", None)
        self.assertIn("还没到这一步", str(core_early.exception))
        with self.assertRaises(SystemExit) as open_early:
            hunt.mark_open(state, "这里有一道缝")
        self.assertIn("还没到这一步", str(open_early.exception))
        hunt.decide(state, "跳", "是最近的")
        with self.assertRaises(SystemExit) as decide_late:
            hunt.decide(state, "前", "是最近的")
        self.assertIn("还没到这一步", str(decide_late.exception))
        with self.assertRaises(SystemExit) as wrong_paper:
            hunt.mark_topic(state, "后", "算这个圈子")
        self.assertIn("前", str(wrong_paper.exception))
        self.assertNotIn("跳", state["topic"])

    def test_core_words_and_short_openings_are_checked(self) -> None:
        state = triangle()
        hunt.decide(state, "跳", "是最近的")
        self.assertEqual("open", walk_to_open(state)["kind"])
        with self.assertRaises(SystemExit):
            hunt.mark_core(state, "是核心吗", None)
        with self.assertRaises(SystemExit) as hedged:
            hunt.mark_core(state, "不是核心", None)
        self.assertIn("是核心", str(hedged.exception))
        with self.assertRaises(SystemExit) as outside:
            hunt.mark_core(state, "", "圈外")
        self.assertIn("最密的这一团", str(outside.exception))
        with self.assertRaises(SystemExit):
            hunt.mark_core(state, "", "丙 丁")
        hunt.mark_core(state, "是核心。", None)
        self.assertEqual("后", state["cores"]["跳"])
        for words in ("好", "好的", "知道了", "缝"):
            with self.assertRaises(SystemExit, msg=words):
                hunt.mark_open(state, words)
        hunt.mark_open(state, "负荷还能再错开一截")
        shown = hunt.render(state, hunt.present(state))
        self.assertIn("摘要里的缝", shown)
        self.assertIn("负荷还能再错开一截", shown)
        self.assertIn("要拿去攻", shown)

    def test_opening_for_another_core_is_ignored(self) -> None:
        state = triangle()
        hunt.decide(state, "跳", "是最近的")
        result = walk_to_open(state)
        self.assertEqual("open", result["kind"])
        state["openings"]["跳"] = {"core_id": "不是这一篇", "text": "旧缝不该算数"}
        result = hunt.present(state)
        self.assertEqual("open", result["kind"])
        self.assertNotIn("旧缝不该算数", result["note"])
        state["cores"]["跳"] = "不在团里"
        result = hunt.present(state)
        self.assertEqual("后", result["core_id"])
        title = hunt.paper_by_id(state, "后")["title"]
        state["papers"] = [item for item in state["papers"] if item["id"] != "后"]
        shown = hunt.render(state, result)
        self.assertIn("汇合点：后", shown)
        self.assertNotIn(title, shown)

    def test_spaced_no_gap_still_switches(self) -> None:
        state = triangle()
        state["papers"].append(paper("下", "负荷时移下", "负荷，时移。"))
        hunt.decide(state, "跳", "是最近的")
        self.assertEqual("open", walk_to_open(state)["kind"])
        hunt.mark_open(state, "「没有 悬而未决」")
        result = hunt.present(state)
        self.assertEqual("下", result["paper"]["id"])
        self.assertIn("看不见缝", result["note"])
        self.assertEqual("nogap", hunt.after_anchor(state, "跳")["switch_reason"])


class AccountingTests(unittest.TestCase):
    def test_not_nearest_does_not_spend_a_switch(self) -> None:
        state = base(
            paper("旁", "负荷时移旁", "负荷，时移。"),
            paper("松", "负荷时移松", "负荷，时移。"),
            paper("下", "负荷时移下", "负荷，时移。"),
        )
        hunt.decide(state, "旁", "不是最近的")
        hunt.decide(state, "松", "是最近的")
        result = hunt.present(state)
        self.assertEqual("下", result["paper"]["id"])
        self.assertIn("第 1 次换近邻", result["note"])
        self.assertNotIn("第 2 次换近邻", result["note"])

    def test_ring_misses_do_not_make_the_names_look_narrow(self) -> None:
        state = base(
            paper("跳", "负荷时移跳", "负荷，时移。", cited_by=["偏甲", "偏乙"], year=2020),
            ring("偏甲", "只谈别的", "摘要里没有这两个词。", references=["跳"], year=2026),
            ring("偏乙", "还是别的", "仍然没有。", references=["跳"], year=2026),
        )
        hunt.decide(state, "跳", "是最近的")
        looked = hunt.after_anchor(state, "跳")
        self.assertEqual(2, looked["dropped"])
        result = hunt.present(state)
        self.assertEqual("fate", result["kind"])
        self.assertNotIn("叫法可能太窄", result["note"])
        self.assertEqual(0, result["dropped"])

    def test_slot_miss_and_old_neighbor_show_up_when_the_circle_holds(self) -> None:
        state = triangle()
        state["papers"][0]["cited_by"] = ["前", "后", "丙", "偏", "旧"]
        state["papers"].append(ring("偏", "只谈负荷", "没有那个动作。", references=["跳"], year=2026))
        state["papers"].append(ring("旧", "负荷时移旧", "负荷，时移。", references=["跳"], year=2018))
        hunt.decide(state, "跳", "是最近的")
        result = hunt.present(state)
        self.assertEqual(["前", "后", "丙"], result["circle"])
        self.assertEqual(1, result["dropped"])
        self.assertEqual(1, result["old"])
        shown = hunt.render(state, result)
        self.assertIn("对不上的已丢掉 1 篇", shown)
        self.assertIn("更早的这轮不看：1 篇", shown)
        self.assertIn("你写：算这个圈子", shown)
        self.assertIn("跳板：跳", shown)
        self.assertIn("近三年是 2024–2026", shown)

    def test_missing_ids_stay_blocking_until_each_one_is_added(self) -> None:
        state = base()
        hunt.add_paper(
            state,
            paper_id="跳",
            year=2020,
            title="负荷时移跳",
            abstract="负荷，时移。",
            references="旧,缺",
        )
        hunt.decide(state, "跳", "是最近的")
        result = hunt.present(state)
        self.assertEqual(["旧", "缺"], result["missing"])
        shown = hunt.render(state, result)
        self.assertIn("add --role ring", shown)
        self.assertIn("- 旧", shown)
        self.assertIn("- 缺", shown)
        self.assertIn("跳板：跳", shown)
        hunt.add_paper(state, paper_id="旧", year=2016, role="ring")
        result = hunt.present(state)
        self.assertEqual(["缺"], result["missing"])
        hunt.add_paper(
            state,
            paper_id="缺",
            year=2026,
            title="负荷时移缺",
            abstract="负荷，时移。",
            references="跳",
            role="ring",
        )
        result = hunt.present(state)
        self.assertEqual("fate", result["kind"])
        self.assertEqual([], result["missing"])
        self.assertEqual(1, hunt.after_anchor(state, "跳")["old"])

    def test_fate_then_a_new_candidate_is_asked_again(self) -> None:
        state = base(paper("甲", "负荷时移甲", "负荷，时移。"))
        hunt.decide(state, "甲", "是最近的")
        self.assertEqual("fate", hunt.present(state)["kind"])
        hunt.mark_fate(state, "已经被攻克")
        closed = hunt.present(state)
        self.assertEqual("closed", closed["kind"])
        shown = hunt.render(state, closed)
        self.assertIn("你的判断：已经被攻克", shown)
        self.assertIn("跳板：甲", shown)
        hunt.add_paper(state, paper_id="乙", year=2026, title="负荷时移乙", abstract="负荷，时移。")
        result = hunt.present(state)
        self.assertEqual("ask", result["kind"])
        self.assertEqual("乙", result["paper"]["id"])
        scan = hunt.render(state, result)
        self.assertIn("你写：是最近的", scan)

    def test_after_the_cap_a_written_fate_stays_closed(self) -> None:
        state = base(*[paper(f"N{i}", f"负荷时移{i}", "负荷，时移。") for i in range(12)])
        for i in range(11):
            current = hunt.present(state)
            hunt.decide(state, current["paper"]["id"], "是最近的")
        stopped = hunt.present(state)
        self.assertEqual("fate", stopped["kind"])
        self.assertIsNone(stopped["paper"])
        hunt.mark_fate(state, "没有价值")
        closed = hunt.present(state)
        self.assertEqual("closed", closed["kind"])
        self.assertIn("没有价值", closed["note"])

    def test_no_gap_with_nobody_left_names_that_gate(self) -> None:
        state = triangle()
        hunt.decide(state, "跳", "是最近的")
        self.assertEqual("open", walk_to_open(state)["kind"])
        hunt.mark_open(state, "没有悬而未决")
        result = hunt.present(state)
        self.assertEqual("fate", result["kind"])
        self.assertIn("走到的汇合点摘要里看不见缝", result["note"])
        self.assertIn("没有下一个近邻了", result["note"])
        shown = hunt.render(state, result)
        self.assertIn("近三年是 2024–2026", shown)
        self.assertIn("这一轮只看近三年的直接邻居", shown)

    def test_only_ring_papers_still_count_as_an_empty_candidate_list(self) -> None:
        state = base(ring("圈", "负荷时移圈", "负荷，时移。"))
        result = hunt.present(state)
        self.assertEqual("empty", result["kind"])
        shown = hunt.render(state, result)
        self.assertIn("--role ring", shown)
        self.assertNotIn("跳板：", shown)
        unclear = hunt.render(state, hunt.present(base(paper("甲", "别的题目", "没有这两个词。"))))
        self.assertIn("看不清", unclear)


class CommandTests(unittest.TestCase):
    def test_help_lists_every_command(self) -> None:
        help_text = hunt.build_parser().format_help()
        for name in ("init", "add-name", "add", "next", "decide", "topic", "fate", "core", "open"):
            self.assertIn(name, help_text)
        failed = cli_fail()
        self.assertEqual(2, failed.code)
        shown = cli_fail("--help")
        self.assertEqual(0, shown.code)

    def test_init_add_name_and_validation_from_the_command_line(self) -> None:
        with TemporaryDirectory() as directory:
            root = str(directory)
            shown = cli("init", "--root", root, "--object", " 负荷 ", "--action", " 时移 ", "--this-year", "2026")
            self.assertIn("对象：负荷", shown)
            self.assertIn("近三年是 2024–2026", shown)
            self.assertIn("换近邻最多 10 次", shown)
            self.assertIn("add-name", shown)
            again = cli_fail("init", "--root", root, "--object", "负荷", "--action", "时移")
            self.assertIn("名单已经有了", str(again))
            empty = cli_fail("init", "--root", root + "/新", "--object", "  ", "--action", "时移")
            self.assertIn("不能是空的", str(empty))
            bad_year = cli_fail(
                "init", "--root", root + "/年", "--object", "负荷", "--action", "时移", "--this-year", "1799"
            )
            self.assertIn("四位数字", str(bad_year))
            named = cli("add-name", "--root", root, "--slot", "object", "--name", "算力负荷")
            self.assertIn("已记下对象叫法：算力负荷", named)
            duplicate = cli_fail("add-name", "--root", root, "--slot", "object", "--name", "算力负荷")
            self.assertIn("已经写过了", str(duplicate))
            blank = cli_fail("add-name", "--root", root, "--slot", "action", "--name", " ")
            self.assertIn("不能是空的", str(blank))
            action = cli("add-name", "--root", root, "--slot", "action", "--name", "削峰")
            self.assertIn("已记下动作叫法：削峰", action)
            no_file = cli_fail("next", "--root", root + "/空")
            self.assertIn("还没有名单", str(no_file))
            for args, snippet in (
                (["--id", "甲 乙", "--year", "2026", "--title", "负荷时移", "--abstract", "负荷，时移。"], "空格"),
                (["--id", "甲", "--year", "2101", "--title", "负荷时移", "--abstract", "负荷，时移。"], "四位数字"),
                (["--id", "甲", "--year", "2026", "--title", "负荷时移"], "题目和摘要"),
                (["--id", "甲", "--year", "2026", "--title", "负荷时移", "--abstract", "负荷，时移。", "--references", "乙,,丙"], "空段"),
                (["--id", "甲", "--year", "2026", "--title", "负荷时移", "--abstract", "负荷，时移。", "--references", "乙 丙"], "空格"),
                (["--id", "甲", "--year", "2026", "--title", "负荷时移", "--abstract", "负荷，时移。", "--cited-by", "乙,乙"], "重复"),
                (["--id", "新", "--year", "2026", "--role", "ring"], "题目和摘要"),
            ):
                failed = cli_fail("add", "--root", root, *args)
                self.assertIn(snippet, str(failed), msg=args)
            bad_role = cli_fail("add", "--root", root, "--id", "甲", "--year", "2026", "--role", "旁观")
            self.assertEqual(2, bad_role.code)
            old = cli("add", "--root", root, "--id", "旧", "--year", "2016", "--role", "ring")
            self.assertIn("已加入圈内邻居 旧", old)
            added = cli(
                "add",
                "--root",
                root,
                "--id",
                "甲",
                "--year",
                "2026",
                "--title",
                "算力负荷可以削峰",
                "--abstract",
                "摘要里写了算力负荷和削峰。",
                "--references",
                "旧",
            )
            self.assertIn("已加入候选近邻 甲", added)
            duplicate_paper = cli_fail(
                "add",
                "--root",
                root,
                "--id",
                "甲",
                "--year",
                "2026",
                "--title",
                "算力负荷可以削峰",
                "--abstract",
                "摘要里写了算力负荷和削峰。",
            )
            self.assertIn("已经在名单里", str(duplicate_paper))
            asked = cli("next", "--root", root)
            self.assertIn("编号：甲", asked)
            self.assertIn("算力负荷", asked)

    def test_command_line_walks_to_the_gap_and_rejects_hedged_words(self) -> None:
        with TemporaryDirectory() as directory:
            root = str(directory)
            cli("init", "--root", root, "--object", "负荷", "--action", "时移", "--this-year", "2026")
            cli(
                "add",
                "--root",
                root,
                "--id",
                "跳",
                "--year",
                "2019",
                "--title",
                "负荷时移跳",
                "--abstract",
                "负荷，时移。",
                "--cited-by",
                "前,后,丙",
            )
            for paper_id, year in (("前", "2025"), ("后", "2024"), ("丙", "2026")):
                others = ",".join(item for item in ("跳", "前", "后", "丙") if item != paper_id)
                cli(
                    "add",
                    "--root",
                    root,
                    "--id",
                    paper_id,
                    "--year",
                    year,
                    "--title",
                    f"负荷时移{paper_id}",
                    "--abstract",
                    "负荷，时移。",
                    "--references",
                    others,
                    "--role",
                    "ring",
                )
            hedged = cli_fail("decide", "--root", root, "--id", "跳", "--words", "不一定是最近的")
            self.assertIn("不一定", str(hedged))
            wrong = cli_fail("decide", "--root", root, "--id", "前", "--words", "是最近的")
            self.assertIn("跳", str(wrong))
            stepped = cli("decide", "--root", root, "--id", "跳", "--words", "是最近的")
            self.assertIn("编号：前", stepped)
            early_fate = cli_fail("fate", "--root", root, "--words", "没有价值")
            self.assertIn("还没到这一步", str(early_fate))
            topic = cli("topic", "--root", root, "--id", "前", "--words", "算这个圈子")
            self.assertIn("编号：后", topic)
            opened = cli("topic", "--root", root, "--id", "后", "--words", "算这个圈子")
            self.assertIn("汇合点：后", opened)
            bad_core = cli_fail("core", "--root", root, "--words", "不是核心")
            self.assertIn("是核心", str(bad_core))
            moved = cli("core", "--root", root, "--id", "丙")
            self.assertIn("编号：丙", moved)
            cli("topic", "--root", root, "--id", "丙", "--words", "算这个圈子")
            short = cli_fail("open", "--root", root, "--text", "好")
            self.assertIn("没有悬而未决", str(short))
            done = cli("open", "--root", root, "--text", "摘要里这道缝还没人补上")
            self.assertIn("摘要里的缝：摘要里这道缝还没人补上", done)
            self.assertIn("全文不进这一轮", done)
            again = cli("next", "--root", root)
            self.assertIn("摘要里的缝", again)

    def test_command_line_fate_closes(self) -> None:
        with TemporaryDirectory() as directory:
            root = str(directory)
            cli("init", "--root", root, "--object", "负荷", "--action", "时移", "--this-year", "2026")
            cli(
                "add",
                "--root",
                root,
                "--id",
                "甲",
                "--year",
                "2026",
                "--title",
                "负荷时移甲",
                "--abstract",
                "负荷，时移。",
            )
            cli("decide", "--root", root, "--id", "甲", "--words", "是最近的")
            hedged = cli_fail("fate", "--root", root, "--words", "可能已经被攻克")
            self.assertIn("已经被攻克", str(hedged))
            closed = cli("fate", "--root", root, "--words", "已经被攻克。")
            self.assertIn("你的判断：已经被攻克", closed)

    def test_script_entry_writes_a_new_list(self) -> None:
        with TemporaryDirectory() as directory:
            argv = sys.argv
            sys.argv = [
                "hunt.py",
                "init",
                "--root",
                directory,
                "--object",
                "负荷",
                "--action",
                "时移",
                "--this-year",
                "2026",
            ]
            try:
                with redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        runpy.run_path(str(ROOT / "scripts" / "hunt.py"), run_name="__main__")
            finally:
                sys.argv = argv
            self.assertEqual(0, caught.exception.code)
            self.assertTrue((Path(directory) / hunt.STATE_NAME).is_file())


if __name__ == "__main__":
    unittest.main()
