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
) -> dict:
    return {
        "id": paper_id,
        "title": title,
        "abstract": abstract,
        "references": references or [],
        "cited_by": cited_by or [],
    }


def base(*papers: dict) -> dict:
    return {
        "object_names": ["负荷"],
        "action_names": ["时移"],
        "papers": list(papers),
        "decisions": {},
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
            hunt.parse_same("看起来挺像")
        self.assertIn("要你自己写", str(caught.exception))

    def test_question_is_not_a_decision(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            hunt.parse_same("是不是同一个东西")
        self.assertIn("写死", str(caught.exception))
        with self.assertRaises(SystemExit):
            hunt.parse_same("是同一个东西吗")

    def test_negative_is_not_counted_as_yes(self) -> None:
        self.assertEqual("no", hunt.parse_same("不是同一个东西"))
        self.assertEqual("yes", hunt.parse_same("是同一个东西"))

    def test_not_same_drops_the_paper_and_scan_continues(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。"),
            paper("乙", "负荷时移乙", "负荷，时移。"),
        )
        hunt.decide(state, "甲", "不是同一个东西", None)
        result = hunt.present(state)
        self.assertEqual("乙", result["paper"]["id"])
        self.assertIsNone(result["anchor_id"])

    def test_cannot_decide_a_paper_that_is_not_current(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。"),
            paper("乙", "负荷时移乙", "负荷，时移。"),
        )
        with self.assertRaises(SystemExit) as caught:
            hunt.decide(state, "乙", "是同一个东西", "占住")
        self.assertIn("甲", str(caught.exception))
        self.assertNotIn("乙", state["decisions"])


class AnchorTests(unittest.TestCase):
    def test_first_dangerous_paper_stops_the_scan(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。", references=["圈"]),
            paper("乙", "负荷时移乙", "负荷，时移。"),
        )
        hunt.decide(state, "甲", "是同一个东西", "占住")
        result = hunt.present(state)
        self.assertEqual("甲", result["anchor_id"])
        self.assertNotEqual("乙", (result.get("paper") or {}).get("id"))

    def test_similar_title_is_not_an_anchor(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。"),
            paper("乙", "负荷时移乙", "负荷，时移。"),
        )
        hunt.decide(state, "甲", "是同一个东西", "只是像")
        result = hunt.present(state)
        self.assertEqual("乙", result["paper"]["id"])
        self.assertIsNone(result["anchor_id"])

    def test_no_anchor_is_unclear(self) -> None:
        state = base(paper("甲", "负荷时移甲", "负荷，时移。"))
        hunt.decide(state, "甲", "不是同一个东西", None)
        result = hunt.present(state)
        self.assertEqual("unclear", result["kind"])
        self.assertIn("看不清", result["note"])

    def test_not_same_does_not_take_a_danger_word(self) -> None:
        state = base(paper("甲", "负荷时移甲", "负荷，时移。"))
        with self.assertRaises(SystemExit):
            hunt.decide(state, "甲", "不是同一个东西", "占住")


class RingTests(unittest.TestCase):
    def test_ring_uses_references_and_citations_only(self) -> None:
        state = base(
            paper("锚", "负荷时移", "负荷，时移。", references=["前"], cited_by=["后"]),
            paper("前", "负荷时移前作", "负荷，时移。"),
            paper("后", "负荷时移后续", "负荷，时移。"),
            paper("外", "负荷时移圈外", "负荷，时移。"),
        )
        hunt.decide(state, "锚", "是同一个东西", "占住")
        result = hunt.present(state)
        self.assertEqual("前", result["paper"]["id"])
        hunt.decide(state, "前", "是同一个东西", "只是像")
        result = hunt.present(state)
        self.assertEqual("后", result["paper"]["id"])
        hunt.decide(state, "后", "不是同一个东西", None)
        result = hunt.present(state)
        self.assertEqual("done", result["kind"])
        self.assertEqual("锚", result["anchor_id"])
        self.assertIn("判断没变", result["note"])
        self.assertNotIn("外", state["decisions"])

    def test_missing_ring_id_blocks_finishing(self) -> None:
        state = base(paper("锚", "负荷时移", "负荷，时移。", references=["缺"]))
        hunt.decide(state, "锚", "是同一个东西", "能推出来")
        result = hunt.present(state)
        self.assertEqual("missing", result["kind"])
        self.assertEqual(["缺"], result["missing"])

    def test_hotter_paper_redraws_the_ring_once(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。", references=["乙"]),
            paper("乙", "负荷时移乙", "负荷，时移。", references=["丙"]),
            paper("丙", "负荷时移丙", "负荷，时移。", references=["丁"]),
            paper("丁", "负荷时移丁", "负荷，时移。"),
        )
        hunt.decide(state, "甲", "是同一个东西", "能推出来")
        self.assertEqual("乙", hunt.present(state)["paper"]["id"])
        hunt.decide(state, "乙", "是同一个东西", "占住")
        result = hunt.present(state)
        self.assertEqual("丙", result["paper"]["id"])
        self.assertEqual("乙", result["anchor_id"])
        hunt.decide(state, "丙", "是同一个东西", "占住")
        result = hunt.present(state)
        self.assertEqual("done", result["kind"])
        self.assertEqual("乙", result["anchor_id"])
        self.assertNotIn("丁", state["decisions"])

    def test_second_redraw_does_not_open_another_ring(self) -> None:
        state = base(
            paper("甲", "负荷时移甲", "负荷，时移。", references=["乙"]),
            paper("乙", "负荷时移乙", "负荷，时移。", references=["丙"]),
        )
        state["decisions"]["甲"] = {"same": "yes", "danger": "能推出来"}
        state["decisions"]["乙"] = {"same": "yes", "danger": "占住"}
        result = hunt.walk_ring(state, "甲", 1)
        self.assertEqual("done", result["kind"])
        self.assertEqual("乙", result["anchor_id"])
        self.assertIn("不再往外扩", result["note"])
        self.assertNotIn("丙", result["missing"])


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
                    "--same",
                    "是同一个东西",
                    "--danger",
                    "占住",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("锚点：甲", decided.stdout)
            self.assertNotIn("编号：乙", decided.stdout)


if __name__ == "__main__":
    unittest.main()
