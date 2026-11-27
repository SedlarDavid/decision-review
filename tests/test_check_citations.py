"""Tests for check_citations.py.

Run: python3 -m unittest discover -s tests
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(PLUGIN, "scripts", "check_citations.py")
FIXTURES = os.path.join(PLUGIN, "tests", "fixtures", "citations")
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))

import check_citations as cc  # noqa: E402


def item(text, item_id):
    m = re.search(r"^### %s\b.*?(?=^### |^</details>|\Z)" % item_id, text, re.S | re.M)
    return m.group(0)


class CheckCitationsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "repo")
        shutil.copytree(os.path.join(FIXTURES, "repo"), self.root)
        self.ledger = os.path.join(self.tmp, "decisions.md")
        shutil.copy(os.path.join(FIXTURES, "ledger.md"), self.ledger)
        self.proc = subprocess.run([sys.executable, SCRIPT, "--ledger", self.ledger, "--root", self.root],
                                   capture_output=True, text=True)
        with open(self.ledger, encoding="utf-8") as f:
            self.text = f.read()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_exit_zero_and_summary(self):
        self.assertEqual(self.proc.returncode, 0)
        self.assertIn("checked 8 citation(s): 4 ok, 4 failed → downgraded D-03, D-04, D-06, D-07",
                      self.proc.stdout)

    def test_exact_match_passes(self):
        self.assertIn("### D-01 · Decision · made by: agent-alone · ✅ verified", self.text)
        self.assertNotIn("(not found)", item(self.text, "D-01"))

    def test_within_three_lines_passes(self):
        # Cited line 8, snippet on line 11.
        self.assertIn("### D-02 · Unchanged · Caching · ✅ verified", self.text)

    def test_multiline_elided_snippet_passes(self):
        self.assertIn("### D-05 · Tests · ✅ verified", self.text)

    def test_fyi_item_inside_details_passes(self):
        self.assertIn("### D-08 · Unchanged · Navigation · ✅ verified", self.text)

    def test_snippet_miss_downgrades(self):
        self.assertIn("### D-03 · Behavior · ❓ UNVERIFIED (citation not found)", self.text)
        self.assertIn('"_fromCache(id)" (not found)', self.text)
        self.assertIn("D-03 lib/api.dart:11: snippet not within ±3 lines", self.proc.stdout)

    def test_beyond_three_lines_downgrades(self):
        self.assertIn("### D-06 · Scope · ❓ UNVERIFIED (citation not found)", self.text)

    def test_missing_file_downgrades_heading_without_marker(self):
        self.assertIn("### D-04 · Decision · made by: plan · ❓ UNVERIFIED (citation not found)", self.text)
        self.assertIn("D-04 lib/gone.dart:3: file not found", self.proc.stdout)

    def test_path_outside_checkout_downgrades(self):
        self.assertIn("### D-07 · Decision · ❓ UNVERIFIED (citation not found)", self.text)
        self.assertIn("path outside checkout", self.proc.stdout)

    def test_status_lines_untouched(self):
        self.assertEqual(self.text.count("**Status:** pending"), 8)

    def test_idempotent(self):
        again, _ = cc.process(self.text, self.root)
        self.assertEqual(again, self.text)

    def test_tolerance_boundary(self):
        lines = ["l%d" % i for i in range(1, 21)]
        path = os.path.join(self.root, "b.txt")
        with open(path, "w") as f:
            f.write("\n".join(lines))
        self.assertIsNone(cc.check(self.root, "b.txt", 10, "l13"))
        self.assertIsNone(cc.check(self.root, "b.txt", 10, "l7"))
        self.assertIsNotNone(cc.check(self.root, "b.txt", 10, "l14"))
        self.assertIsNotNone(cc.check(self.root, "b.txt", 10, "l6"))
        self.assertIn("out of range", cc.check(self.root, "b.txt", 99, "l1"))

    def test_near_miss_formats_on_evidence_lines_downgrade(self):
        for evidence in ("`lib/api.dart:6`", "`lib/api.dart:5-8`", "`lib/api.dart:6` 'single quoted'"):
            text, results = cc.process("### D-01 · Decision · ✅ verified\nEvidence: %s\n" % evidence, self.root)
            self.assertEqual([r[2] for r in results], ["no checkable snippet"], evidence)
            self.assertIn(cc.UNVERIFIED, text.splitlines()[0])

    def test_backticked_path_line_in_prose_not_flagged(self):
        _, results = cc.process("### D-01 · x · ✅ verified\nPR says iOS `APIRouter.swift:91` used it.\n"
                                "Evidence: PR body\n", self.root)
        self.assertEqual(results, [])

    def test_already_unverified_heading_keeps_one_marker(self):
        text, _ = cc.process("### D-01 · Tests · ❓ UNVERIFIED (no transcript)\n"
                             "Evidence: `lib/gone.dart:1` \"x\"\n", self.root)
        self.assertEqual(text.splitlines()[0].count("UNVERIFIED"), 1)

    def test_session_and_pr_body_citations_ignored(self):
        _, results = cc.process("### D-01 · x · ✅ verified\nEvidence: session ab12cd34:L5 · PR body\n",
                                self.root)
        self.assertEqual(results, [])

    def test_fixture_with_eight_calls_has_no_split_line(self):
        self.assertNotIn("consider splitting", self.proc.stdout)
        self.assertNotIn("consider splitting", self.text)


def ledger_with_calls(calls, fyi=3, note=""):
    items = "\n".join("### D-%02d · Behavior · ✅ verified\nx\n**Status:** pending\n" % i
                      for i in range(1, calls + 1))
    fyis = "\n".join("### D-%02d · Unchanged · N/A\nx\n" % i
                     for i in range(calls + 1, calls + fyi + 1))
    return ("---\npr: 1\n---\n\n## Needs your call\n%s\n%s\n"
            "<details><summary>Verified FYI</summary>\n\n%s\n</details>\n\n## Follow-ups\n"
            % (note, items, fyis))


class SplitNoteTest(unittest.TestCase):
    """Regression: a 16-call ledger (16 calls, 2026-11-19) must say "consider splitting"."""

    def test_eleven_calls_adds_note_under_heading(self):
        text, calls = cc.split_note(ledger_with_calls(11))
        self.assertEqual(calls, 11)
        lines = text.splitlines()
        heading = lines.index("## Needs your call")
        self.assertEqual(lines[heading + 2], "> " + cc.SPLIT_LINE)
        self.assertEqual(text.count("consider splitting"), 1)

    def test_ten_calls_no_note_and_fyi_not_counted(self):
        text, calls = cc.split_note(ledger_with_calls(10, fyi=5))
        self.assertEqual(calls, 10)
        self.assertNotIn("consider splitting", text)

    def test_existing_note_not_duplicated_and_idempotent(self):
        original = ledger_with_calls(16, note="> More than 10 calls — consider splitting this PR.\n")
        text, calls = cc.split_note(original)
        self.assertEqual(calls, 16)
        self.assertEqual(text, original)
        again, _ = cc.split_note(cc.split_note(ledger_with_calls(16))[0])
        self.assertEqual(again.count("consider splitting"), 1)

    def test_no_calls_heading(self):
        self.assertEqual(cc.split_note("## Intent\nx\n"), ("## Intent\nx\n", 0))

    def test_cli_prints_split_line(self):
        tmp = tempfile.mkdtemp()
        try:
            ledger = os.path.join(tmp, "decisions.md")
            with open(ledger, "w", encoding="utf-8") as f:
                f.write(ledger_with_calls(16))
            proc = subprocess.run([sys.executable, SCRIPT, "--ledger", ledger, "--root", tmp],
                                  capture_output=True, text=True)
            self.assertIn(cc.SPLIT_LINE, proc.stdout)
            with open(ledger, encoding="utf-8") as f:
                self.assertIn("> " + cc.SPLIT_LINE, f.read())
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
