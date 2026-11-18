"""Tests for find_sessions.py.

Run: python3 -m unittest discover -s tests
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(PLUGIN, "scripts", "find_sessions.py")
FIXTURES = os.path.join(PLUGIN, "tests", "fixtures", "projects")
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))

import find_sessions  # noqa: E402

S140 = os.path.join("-Users-x-shop-wt", "11111111-aaaa-4aaa-8aaa-000000000140.jsonl")
S140_SUB = os.path.join("-Users-x-shop-wt", "11111111-aaaa-4aaa-8aaa-000000000140", "subagents",
                        "agent-a1b2c3d4e5f6.jsonl")
S14 = os.path.join("-Users-x-shop", "22222222-bbbb-4bbb-8bbb-000000000014.jsonl")
MULTI = os.path.join("-Users-x-multi", "44444444-dddd-4ddd-8ddd-000000000200.jsonl")
ORPHAN = os.path.join("-Users-x-orphan", "55555555-eeee-4eee-8eee-000000000000.jsonl")


class FindSessionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "projects")
        shutil.copytree(FIXTURES, self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def rel(self, paths):
        return [os.path.relpath(p, self.root) for p in paths]

    def test_exact_pr_url_match_with_subagents(self):
        paths, how = find_sessions.find("acme/shop", 140, projects_dir=self.root)
        self.assertEqual(how, "pr-link")
        # Deduped (pr-link repeats 3x), subagent included, meta.json skipped,
        # pull/14 and the spoofed pr-link (prNumber 999) excluded.
        self.assertEqual(self.rel(paths), [S140, S140_SUB])

    def test_pull_14_does_not_match_pull_140(self):
        paths, how = find_sessions.find("acme/shop", 14, projects_dir=self.root)
        self.assertEqual((self.rel(paths), how), ([S14], "pr-link"))

    def test_repo_is_case_insensitive_and_must_match(self):
        paths, _ = find_sessions.find("ACME/Shop", 140, projects_dir=self.root)
        self.assertEqual(self.rel(paths)[0], S140)
        paths, how = find_sessions.find("other/shop", 140, projects_dir=self.root)
        self.assertEqual((paths, how), ([], "none"))

    def test_json_confirmation_rejects_grep_only_match(self):
        # The spoof file contains the exact prUrl but its record says prNumber 999.
        self.assertNotIn("-Users-x-other", " ".join(
            find_sessions.by_pr("acme/shop", 140, self.root)))

    def test_multi_pr_session_found_for_each_pr(self):
        for pr in (200, 201):
            paths, how = find_sessions.find("acme/multi", pr, projects_dir=self.root)
            self.assertEqual((self.rel(paths), how), ([MULTI], "pr-link"))

    def test_branch_fallback(self):
        paths, how = find_sessions.find("acme/shop", 777, "feat/orphan", projects_dir=self.root)
        self.assertEqual((self.rel(paths), how), ([ORPHAN], "branch"))

    def test_branch_fallback_scoped_to_repo_roots(self):
        import json
        for project, cwd, sid in (("-Users-x-shopx", "/Users/x/shop/wt-login", "aaaa0001"),
                                  ("-Users-x-blog", "/Users/x/blog", "bbbb0002")):
            os.makedirs(os.path.join(self.root, project))
            with open(os.path.join(self.root, project, sid + ".jsonl"), "w") as f:
                f.write(json.dumps({"type": "user", "gitBranch": "fix/login", "cwd": cwd,
                                    "message": {"content": "hi"}}, separators=(",", ":")))
        paths, _ = find_sessions.find(None, None, "fix/login", projects_dir=self.root)
        self.assertEqual(len(paths), 2)  # unscoped: both repos match
        paths, how = find_sessions.find(None, None, "fix/login", projects_dir=self.root,
                                        repo_roots=["/Users/x/shop", "/Users/x/shop/wt-login"])
        self.assertEqual((self.rel(paths), how), ([os.path.join("-Users-x-shopx", "aaaa0001.jsonl")], "branch"))
        paths, _ = find_sessions.find(None, None, "fix/login", projects_dir=self.root,
                                      repo_roots=["/Users/x/sho"])  # prefix of a name is not inside
        self.assertEqual(paths, [])

    def test_exclude_session_drops_it_and_its_subagents(self):
        paths, how = find_sessions.find("acme/shop", 777, "feat/orphan", projects_dir=self.root,
                                        exclude="55555555-eeee-4eee-8eee-000000000000")
        self.assertEqual((paths, how), ([], "none"))
        paths, _ = find_sessions.find("acme/shop", 140, projects_dir=self.root,
                                      exclude="11111111-aaaa-4aaa-8aaa-000000000140")
        self.assertNotIn(S140_SUB, self.rel(paths))
        self.assertNotIn(S140, self.rel(paths))

    def test_branch_fallback_skips_default_branches(self):
        paths, how = find_sessions.find("acme/shop", 777, "main", projects_dir=self.root)
        self.assertEqual((paths, how), ([], "none"))

    def test_pr_match_wins_over_branch(self):
        paths, how = find_sessions.find("acme/shop", 140, "feat/orphan", projects_dir=self.root)
        self.assertEqual((self.rel(paths)[0], how), (S140, "pr-link"))

    def test_newest_session_first(self):
        old, new = os.path.join(self.root, S14), os.path.join(self.root, ORPHAN)
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))
        self.assertEqual(self.rel(find_sessions.expand({old, new})), [ORPHAN, S14])

    def test_needle_split_across_chunks(self):
        path = os.path.join(self.root, "-p", "s.jsonl")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            f.write("x" * 5 + '/pull/7"')
        original = find_sessions.CHUNK
        try:
            for size in range(2, 12):
                find_sessions.CHUNK = size
                self.assertIn(path, find_sessions._files_containing('/pull/7"', self.root), size)
        finally:
            find_sessions.CHUNK = original

    def test_missing_projects_dir(self):
        self.assertEqual(find_sessions.find("a/b", 1, projects_dir=os.path.join(self.tmp, "nope")),
                         ([], "none"))

    def test_cli_prints_paths_and_note(self):
        proc = subprocess.run([sys.executable, SCRIPT, "--repo", "acme/shop", "--pr", "140",
                               "--projects-dir", self.root], capture_output=True, text=True, check=True)
        self.assertEqual(self.rel(proc.stdout.split()), [S140, S140_SUB])
        self.assertIn("matched by pr-link", proc.stderr)
        self.assertIn("1 session(s), 2 file(s)", proc.stderr)


if __name__ == "__main__":
    unittest.main()
