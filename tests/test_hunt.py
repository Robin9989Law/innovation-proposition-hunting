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
) -> dict:
    return {
        "id": paper_id,
        "year": year,
        "title": title,
        "abstract": abstract,
        "references": references or [],
        "cited_by": cited_by or [],
    }


def base(*papers: dict) -> dict:
    return {
        "object_names": ["负荷"],
        "action_names": ["时移"],
        "this_year": 2026,
        "papers": list(papers),
        "decisions": {},
        "topic": {},
        "fate": None,
        "core_id": None,
        "open_problem": None,
    }


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
            paper("前", "负荷时移前作", "负荷，时移。", references=["跳", "后", "丙"], year=2025),
            paper("后", "负荷时移后续", "负荷，时移。", references=["跳", "前", "丙"], year=2024),
            paper("丙", "负荷时移三角", "负荷，时移。", references=["跳", "前", "后"], year=2026),
            paper("孤", "负荷时移孤单", "负荷，时移。", references=["跳"], year=2026),
            paper("旧", "负荷时移旧作", "负荷，时移。", year=2018),
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
        self.assertIn("不必读全文", shown)
        self.assertNotIn("读这一篇的全文", shown)
        self.assertNotIn("外", state["topic"])
        self.assertNotIn("丙", state["topic"])
        self.assertNotIn("孤", state["topic"])
        self.assertGreaterEqual(result["old"], 1)

    def test_old_neighbor_without_recent_topic_asks_for_fate(self) -> None:
        state = base(
            paper("锚", "负荷时移", "负荷，时移。", references=["旧"], year=2019),
            paper("旧", "负荷时移旧作", "负荷，时移。", year=2015),
        )
        hunt.decide(state, "锚", "是最近的")
        result = hunt.present(state)
        self.assertEqual("旧", result["paper"]["id"])
        self.assertIn("内核不紧密", result["note"])
        self.assertIn("换近邻", result["note"])
        hunt.decide(state, "旧", "是最近的")
        result = hunt.present(state)
        self.assertEqual("fate", result["kind"])
        self.assertIn("没有价值", result["note"])
        self.assertIn("已经被攻克", result["note"])
        hunt.mark_fate(state, "已经被攻克")
        result = hunt.present(state)
        self.assertEqual("closed", result["kind"])
        self.assertIn("已经被攻克", result["note"])

    def test_recent_followup_of_an_old_anchor_is_the_circle(self) -> None:
        state = base(
            paper("锚", "负荷时移", "负荷，时移。", cited_by=["新"], year=2019),
            paper("新", "负荷时移新作", "负荷，时移。", references=["锚"], year=2025),
        )
        hunt.decide(state, "锚", "是最近的")
        result = hunt.present(state)
        self.assertEqual("新", result["paper"]["id"])
        self.assertIn("内核不紧密", result["note"])
        self.assertIn("换近邻", result["note"])
        hunt.decide(state, "新", "是最近的")
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
            paper("乙", "负荷时移乙", "负荷，时移。", references=["甲", "丙", "丁"], year=2024),
            paper("丙", "负荷时移丙", "负荷，时移。", references=["甲", "乙", "丁"], year=2025),
            paper("丁", "负荷时移丁", "负荷，时移。", references=["甲", "乙", "丙"], year=2026),
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
            paper("孤", "负荷时移孤", "负荷，时移。", references=["松"], year=2026),
            paper("前", "负荷时移前", "负荷，时移。", references=["好", "后", "丙"], year=2025),
            paper("后", "负荷时移后", "负荷，时移。", references=["好", "前", "丙"], year=2024),
            paper("丙", "负荷时移丙", "负荷，时移。", references=["好", "前", "后"], year=2026),
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
            paper("前", "负荷时移前", "负荷，时移。", references=["跳", "后", "丙"], year=2025),
            paper("后", "负荷时移后", "负荷，时移。", references=["跳", "前", "丙"], year=2024),
            paper("丙", "负荷时移丙", "负荷，时移。", references=["跳", "前", "后"], year=2026),
        )
        hunt.decide(state, "跳", "是最近的")
        hunt.mark_topic(state, "前", "不算这个圈子")
        result = hunt.present(state)
        self.assertEqual("下", result["paper"]["id"])
        self.assertIn("不收敛", result["note"])
        self.assertIn("换近邻", result["note"])

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
