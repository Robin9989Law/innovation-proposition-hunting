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
            hunt.parse_hotspot("是不是当前热点")
        self.assertIn("写死", str(caught.exception))
        with self.assertRaises(SystemExit):
            hunt.parse_hotspot("是当前热点吗")

    def test_negative_is_not_counted_as_yes(self) -> None:
        self.assertEqual("no", hunt.parse_hotspot("不是当前热点"))
        self.assertEqual("yes", hunt.parse_hotspot("是当前热点"))

    def test_not_same_drops_the_paper_and_scan_continues(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。"),
            paper("乙", "负荷时移乙", "负荷，时移。"),
        )
        hunt.decide(state, "甲", "不是当前热点")
        result = hunt.present(state)
        self.assertEqual("乙", result["paper"]["id"])
        self.assertIsNone(result["anchor_id"])

    def test_cannot_decide_a_paper_that_is_not_current(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。"),
            paper("乙", "负荷时移乙", "负荷，时移。"),
        )
        with self.assertRaises(SystemExit) as caught:
            hunt.decide(state, "乙", "是当前热点")
        self.assertIn("甲", str(caught.exception))
        self.assertNotIn("乙", state["decisions"])


class AnchorTests(unittest.TestCase):
    def test_first_dangerous_paper_stops_the_scan(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。", references=["圈"]),
            paper("乙", "负荷时移乙", "负荷，时移。"),
        )
        hunt.decide(state, "甲", "是当前热点")
        result = hunt.present(state)
        self.assertEqual("甲", result["anchor_id"])
        self.assertNotEqual("乙", (result.get("paper") or {}).get("id"))

    def test_similar_title_is_not_an_anchor(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。"),
            paper("乙", "负荷时移乙", "负荷，时移。"),
        )
        hunt.decide(state, "甲", "不是当前热点")
        result = hunt.present(state)
        self.assertEqual("乙", result["paper"]["id"])
        self.assertIsNone(result["anchor_id"])

    def test_no_anchor_is_unclear(self) -> None:
        state = base(paper("甲", "负荷时移甲", "负荷，时移。"))
        hunt.decide(state, "甲", "不是当前热点")
        result = hunt.present(state)
        self.assertEqual("unclear", result["kind"])
        self.assertIn("看不清", result["note"])

    def test_not_same_does_not_take_a_danger_word(self) -> None:
        state = base(paper("甲", "负荷时移甲", "负荷，时移。"))
        with self.assertRaises(SystemExit):
            hunt.decide(state, "甲", "是不是当前热点")


class CircleTests(unittest.TestCase):
    def test_circle_keeps_only_direct_recent_papers(self) -> None:
        state = base(
            paper("锚", "负荷时移", "负荷，时移。", references=["旧"], cited_by=["前", "后"], year=2026),
            paper("前", "负荷时移前作", "负荷，时移。", references=["锚", "丙"], year=2025),
            paper("后", "负荷时移后续", "负荷，时移。", year=2024),
            paper("旧", "负荷时移旧作", "负荷，时移。", year=2018),
            paper("外", "负荷时移圈外", "负荷，时移。", year=2026),
            paper("丙", "负荷时移再远", "负荷，时移。", year=2026),
        )
        hunt.decide(state, "锚", "是当前热点")
        self.assertEqual("前", hunt.present(state)["paper"]["id"])
        hunt.mark_topic(state, "前", "算这个主题")
        self.assertEqual("后", hunt.present(state)["paper"]["id"])
        hunt.mark_topic(state, "后", "不算这个主题")
        result = hunt.present(state)
        self.assertEqual("core", result["kind"])
        self.assertEqual(["锚", "前"], result["circle"])
        self.assertEqual("锚", result["core_id"])
        self.assertNotIn("外", state["topic"])
        self.assertNotIn("丙", state["topic"])
        self.assertNotIn("旧", state["topic"])
        self.assertGreaterEqual(result["old"], 1)

    def test_old_neighbor_without_recent_topic_asks_for_fate(self) -> None:
        state = base(
            paper("锚", "负荷时移", "负荷，时移。", references=["旧"], year=2019),
            paper("旧", "负荷时移旧作", "负荷，时移。", year=2015),
        )
        hunt.decide(state, "锚", "是当前热点")
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
        hunt.decide(state, "锚", "是当前热点")
        self.assertEqual("新", hunt.present(state)["paper"]["id"])
        hunt.mark_topic(state, "新", "算这个主题")
        result = hunt.present(state)
        self.assertEqual("open", result["kind"])
        self.assertEqual(["新"], result["circle"])
        self.assertEqual("新", result["core_id"])
        hunt.mark_open(state, "边界情形下负荷能不能时移，还没写。")
        result = hunt.present(state)
        self.assertEqual("done", result["kind"])
        self.assertIn("边界情形", result["note"])

    def test_missing_direct_id_blocks_the_circle(self) -> None:
        state = base(paper("锚", "负荷时移", "负荷，时移。", references=["缺"], year=2026))
        hunt.decide(state, "锚", "是当前热点")
        result = hunt.present(state)
        self.assertEqual("missing", result["kind"])
        self.assertEqual(["缺"], result["missing"])

    def test_reader_can_move_the_core_inside_the_circle(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。", cited_by=["乙", "丙"], year=2024),
            paper("乙", "负荷时移乙", "负荷，时移。", references=["甲"], year=2025),
            paper("丙", "负荷时移丙", "负荷，时移。", references=["甲"], year=2026),
        )
        hunt.decide(state, "甲", "是当前热点")
        hunt.mark_topic(state, "乙", "算这个主题")
        hunt.mark_topic(state, "丙", "算这个主题")
        result = hunt.present(state)
        self.assertEqual("甲", result["core_id"])
        hunt.mark_core(state, "", "丙")
        result = hunt.present(state)
        self.assertEqual("open", result["kind"])
        self.assertEqual("丙", result["core_id"])
        with self.assertRaises(SystemExit):
            hunt.mark_open(state, "继续")


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
                    "是当前热点",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("热点入口：甲", decided.stdout)
            self.assertIn("悬而未决", decided.stdout)
            self.assertNotIn("编号：乙", decided.stdout)


if __name__ == "__main__":
    unittest.main()
