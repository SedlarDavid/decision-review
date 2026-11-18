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


if __name__ == "__main__":
    unittest.main()
