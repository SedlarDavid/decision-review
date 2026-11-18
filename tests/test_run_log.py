"""Tests for run_log.py.

Run: python3 -m unittest discover -s tests
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(PLUGIN, "scripts", "run_log.py")
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))

import run_log  # noqa: E402

TRIAGED = """---
pr: 140                                  # or "branch" when there is no PR
url: https://github.com/owner/repo/pull/140
head: 7d05e18369f7119add78030cd65782aaae26eae4
base: master
slug: someone-stock-fix
evidence:
  plan: missing (no plan named in PR body, session or diff)
  sessions: 3f9a1c2e (+4 subagents)
  review: digest (FINDING #3 from session)
counts: { needs_call: 3, fyi: 2, unverified: 1 }
triaged: 2026-11-18
---

# Decision review — PR #140: fix stock

## Needs your call

### D-01 · Tests · ❓ UNVERIFIED (citation not found)
E2E on iPhone.
**Status:** confirmed

### D-02 · Decision · made by: agent-alone · ✅ verified
Endpoint switch.
**Status:** rejected — keep the old endpoint

### D-03 · Unchanged · Error fallback · ✅ verified · ⚠️ risky fallback kept
**Status:** develop — show retry instead

<details><summary>Verified FYI (2 items)</summary>

### D-04 · Unchanged · Navigation · ✅ verified
**Status:** confirmed

### D-05 · Unchanged · Persistence and migrations · N/A
No storage touched.

</details>

## Follow-ups

- D-02 · rejected — endpoint switch — keep the old endpoint

## Tool notes

<!-- Filled during triage: problems with this ledger itself. -->
- D-02: made-by should be user, I picked option 2 in the session
- ledger too long for a one-line fix
"""


class RunLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ledger = os.path.join(self.tmp, "decisions.md")
        self.log = os.path.join(self.tmp, "nested", "dir", "runs.jsonl")
        self._write(TRIAGED)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _write(self, text):
        with open(self.ledger, "w", encoding="utf-8") as f:
            f.write(text)

    def _run(self, *extra):
        return subprocess.run([sys.executable, SCRIPT, "--ledger", self.ledger, "--log", self.log, *extra],
                              capture_output=True, text=True)

    def _records(self):
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_appends_summary_of_triaged_ledger(self):
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(self.log, proc.stdout)
        [rec] = self._records()
        self.assertEqual(rec["repo"], "owner/repo")
        self.assertEqual(rec["pr"], 140)
        self.assertEqual(rec["head"], "7d05e18369f7119add78030cd65782aaae26eae4")
        self.assertEqual(rec["slug"], "someone-stock-fix")
        self.assertEqual(rec["ledger"], os.path.abspath(self.ledger))
        self.assertEqual(rec["triaged"], "2026-11-18")
        self.assertEqual(rec["evidence"]["sessions"], "3f9a1c2e (+4 subagents)")
        self.assertEqual(rec["evidence"]["review"], "digest (FINDING #3 from session)")
        self.assertEqual(rec["counts"], {"needs_call": 3, "fyi": 2, "unverified": 1})
        self.assertEqual(rec["statuses"], {"confirmed": 2, "rejected": 1, "develop": 1, "pending": 0})
        self.assertEqual(rec["citations_downgraded"], 1)
        self.assertEqual(rec["verdict"], "1 rejected · 1 to develop · 2 confirmed")
        self.assertEqual(rec["tool_notes"], [
            {"item": "D-02", "note": "made-by should be user, I picked option 2 in the session"},
            {"item": None, "note": "ledger too long for a one-line fix"},
        ])

    def test_appends_instead_of_overwriting(self):
        self._run()
        self._run()
        self.assertEqual(len(self._records()), 2)

    def test_follow_ups_are_not_tool_notes(self):
        self._write(TRIAGED.split("## Tool notes")[0])
        self._run()
        self.assertEqual(self._records()[0]["tool_notes"], [])

    def test_branch_mode_takes_repo_argument(self):
        self._write(TRIAGED.replace("pr: 140", "pr: branch").replace(
            "url: https://github.com/owner/repo/pull/140\n", ""))
        self._run("--repo", "my-repo")
        rec = self._records()[0]
        self.assertEqual(rec["pr"], "branch")
        self.assertIsNone(rec["url"])
        self.assertEqual(rec["repo"], "my-repo")

    def test_ledger_without_frontmatter_still_logs(self):
        self._write("# Decision review\n\n### D-01 · Behavior · ✅ verified\n**Status:** pending\n")
        self.assertEqual(self._run().returncode, 0)
        rec = self._records()[0]
        self.assertIsNone(rec["repo"])
        self.assertEqual(rec["evidence"], {})
        self.assertEqual(rec["verdict"], "1 pending")

    def test_missing_ledger_exits_1_without_logging(self):
        os.remove(self.ledger)
        proc = self._run()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("can't read ledger", proc.stderr)
        self.assertFalse(os.path.exists(self.log))

    def test_verdicts(self):
        base = dict.fromkeys(run_log.STATUSES, 0)
        self.assertEqual(run_log.verdict({**base, "confirmed": 5}), "all 5 confirmed")
        self.assertEqual(run_log.verdict({**base, "confirmed": 5, "pending": 2}), "2 pending")


if __name__ == "__main__":
    unittest.main()
