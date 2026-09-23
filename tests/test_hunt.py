import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hunt  # noqa: E402


def paper(
    paper_id: str,
    title: str,
    abstract: str,
    references: list[str] | None = None,
    cited_by: list[str] | None = None,
    year: int = 2026,
    role: str = "candidate",
) -> dict:
    return {
        "id": paper_id,
        "year": year,
        "title": title,
        "abstract": abstract,
        "references": references or [],
        "cited_by": cited_by or [],
        "role": role,
    }


def ring(*args, **kwargs) -> dict:
    return paper(*args, role="ring", **kwargs)


def base(*papers: dict) -> dict:
    return {
        "object_names": ["负荷"],
        "action_names": ["时移"],
        "this_year": 2026,
        "papers": list(papers),
        "decisions": {},
        "topic": {},
        "cores": {},
        "openings": {},
        "fate": None,
    }


def walk_to_open(state: dict) -> dict:
    result = hunt.present(state)
    while result["kind"] == "ask" and result["phase"] == "circle":
        hunt.mark_topic(state, result["paper"]["id"], "算这个圈子")
        result = hunt.present(state)
    return result


class SlotTests(unittest.TestCase):
    def test_both_slots_must_hit(self) -> None:
        state = base(
            paper("只对象", "数据中心负荷预测", "只谈了负荷。"),
            paper("只动作", "任务时移", "只谈了时移。"),
            paper("两处", "负荷时移调度", "把负荷做了时移。"),
        )
        result = hunt.present(state)
        self.assertEqual("ask", result["kind"])
        self.assertEqual("两处", result["paper"]["id"])
        self.assertEqual(2, result["dropped"])

    def test_synonym_must_already_be_written(self) -> None:
        state = base(paper("别名", "算力负荷可以时移", "摘要重复算力负荷和时移。"))
        state["object_names"] = ["数据中心负荷"]
        self.assertEqual("unclear", hunt.present(state)["kind"])
        state["object_names"].append("算力负荷")
        result = hunt.present(state)
        self.assertEqual("别名", result["paper"]["id"])

    def test_whole_sentence_is_not_required(self) -> None:
        state = base(paper("拆开", "关于负荷", "后文才写时移，两词不连在一起。"))
        self.assertEqual("拆开", hunt.present(state)["paper"]["id"])


class IdentityTests(unittest.TestCase):
    def test_reader_must_write_same_or_not(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            hunt.parse_hotspot("看起来挺像")
        self.assertIn("要你自己写", str(caught.exception))

    def test_question_is_not_a_decision(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            hunt.parse_hotspot("是不是最近的")
        self.assertIn("写死", str(caught.exception))
        with self.assertRaises(SystemExit):
            hunt.parse_hotspot("是最近的吗")

    def test_negative_is_not_counted_as_yes(self) -> None:
        self.assertEqual("no", hunt.parse_hotspot("不是最近的"))
        self.assertEqual("yes", hunt.parse_hotspot("是最近的"))
        self.assertEqual("yes", hunt.parse_hotspot(" 是最近的。"))

    def test_hedged_words_must_be_rewritten(self) -> None:
        for words in ("不一定是最近的", "未必是最近的", "我觉得是最近的", "是最近的，但不确定"):
            with self.assertRaises(SystemExit, msg=words):
                hunt.parse_hotspot(words)
        for words in ("不太算这个圈子", "未必算这个圈子", "应该算这个圈子"):
            with self.assertRaises(SystemExit, msg=words):
                hunt.parse_topic(words)
        self.assertEqual("no", hunt.parse_topic("不算这个圈子"))
        self.assertEqual("yes", hunt.parse_topic("算这个圈子。"))
        for words in ("不是没有价值", "可能已经被攻克", "没有价值，已经被攻克"):
            with self.assertRaises(SystemExit, msg=words):
                hunt.parse_fate(words)
        self.assertEqual("没有价值", hunt.parse_fate("没有价值。"))

    def test_not_same_drops_the_paper_and_scan_continues(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。"),
            paper("乙", "负荷时移乙", "负荷，时移。"),
        )
        hunt.decide(state, "甲", "不是最近的")
        result = hunt.present(state)
        self.assertEqual("乙", result["paper"]["id"])
        self.assertIsNone(result["anchor_id"])

    def test_cannot_decide_a_paper_that_is_not_current(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。"),
            paper("乙", "负荷时移乙", "负荷，时移。"),
        )
        with self.assertRaises(SystemExit) as caught:
            hunt.decide(state, "乙", "是最近的")
        self.assertIn("甲", str(caught.exception))
        self.assertNotIn("乙", state["decisions"])


class AnchorTests(unittest.TestCase):
    def test_first_dangerous_paper_stops_the_scan(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。", references=["圈"]),
            paper("乙", "负荷时移乙", "负荷，时移。"),
        )
        hunt.decide(state, "甲", "是最近的")
        result = hunt.present(state)
        self.assertEqual("甲", result["anchor_id"])
        self.assertNotEqual("乙", (result.get("paper") or {}).get("id"))

    def test_similar_title_is_not_an_anchor(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。"),
            paper("乙", "负荷时移乙", "负荷，时移。"),
        )
        hunt.decide(state, "甲", "不是最近的")
        result = hunt.present(state)
        self.assertEqual("乙", result["paper"]["id"])
        self.assertIsNone(result["anchor_id"])

    def test_no_anchor_is_unclear(self) -> None:
        state = base(paper("甲", "负荷时移甲", "负荷，时移。"))
        hunt.decide(state, "甲", "不是最近的")
        result = hunt.present(state)
        self.assertEqual("unclear", result["kind"])
        self.assertIn("看不清", result["note"])

    def test_not_same_does_not_take_a_danger_word(self) -> None:
        state = base(paper("甲", "负荷时移甲", "负荷，时移。"))
        with self.assertRaises(SystemExit):
            hunt.decide(state, "甲", "是不是最近的")


class CircleTests(unittest.TestCase):
    def test_circle_keeps_only_direct_recent_papers(self) -> None:
        state = base(
            paper("跳", "负荷时移", "负荷，时移。", references=["旧"], cited_by=["前", "后", "丙", "孤"], year=2019),
            ring("前", "负荷时移前作", "负荷，时移。", references=["跳", "后", "丙"], year=2025),
            ring("后", "负荷时移后续", "负荷，时移。", references=["跳", "前", "丙"], year=2024),
            ring("丙", "负荷时移三角", "负荷，时移。", references=["跳", "前", "后"], year=2026),
            ring("孤", "负荷时移孤单", "负荷，时移。", references=["跳"], year=2026),
            ring("旧", "负荷时移旧作", "负荷，时移。", year=2018),
            paper("外", "负荷时移圈外", "负荷，时移。", year=2026),
        )
        hunt.decide(state, "跳", "是最近的")
        self.assertEqual("前", hunt.present(state)["paper"]["id"])
        hunt.mark_topic(state, "前", "算这个圈子")
        result = hunt.present(state)
        self.assertEqual("后", result["paper"]["id"])
        self.assertEqual(["前", "后", "丙"], result["circle"])
        self.assertNotIn("跳", result["circle"])
        self.assertNotIn("孤", result["circle"])
        hunt.mark_topic(state, "后", "算这个圈子")
        result = hunt.present(state)
        self.assertEqual("open", result["kind"])
        self.assertEqual("后", result["core_id"])
        shown = hunt.render(state, result)
        self.assertIn("负荷时移后续", shown)
        self.assertIn("摘要里看见的缝", shown)
        self.assertIn("全文不进这一轮", shown)
        self.assertNotIn("读这一篇的全文", shown)
        judged = state["topic"]["跳"]
        self.assertNotIn("外", judged)
        self.assertNotIn("丙", judged)
        self.assertNotIn("孤", judged)
        self.assertGreaterEqual(result["old"], 1)

    def test_old_neighbor_without_recent_topic_asks_for_fate(self) -> None:
        state = base(
            paper("锚", "负荷时移", "负荷，时移。", references=["旧"], year=2019),
            ring("旧", "负荷时移旧作", "负荷，时移。", year=2015),
        )
        hunt.decide(state, "锚", "是最近的")
        result = hunt.present(state)
        self.assertEqual("fate", result["kind"])
        self.assertIn("内核不紧密", result["note"])
        self.assertIsNone(result["paper"])
        self.assertIn("没有价值", result["note"])
        self.assertIn("已经被攻克", result["note"])
        hunt.mark_fate(state, "已经被攻克")
        result = hunt.present(state)
        self.assertEqual("closed", result["kind"])
        self.assertIn("已经被攻克", result["note"])

    def test_recent_followup_of_an_old_anchor_is_the_circle(self) -> None:
        state = base(
            paper("锚", "负荷时移", "负荷，时移。", cited_by=["新"], year=2019),
            ring("新", "负荷时移新作", "负荷，时移。", references=["锚"], year=2025),
        )
        hunt.decide(state, "锚", "是最近的")
        result = hunt.present(state)
        self.assertEqual("fate", result["kind"])
        self.assertIn("内核不紧密", result["note"])
        self.assertIn("没有下一个近邻了", result["note"])

    def test_missing_direct_id_blocks_the_circle(self) -> None:
        state = base(paper("锚", "负荷时移", "负荷，时移。", references=["缺"], year=2026))
        hunt.decide(state, "锚", "是最近的")
        result = hunt.present(state)
        self.assertEqual("missing", result["kind"])
        self.assertEqual(["缺"], result["missing"])

    def test_reader_can_move_the_core_inside_the_circle(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。", cited_by=["乙", "丙", "丁"], year=2020),
            ring("乙", "负荷时移乙", "负荷，时移。", references=["甲", "丙", "丁"], year=2024),
            ring("丙", "负荷时移丙", "负荷，时移。", references=["甲", "乙", "丁"], year=2025),
            ring("丁", "负荷时移丁", "负荷，时移。", references=["甲", "乙", "丙"], year=2026),
        )
        hunt.decide(state, "甲", "是最近的")
        self.assertEqual("乙", hunt.present(state)["paper"]["id"])
        hunt.mark_topic(state, "乙", "算这个圈子")
        result = hunt.present(state)
        self.assertEqual("open", result["kind"])
        self.assertEqual(["乙", "丙", "丁"], result["circle"])
        self.assertNotIn("甲", result["circle"])
        self.assertEqual("乙", result["core_id"])
        hunt.mark_core(state, "", "丙")
        result = hunt.present(state)
        self.assertEqual("丙", result["paper"]["id"])
        hunt.mark_topic(state, "丙", "算这个圈子")
        result = hunt.present(state)
        self.assertEqual("open", result["kind"])
        self.assertEqual("丙", result["core_id"])
        with self.assertRaises(SystemExit):
            hunt.mark_open(state, "继续")

    def test_four_checks_are_measured_on_the_triangle(self) -> None:
        state = base(
            paper("跳", "负荷时移", "负荷，时移。", cited_by=["前", "后", "丙", "孤"], year=2019),
            ring("前", "负荷时移前作", "负荷，时移。", references=["跳", "后", "丙"], year=2025),
            ring("后", "负荷时移后续", "负荷，时移。", references=["跳", "前", "丙"], year=2024),
            ring("丙", "负荷时移三角", "负荷，时移。", references=["跳", "前", "后"], year=2026),
            ring("孤", "负荷时移孤单", "负荷，时移。", references=["跳"], year=2026),
        )
        hunt.decide(state, "跳", "是最近的")
        result = hunt.present(state)
        self.assertEqual(["前", "后"], result["path"])
        self.assertEqual(2, result["tightness"])
        self.assertEqual(2, result["core_links"])
        self.assertEqual(1, result["hops"])
        self.assertEqual(2, result["step_bound"])
        self.assertLessEqual(result["hops"], result["step_bound"])
        self.assertIn("方向碰上了", result["note"])
        self.assertIn("直接连着这篇近邻", result["note"])
        self.assertIn("不是历史上的源头", result["note"])
        self.assertIn("没写上的边不算", result["note"])
        self.assertIn("至少连着 2 篇", result["note"])
        self.assertIn("汇合点是「后」", result["note"])
        self.assertIn("最多 2 步", result["note"])
        self.assertIn("不往外扩", result["note"])
        self.assertIn("- 丙 负荷时移三角", result["note"])
        self.assertNotEqual("丙", result["paper"]["id"])
        self.assertNotIn("孤", result["circle"])

    def test_tighter_component_beats_the_earlier_triangle(self) -> None:
        state = base(
            paper("跳", "负荷时移", "负荷，时移。", cited_by=["前", "后", "丙", "甲", "乙", "丁", "戊"], year=2019),
            ring("前", "负荷时移前", "负荷，时移。", references=["跳", "后", "丙"], year=2026),
            ring("后", "负荷时移后", "负荷，时移。", references=["跳", "前", "丙"], year=2026),
            ring("丙", "负荷时移丙", "负荷，时移。", references=["跳", "前", "后"], year=2026),
            ring("甲", "负荷时移甲", "负荷，时移。", references=["跳", "乙", "丁", "戊"], year=2024),
            ring("乙", "负荷时移乙", "负荷，时移。", references=["跳", "甲", "丁", "戊"], year=2025),
            ring("丁", "负荷时移丁", "负荷，时移。", references=["跳", "甲", "乙", "戊"], year=2026),
            ring("戊", "负荷时移戊", "负荷，时移。", references=["跳", "甲", "乙", "丁"], year=2026),
        )
        hunt.decide(state, "跳", "是最近的")
        result = hunt.present(state)
        self.assertEqual(["甲", "乙", "丁", "戊"], result["circle"])
        self.assertEqual("甲", result["paper"]["id"])
        self.assertEqual("甲", result["core_id"])
        self.assertEqual(3, result["tightness"])
        self.assertEqual(0, result["hops"])
        self.assertEqual(3, result["step_bound"])
        self.assertLessEqual(result["hops"], result["step_bound"])
        self.assertIn("- 乙 负荷时移乙", result["note"])
        self.assertIn("- 丁 负荷时移丁", result["note"])
        self.assertIn("- 戊 负荷时移戊", result["note"])
        self.assertNotIn("前", result["circle"])

    def test_nearness_names_the_hits_before_the_reader_decides(self) -> None:
        state = base(paper("甲", "负荷时移甲", "只在摘要里写了负荷和时移。"))
        note = hunt.present(state)["note"]
        self.assertIn("对象「负荷」", note)
        self.assertIn("动作「时移」", note)
        self.assertIn("近不近要你写死", note)

    def test_loose_shapes_have_no_kernel(self) -> None:
        chain = base(
            paper("链头", "负荷时移链头", "负荷，时移。", references=["链中"], year=2024),
            paper("链中", "负荷时移链中", "负荷，时移。", references=["链尾"], year=2025),
            paper("链尾", "负荷时移链尾", "负荷，时移。", year=2026),
        )
        self.assertEqual([], hunt.tight_members(chain, ["链头", "链中", "链尾"]))
        pair = base(
            paper("甲", "负荷时移甲", "负荷，时移。", references=["乙"], year=2024),
            paper("乙", "负荷时移乙", "负荷，时移。", references=["甲"], year=2025),
        )
        self.assertEqual([], hunt.tight_members(pair, ["甲", "乙"]))
        star = base(
            paper("中", "负荷时移中", "负荷，时移。", cited_by=["旁甲", "旁乙"], year=2024),
            paper("旁甲", "负荷时移旁甲", "负荷，时移。", references=["中"], year=2025),
            paper("旁乙", "负荷时移旁乙", "负荷，时移。", references=["中"], year=2026),
        )
        self.assertEqual([], hunt.tight_members(star, ["中", "旁甲", "旁乙"]))

    def test_loose_neighbor_switches_until_a_tight_kernel_converges(self) -> None:
        state = base(
            paper("松", "负荷时移松", "负荷，时移。", cited_by=["孤"], year=2020),
            paper("好", "负荷时移好", "负荷，时移。", cited_by=["前", "后", "丙"], year=2021),
            ring("孤", "负荷时移孤", "负荷，时移。", references=["松"], year=2026),
            ring("前", "负荷时移前", "负荷，时移。", references=["好", "后", "丙"], year=2025),
            ring("后", "负荷时移后", "负荷，时移。", references=["好", "前", "丙"], year=2024),
            ring("丙", "负荷时移丙", "负荷，时移。", references=["好", "前", "后"], year=2026),
        )
        hunt.decide(state, "松", "是最近的")
        result = hunt.present(state)
        self.assertEqual("好", result["paper"]["id"])
        self.assertEqual("scan", result["phase"])
        self.assertIn("内核不紧密", result["note"])
        self.assertIn("换近邻", result["note"])
        self.assertNotEqual("fate", result["kind"])
        hunt.decide(state, "好", "是最近的")
        result = hunt.present(state)
        self.assertEqual("前", result["paper"]["id"])
        self.assertEqual(["前", "后", "丙"], result["circle"])
        self.assertEqual("好", result["anchor_id"])

    def test_walk_that_falls_apart_switches_neighbor(self) -> None:
        state = base(
            paper("跳", "负荷时移跳", "负荷，时移。", cited_by=["前", "后", "丙"], year=2019),
            paper("下", "负荷时移下", "负荷，时移。", year=2026),
            ring("前", "负荷时移前", "负荷，时移。", references=["跳", "后", "丙"], year=2025),
            ring("后", "负荷时移后", "负荷，时移。", references=["跳", "前", "丙"], year=2024),
            ring("丙", "负荷时移丙", "负荷，时移。", references=["跳", "前", "后"], year=2026),
        )
        hunt.decide(state, "跳", "是最近的")
        hunt.mark_topic(state, "前", "不算这个圈子")
        result = hunt.present(state)
        self.assertEqual("下", result["paper"]["id"])
        self.assertIn("不收敛", result["note"])
        self.assertIn("换近邻", result["note"])

    def test_broken_group_does_not_jump_to_another_group(self) -> None:
        state = base(
            paper("跳", "负荷时移跳", "负荷，时移。", cited_by=["a", "b", "c", "x", "y", "z"], year=2019),
            ring("a", "负荷时移a", "负荷，时移。", references=["跳", "b", "c"], year=2026),
            ring("b", "负荷时移b", "负荷，时移。", references=["跳", "a", "c"], year=2026),
            ring("c", "负荷时移c", "负荷，时移。", references=["跳", "a", "b"], year=2026),
            ring("x", "负荷时移x", "负荷，时移。", references=["跳", "y", "z"], year=2026),
            ring("y", "负荷时移y", "负荷，时移。", references=["跳", "x", "z"], year=2026),
            ring("z", "负荷时移z", "负荷，时移。", references=["跳", "x", "y"], year=2026),
        )
        hunt.decide(state, "跳", "是最近的")
        result = hunt.present(state)
        self.assertEqual(["a", "b", "c"], result["circle"])
        hunt.mark_topic(state, result["paper"]["id"], "不算这个圈子")
        result = hunt.present(state)
        self.assertEqual("fate", result["kind"])
        self.assertIn("不收敛", result["note"])
        self.assertNotIn("x", result["circle"])
        self.assertIsNone(result["paper"])

    def test_shrunk_group_says_it_is_still_the_same_group(self) -> None:
        state = base(
            paper("跳", "负荷时移跳", "负荷，时移。", cited_by=["甲", "乙", "丙", "丁"], year=2019),
            ring("甲", "负荷时移甲", "负荷，时移。", references=["跳", "乙", "丙", "丁"], year=2024),
            ring("乙", "负荷时移乙", "负荷，时移。", references=["跳", "甲", "丙", "丁"], year=2025),
            ring("丙", "负荷时移丙", "负荷，时移。", references=["跳", "甲", "乙", "丁"], year=2026),
            ring("丁", "负荷时移丁", "负荷，时移。", references=["跳", "甲", "乙", "丙"], year=2026),
        )
        hunt.decide(state, "跳", "是最近的")
        self.assertEqual("甲", hunt.present(state)["paper"]["id"])
        hunt.mark_topic(state, "甲", "不算这个圈子")
        result = hunt.present(state)
        self.assertEqual(["乙", "丙", "丁"], result["circle"])
        self.assertIn("剩下的仍在原来这一团里", result["note"])

    def test_judgments_do_not_carry_to_another_anchor(self) -> None:
        state = base(
            paper("A", "负荷时移A", "负荷，时移。", cited_by=["a", "b", "c", "d"], year=2020),
            paper("B", "负荷时移B", "负荷，时移。", cited_by=["a", "b", "c"], year=2020),
            ring("a", "负荷时移a", "负荷，时移。", references=["A", "B", "b", "c"], year=2026),
            ring("b", "负荷时移b", "负荷，时移。", references=["A", "B", "a", "c"], year=2026),
            ring("c", "负荷时移c", "负荷，时移。", references=["A", "B", "a", "b"], year=2026),
            ring("d", "负荷时移d", "负荷，时移。", references=["A"], year=2026),
        )
        hunt.decide(state, "A", "是最近的")
        self.assertEqual("a", hunt.present(state)["paper"]["id"])
        hunt.mark_topic(state, "a", "不算这个圈子")
        result = hunt.present(state)
        self.assertEqual("B", result["paper"]["id"])
        hunt.decide(state, "B", "是最近的")
        result = hunt.present(state)
        self.assertEqual("B", result["anchor_id"])
        self.assertEqual(["a", "b", "c"], result["circle"])
        self.assertEqual("a", result["paper"]["id"])

    def test_written_gap_belongs_to_its_anchor(self) -> None:
        state = base(
            paper("A", "负荷时移A", "负荷，时移。", cited_by=["q"], year=2020),
            paper("B", "负荷时移B", "负荷，时移。", cited_by=["a", "b", "c"], year=2020),
            ring("a", "负荷时移a", "负荷，时移。", references=["B", "b", "c"], year=2026),
            ring("b", "负荷时移b", "负荷，时移。", references=["B", "a", "c"], year=2026),
            ring("c", "负荷时移c", "负荷，时移。", references=["B", "a", "b"], year=2026),
            ring("q", "负荷时移q", "负荷，时移。", references=["A"], year=2026),
        )
        hunt.decide(state, "A", "是最近的")
        hunt.decide(state, "B", "是最近的")
        self.assertEqual("open", walk_to_open(state)["kind"])
        hunt.mark_open(state, "B 圈的缝在这里")
        self.assertEqual("done", hunt.present(state)["kind"])
        hunt.add_paper(state, paper_id="r", year=2026, title="负荷时移r", abstract="负荷，时移。",
                       references="A,q", role="ring")
        hunt.add_paper(state, paper_id="t", year=2026, title="负荷时移t", abstract="负荷，时移。",
                       references="A,q,r", role="ring")
        state["papers"][0]["cited_by"] += ["r", "t"]
        paper_by_id = {item["id"]: item for item in state["papers"]}
        paper_by_id["q"]["references"] = ["A", "r", "t"]
        result = walk_to_open(state)
        self.assertEqual("A", result["anchor_id"])
        self.assertEqual("open", result["kind"])

    def test_no_gap_switches_neighbor(self) -> None:
        state = base(
            paper("跳", "负荷时移跳", "负荷，时移。", cited_by=["前", "后", "丙"], year=2019),
            paper("下", "负荷时移下", "负荷，时移。", year=2026),
            ring("前", "负荷时移前", "负荷，时移。", references=["跳", "后", "丙"], year=2025),
            ring("后", "负荷时移后", "负荷，时移。", references=["跳", "前", "丙"], year=2024),
            ring("丙", "负荷时移丙", "负荷，时移。", references=["跳", "前", "后"], year=2026),
        )
        hunt.decide(state, "跳", "是最近的")
        self.assertEqual("open", walk_to_open(state)["kind"])
        hunt.mark_open(state, "没有悬而未决。")
        result = hunt.present(state)
        self.assertEqual("下", result["paper"]["id"])
        self.assertIn("看不见缝", result["note"])
        self.assertIn("换近邻", result["note"])

    def test_ring_papers_are_not_candidates_and_old_ones_need_only_a_year(self) -> None:
        state = base()
        hunt.add_paper(state, paper_id="跳", year=2020, title="负荷时移跳", abstract="负荷，时移。",
                       references="旧", cited_by="新")
        hunt.add_paper(state, paper_id="旧", year=2015, role="ring")
        with self.assertRaises(SystemExit):
            hunt.add_paper(state, paper_id="新", year=2026, role="ring")
        with self.assertRaises(SystemExit):
            hunt.add_paper(state, paper_id="候", year=2015)
        hunt.add_paper(state, paper_id="新", year=2026, title="负荷时移新", abstract="负荷，时移。",
                       references="跳", role="ring")
        hunt.decide(state, "跳", "是最近的")
        result = hunt.present(state)
        self.assertEqual("fate", result["kind"])
        self.assertEqual(1, hunt.after_anchor(state, "跳")["old"])
        self.assertNotIn("叫法可能太窄", result["note"])

    def test_old_state_file_is_refused(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / hunt.STATE_NAME).write_text(
                '{"papers": [], "topic": {"甲": "no"}, "core_id": null, "open_problem": null}',
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as caught:
                hunt.load_state(root)
            self.assertIn("旧格式", str(caught.exception))

    def test_rejected_circle_paper_is_not_the_next_neighbor(self) -> None:
        state = base(
            paper("跳", "负荷时移跳", "负荷，时移。", cited_by=["前", "后", "丙"], year=2019),
            paper("前", "负荷时移前", "负荷，时移。", references=["跳", "后", "丙"], year=2025),
            paper("下", "负荷时移下", "负荷，时移。", year=2026),
            ring("后", "负荷时移后", "负荷，时移。", references=["跳", "前", "丙"], year=2024),
            ring("丙", "负荷时移丙", "负荷，时移。", references=["跳", "前", "后"], year=2026),
        )
        hunt.decide(state, "跳", "是最近的")
        hunt.mark_topic(state, "前", "不算这个圈子")
        result = hunt.present(state)
        self.assertEqual("下", result["paper"]["id"])
        self.assertEqual("scan", result["phase"])
        self.assertNotEqual("前", result["paper"]["id"])

    def test_narrow_names_are_named_before_fate(self) -> None:
        state = base(
            paper("偏甲", "只谈负荷", "摘要里没有那个动作。"),
            paper("偏乙", "还是负荷", "仍然没有那个动作。"),
            paper("甲", "负荷时移甲", "负荷，时移。", year=2026),
        )
        hunt.decide(state, "甲", "是最近的")
        result = hunt.present(state)
        self.assertEqual("fate", result["kind"])
        self.assertIn("叫法可能太窄", result["note"])
        self.assertIn("这张名单里没有紧密圈子", result["note"])
        self.assertIn("没有价值", result["note"])
        self.assertIn("对主题下的判断", result["note"])

    def test_every_neighbor_fails_then_reader_writes_fate(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。", year=2026),
            paper("乙", "负荷时移乙", "负荷，时移。", year=2025),
        )
        hunt.decide(state, "甲", "是最近的")
        self.assertEqual("乙", hunt.present(state)["paper"]["id"])
        hunt.decide(state, "乙", "是最近的")
        result = hunt.present(state)
        self.assertEqual("fate", result["kind"])
        self.assertIn("没有下一个近邻了", result["note"])
        hunt.mark_fate(state, "没有价值")
        self.assertEqual("closed", hunt.present(state)["kind"])

    def test_switch_stops_after_ten(self) -> None:
        state = base(
            *[
                paper(f"N{i}", f"负荷时移{i}", "负荷，时移。")
                for i in range(12)
            ]
        )
        for i in range(11):
            current = hunt.present(state)
            self.assertEqual("ask", current["kind"])
            self.assertEqual(f"N{i}", current["paper"]["id"])
            if i:
                self.assertIn(f"第 {i} 次换近邻", current["note"])
                self.assertIn("最多 10 次", current["note"])
            hunt.decide(state, f"N{i}", "是最近的")
        stopped = hunt.present(state)
        self.assertEqual("fate", stopped["kind"])
        self.assertIn("到上限了", stopped["note"])
        self.assertIn("已经换了 10 次近邻", stopped["note"])
        self.assertIsNone(stopped["paper"])


class CommandTests(unittest.TestCase):
    def test_cli_stops_at_the_first_anchor(self) -> None:
        hunt_py = ROOT / "scripts" / "hunt.py"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(
                [sys.executable, str(hunt_py), "init", "--root", str(root), "--object", "负荷", "--action", "时移"],
                check=True,
                capture_output=True,
                text=True,
            )
            for paper_id, title in (("甲", "负荷时移甲"), ("乙", "负荷时移乙")):
                subprocess.run(
                    [
                        sys.executable,
                        str(hunt_py),
                        "add",
                        "--root",
                        str(root),
                        "--id",
                        paper_id,
                        "--year",
                        "2026",
                        "--title",
                        title,
                        "--abstract",
                        "做了负荷的时移。",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            shown = subprocess.run(
                [sys.executable, str(hunt_py), "next", "--root", str(root)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("编号：甲", shown.stdout)
            self.assertNotIn("编号：乙", shown.stdout)
            decided = subprocess.run(
                [
                    sys.executable,
                    str(hunt_py),
                    "decide",
                    "--root",
                    str(root),
                    "--id",
                    "甲",
                    "--words",
                    "是最近的",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("内核不紧密", decided.stdout)
            self.assertIn("换近邻", decided.stdout)
            self.assertIn("编号：乙", decided.stdout)
            self.assertNotIn("没有下一个近邻了", decided.stdout)


if __name__ == "__main__":
    unittest.main()
