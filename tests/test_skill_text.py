"""Guards on the skill's instructions that came out of real triage runs.

Run: python3 -m unittest discover -s tests
"""
import os
import unittest

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(PLUGIN, "skills", "decision-review", "SKILL.md")
TRIAGE = os.path.join(PLUGIN, "skills", "decision-review", "references", "triage.md")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TriageTextTest(unittest.TestCase):
    def setUp(self):
        self.triage = read(TRIAGE)

    def test_calls_asked_before_fyi_bulk_question(self):
        # 2026-11-19 run: opening with "accept 17 FYI items?" read as a rubber stamp.
        calls = self.triage.index("## 1. Needs your call")
        fyi = self.triage.index("## 2. Verified FYI")
        self.assertLess(calls, fyi)
        self.assertIn("one bulk question, last", self.triage)

    def test_tool_tip_before_first_question_including_fyi(self):
        # The tip said "before the first batch", so it could be skipped at the FYI question.
        self.assertNotIn("Before the first batch", self.triage)
        tip = self.triage.index("Before the first question of the triage")
        self.assertLess(tip, self.triage.index("## 1. Needs your call"))
        self.assertIn("or the FYI question when\nthere are no calls", self.triage)

    def test_resume_follows_same_order(self):
        resume = self.triage[self.triage.index("## Resume"):]
        self.assertLess(resume.index("pending calls"), resume.index("step 2"))


class SkillTextTest(unittest.TestCase):
    def setUp(self):
        self.skill = read(SKILL)

    def test_explain_more_is_a_warning_not_a_feature(self):
        # 2026-11-19 run: the run said "I can answer Explain more from my own context".
        self.assertIn("may defend its own\n  choices", self.skill)
        self.assertIn("never a feature", self.skill)

    def test_summary_repeats_split_line_from_citation_check(self):
        self.assertIn("`More than 10 calls — consider splitting this PR.`, repeat that line verbatim",
                      self.skill)


if __name__ == "__main__":
    unittest.main()
