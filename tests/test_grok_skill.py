import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".grok" / "skills" / "proposition-hunt" / "SKILL.md"
GUIDE = ROOT / "grok-bot" / "装到一个bot.md"


class GrokSkillTests(unittest.TestCase):
    def test_grok_discovers_one_named_skill(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        front, body = text.split("---", 2)[1:]
        self.assertIn("name: proposition-hunt", front)
        self.assertIn("user-invocable: true", front)
        self.assertIn("命题狩猎", front)
        self.assertIn("scripts/hunt.py", body)
        self.assertIn("cursor/fast-neighbor-8b2e", body)
        self.assertIn("不要用 `main`", body)
        for phrase in ("是最近的", "算这个圈子", "是核心", "没有价值", "已经被攻克", "没有悬而未决"):
            self.assertIn(phrase, body)
        self.assertIn("不要自己把圈子算出来", body)

    def test_one_bot_guide_points_at_that_skill(self) -> None:
        guide = GUIDE.read_text(encoding="utf-8")
        self.assertIn("命题狩猎", guide)
        self.assertIn(".grok/skills/proposition-hunt/SKILL.md", guide)
        self.assertIn("只给这个 bot", guide)
        self.assertIn("cursor/fast-neighbor-8b2e", guide)
        self.assertIn("不要用 main", guide)


if __name__ == "__main__":
    unittest.main()
