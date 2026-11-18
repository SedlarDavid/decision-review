"""Tests for session_digest.py.

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
SCRIPT = os.path.join(PLUGIN, "scripts", "session_digest.py")
PROJECTS = os.path.join(PLUGIN, "tests", "fixtures", "projects")
MAIN = os.path.join(PROJECTS, "-Users-x-shop-wt", "11111111-aaaa-4aaa-8aaa-000000000140.jsonl")
SUB = os.path.join(PROJECTS, "-Users-x-shop-wt", "11111111-aaaa-4aaa-8aaa-000000000140", "subagents",
                   "agent-a1b2c3d4e5f6.jsonl")
MULTI = os.path.join(PROJECTS, "-Users-x-multi", "44444444-dddd-4ddd-8ddd-000000000200.jsonl")

# Token-shaped test values are assembled at runtime so no file in the repo holds one whole:
# the MAIN fixture carries placeholders that with_secrets() fills in.
GH_TOKEN = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123"
SK_KEY = "sk-" + "ant-api03-abcdefghijklmnopqrstuv"
PEM_BEGIN = "-----BEGIN RSA " + "PRIVATE KEY-----"
PEM_END = "-----END RSA " + "PRIVATE KEY-----"
PLACEHOLDERS = {"__GH_TOKEN__": GH_TOKEN, "__SK_KEY__": SK_KEY,
                "__PEM_BEGIN__": PEM_BEGIN, "__PEM_END__": PEM_END}
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))

import session_digest as sd  # noqa: E402


class ExtractionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = sd.build([MAIN, SUB], "feat/stock")

    def test_citation_labels(self):
        self.assertIn("## session 11111111\n", self.out)
        self.assertIn("## session 11111111/a1b2c3d4\n", self.out)

    def test_user_prompt_kept_and_meta_skipped(self):
        self.assertIn("PROMPT: backend says stock is always Sold out", self.out)
        self.assertNotIn("Base directory for this skill", self.out)
        self.assertNotIn("task-notification", self.out)

    def test_slash_and_skill_invocations(self):
        self.assertIn("SKILL: /vgv-wingspan:review", self.out)
        self.assertIn("SKILL: vgv-wingspan:build docs/plan/x.md", self.out)

    def test_ask_user_question_paired_with_answer_and_note(self):
        self.assertRegex(self.out, r'L\d+ ASK: Q: "FINDING-02: when the stock check fails, '
                                   r'what should Aktivovat do\?" → A: "Enable, let BE decide '
                                   r'\(Recommended\)" \(note: "also report to Sentry"\)')

    def test_ask_answer_falls_back_to_result_text(self):
        q = "Pick one?"
        recs = [
            {"type": "assistant", "gitBranch": "b", "message": {"content": [
                {"type": "tool_use", "id": "q1", "name": "AskUserQuestion",
                 "input": {"questions": [{"question": q}]}}]}},
            {"type": "user", "gitBranch": "b", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "q1",
                 "content": 'Your questions have been answered: "%s"="Option B". You can now continue.' % q}]}},
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(json.dumps(r) for r in recs))
        try:
            self.assertIn('Q: "Pick one?" → A: "Option B"', sd.build([f.name], "b"))
        finally:
            os.unlink(f.name)

    def test_finding_lines_kept(self):
        self.assertIn("FINDING: - FINDING-01: no control test for the stock gate", self.out)
        self.assertIn("FINDING: - FINDING-02: a failed stock fetch shows Sold out", self.out)
        self.assertNotIn("Other text", self.out)

    def test_bash_filter_and_exit_status(self):
        self.assertIn("BASH [exit 1]: `fvm flutter test test/api_test.dart`", self.out)
        self.assertIn("BASH [exit 0]: `fvm flutter test && fvm flutter analyze`", self.out)
        self.assertIn("BASH [exit 0]: `gh pr create --title 'fix stock'`", self.out)
        self.assertIn("BASH [exit 0]: `git diff origin/master...HEAD`", self.out)
        self.assertNotIn("`ls lib`", self.out)

    def test_read_only_commands_skipped(self):
        for cmd in ("grep -rn foo lib test", "sed -n 1,5p test/a_test.dart", "cd /r && cat test/x"):
            self.assertIsNotNone(sd.BASH_SKIP.match(cmd), cmd)
        for cmd in ("fvm flutter test", "cd /r && fvm flutter analyze", "git log -S x", "curl -s https://x"):
            self.assertIsNone(sd.BASH_SKIP.match(cmd), cmd)

    def test_mcp_runs_collapsed(self):
        self.assertIn("MCP: mcp__mobile-mcp__mobile_take_screenshot ×2", self.out)
        self.assertIn("MCP: mcp__mobile-mcp__mobile_click_on_screen_at_coordinates", self.out)

    def test_edited_paths_deduped(self):
        self.assertEqual(self.out.count("EDIT: /repo/lib/api.dart"), 1)
        self.assertIn("EDIT: /repo/test/api_test.dart", self.out)


class BranchWindowTest(unittest.TestCase):
    def test_two_pr_session_windowed_by_branch(self):
        one = sd.build([MULTI], "feat/one")
        two = sd.build([MULTI], "feat/two")
        self.assertIn("FINDING-07", one)
        self.assertNotIn("FINDING-09", one)
        self.assertIn("npm test", one)
        self.assertIn("FINDING-09", two)
        self.assertNotIn("FINDING-07", two)
        self.assertIn("BASH [exit 2]: `pytest -q`", two)

    def test_transcripts_without_entries_listed_in_header_only(self):
        out = sd.build([MAIN, SUB], "feat/other")
        self.assertIn("no matching entries: 11111111, 11111111/a1b2c3d4", out)
        self.assertNotIn("## session", out)

    def test_no_branch_reads_everything(self):
        out = sd.build([MULTI])
        self.assertIn("FINDING-07", out)
        self.assertIn("FINDING-09", out)


def with_secrets(tmp):
    """Copy of MAIN with the placeholders replaced by token-shaped values."""
    with open(MAIN, encoding="utf-8") as f:
        text = f.read()
    for placeholder, value in PLACEHOLDERS.items():
        text = text.replace(placeholder, value)
    path = os.path.join(tmp, os.path.basename(MAIN))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class RedactionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        try:
            path = with_secrets(tmp)
            with open(path, encoding="utf-8") as f:
                assert GH_TOKEN in f.read()
            cls.out = sd.build([path], "feat/stock")
        finally:
            shutil.rmtree(tmp)

    def test_github_token(self):
        self.assertNotIn(GH_TOKEN, self.out)
        self.assertEqual(sd.redact("x gho_" + "ABCDEFGHIJKLMNOPQRSTUV y"), "x gh*_[REDACTED] y")

    def test_sk_key(self):
        self.assertNotIn(SK_KEY, self.out)
        self.assertEqual(sd.redact("sk-" + "proj-0123456789abcdefXYZ"), "sk-[REDACTED]")

    def test_bearer(self):
        self.assertNotIn("abcdef1234567890XYZ", self.out)
        self.assertIn("Bearer [REDACTED]", self.out)

    def test_key_value_secrets(self):
        self.assertNotIn("hunter2secret", self.out)
        self.assertNotIn("zzz999", self.out)
        self.assertIn("STORE_PASSWORD=[REDACTED]", self.out)
        self.assertEqual(sd.redact('"api_key": "zzz999"'), '"api_key": "[REDACTED]"')
        self.assertEqual(sd.redact("secret: s3cr3t"), "secret: [REDACTED]")
        self.assertEqual(sd.redact("GH_TOKEN=abc123"), "GH_TOKEN=[REDACTED]")

    def test_pem_block(self):
        self.assertNotIn("MIIEowIBAAKCAQEA", self.out)
        self.assertIn("[REDACTED PEM] done", self.out)
        # A PEM cut off before its END line is still redacted.
        self.assertEqual(sd.redact("k -----BEGIN " + "PRIVATE KEY-----\nMIIabc"), "k [REDACTED PEM]")

    def test_more_token_shapes(self):
        cases = {
            "github_pat_" + "11ABCDEFG0123456789_abcdefghijKLMNOP": "github_pat_[REDACTED]",
            "aws AKIA" + "ABCDEFGHIJKLMNOP key": "aws AKIA[REDACTED] key",
            "xoxb-" + "1234567890-abcdefghij": "xox-[REDACTED]",
            "keytool --password hunter2 -v": "keytool --password [REDACTED] -v",
            "cli --token=abc123def": "cli --token=[REDACTED]",
            'storePassword "s3cret pass"': 'storePassword "[REDACTED]"',
        }
        for raw, expected in cases.items():
            self.assertEqual(sd.redact(raw), expected, raw)

    def test_prose_about_secrets_untouched(self):
        for prose in ("the token expired yesterday", "reset your password via email",
                      "secret sauce is the cache"):
            self.assertEqual(sd.redact(prose), prose)

    def test_redaction_happens_before_truncation(self):
        long_prompt = "x" * 190 + " password=supersecretvalue123"
        entry = sd.Entry("prompt", 1, sd.redact(long_prompt))
        self.assertNotIn("supersecret", entry.render(200))


def _write_jsonl(directory, name, records):
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write("\n".join(json.dumps(r, ensure_ascii=False) for r in records))
    return path


class RobustnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_secret_straddling_line_cut_is_redacted(self):
        token = "ghp_" + "A1b2C3d4E5" * 4
        text = "FINDING-07: " + "x" * (sd.LINE_CHARS - 25) + " " + token
        path = _write_jsonl(self.tmp, "s.jsonl", [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}])
        out = sd.build([path])
        self.assertIn("FINDING-07", out)
        self.assertNotIn("ghp_A1b2", out)

    def test_ask_list_answer_joined_and_clipped(self):
        path = _write_jsonl(self.tmp, "a.jsonl", [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "q", "name": "AskUserQuestion",
                 "input": {"questions": [{"question": "Which?"}]}}]}},
            {"type": "user", "toolUseResult": {"answers": {"Which?": ["A", "B\n" + "z" * 900]}},
             "message": {"content": [{"type": "tool_result", "tool_use_id": "q", "content": "x"}]}},
        ])
        ask = [l for l in sd.build([path]).splitlines() if " ASK: " in l][0]
        self.assertIn('A: "A, B zzz', ask)
        self.assertLess(len(ask), 2 * sd.LINE_CHARS)

    def test_null_or_odd_message_content_does_not_crash(self):
        path = _write_jsonl(self.tmp, "n.jsonl", [
            {"type": "user", "message": {"content": None}},
            {"type": "user", "message": "not a dict"},
            {"type": "assistant", "message": {"content": None}},
            {"type": "user", "message": {"content": "still here"}},
        ])
        self.assertIn("PROMPT: still here", sd.build([path]))


class CapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "noisy.jsonl")
        recs = []

        def add(r):
            r["gitBranch"] = "b"
            recs.append(r)

        add({"type": "user", "message": {"content": "první prompt " + "č" * 600}})
        for i in range(60):
            add({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "b%d" % i, "name": "Bash",
                 "input": {"command": "flutter test test/file_%03d_test.dart %s" % (i, "-v " * 40)}}]}})
            add({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "e%d" % i, "name": "Edit",
                 "input": {"file_path": "/repo/lib/feature/very/long/path/file_%03d.dart" % i}}]}})
        add({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "q", "name": "AskUserQuestion",
             "input": {"questions": [{"question": "Keep fallback?"}]}}]}})
        add({"type": "user", "toolUseResult": {"answers": {"Keep fallback?": "No"}},
             "message": {"content": [{"type": "tool_result", "tool_use_id": "q", "content": "x"}]}})
        add({"type": "assistant", "message": {"content": [{"type": "text", "text": "FINDING-01: keep me"}]}})
        with open(self.path, "w") as f:
            f.write("\n".join(json.dumps(r, ensure_ascii=False) for r in recs))
        self.full = sd.build([self.path], "b", max_bytes=10 ** 9)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def size(self, text):
        return len(text.encode("utf-8"))

    def test_under_cap_untouched(self):
        self.assertNotIn("trimmed:", self.full)
        self.assertEqual(self.full.count("BASH"), 60)

    def test_drops_bash_oldest_first(self):
        cap = self.size(self.full) - 2000
        out = sd.build([self.path], "b", max_bytes=cap)
        self.assertLessEqual(self.size(out), cap)
        self.assertNotIn("file_000_test", out)
        self.assertIn("file_059_test", out)
        self.assertEqual(out.count("EDIT"), 60)
        self.assertIn("bash commands dropped", out)

    def test_then_edits_then_prompt_truncation(self):
        no_bash = "\n".join(l for l in self.full.splitlines() if " BASH" not in l) + "\n"
        cap = self.size(no_bash) - 1500
        out = sd.build([self.path], "b", max_bytes=cap)
        self.assertLessEqual(self.size(out), cap)
        self.assertNotIn("BASH", out)
        self.assertNotIn("file_000.dart", out)
        self.assertIn("file_059.dart", out)
        self.assertIn("č" * 300, out)  # prompt not truncated yet

        bare = sd.build([self.path], "b", max_bytes=1)
        self.assertNotIn("EDIT", bare)
        self.assertIn("prompts truncated to 200 chars", bare)

    def test_ask_and_finding_never_dropped(self):
        out = sd.build([self.path], "b", max_bytes=1)
        self.assertIn('ASK: Q: "Keep fallback?" → A: "No"', out)
        self.assertIn("FINDING-01: keep me", out)
        self.assertIn("never dropped", out)

    def test_cap_counts_utf8_bytes(self):
        cap = 2000
        out = sd.build([self.path], "b", max_bytes=cap)
        self.assertLessEqual(self.size(out), cap)
        self.assertIn("první prompt", out)

    def test_drops_oldest_transcript_first_regardless_of_input_order(self):
        def bash_records(prefix, day):
            return [{"type": "assistant", "gitBranch": "b", "timestamp": "2026-11-%02dT10:%02d:00Z" % (day, i),
                     "message": {"content": [{"type": "tool_use", "id": "%s%d" % (prefix, i), "name": "Bash",
                                              "input": {"command": "flutter test %s_%02d %s" % (prefix, i, "-v " * 40)}}]}}
                    for i in range(20)]
        newer = _write_jsonl(self.tmp, "newer.jsonl", bash_records("new", 17))
        older = _write_jsonl(self.tmp, "older.jsonl", bash_records("old", 10))
        full = sd.build([newer, older], "b", max_bytes=10 ** 9)  # find_sessions order: newest first
        out = sd.build([newer, older], "b", max_bytes=self.size(full) - 3000)
        self.assertNotIn("old_00", out)
        self.assertEqual(out.count("flutter test new_"), 20)

    def test_default_cap_is_40000_bytes(self):
        recs = [{"type": "assistant", "gitBranch": "b", "message": {"content": [
            {"type": "tool_use", "id": "x%d" % i, "name": "Bash",
             "input": {"command": "flutter test test/f_%04d_test.dart %s" % (i, "-v " * 60)}}]}}
            for i in range(400)]
        path = _write_jsonl(self.tmp, "big.jsonl", recs)
        self.assertGreater(self.size(sd.build([path], "b", max_bytes=10 ** 9)), 40000)
        out = sd.build([path], "b")
        self.assertLessEqual(self.size(out), 40000)
        self.assertGreater(self.size(out), 39000)  # drops only what it must


class CliTest(unittest.TestCase):
    def test_cli(self):
        proc = subprocess.run([sys.executable, SCRIPT, "--branch", "feat/stock", MAIN],
                              capture_output=True, text=True, check=True)
        self.assertTrue(proc.stdout.startswith("# Session digest"))
        self.assertIn("Enable, let BE decide", proc.stdout)


if __name__ == "__main__":
    unittest.main()
