#!/usr/bin/env python3
"""Turn multi-MB Claude Code transcripts into a small, redacted markdown digest.

Usage: session_digest.py [--branch B] [--max-bytes N] <transcript.jsonl>...

Keeps, per transcript and in order: user prompts, slash/skill invocations,
AskUserQuestion questions with their answers, assistant lines mentioning FINDING-NN,
Bash commands about tests/analysis/e2e/devices/http/gh pr/git (with exit status; plain
grep/sed/cat/ls-style reads are skipped),
MCP tool calls, and edited file paths. Each entry cites `L<n>`, the transcript line.

With --branch, only records whose gitBranch equals B are read: one session can link
several PRs on different branches.

Output is capped at --max-bytes UTF-8 bytes (default 40 000). Over the cap it drops Bash
entries oldest first, then edited paths, then truncates prompts to 200 chars (then MCP,
skill and prompt entries as a last resort). AskUserQuestion pairs and FINDING lines are
never dropped. Secrets are redacted before anything is truncated.
"""
import argparse
import json
import os
import re
import sys

MAX_BYTES = 40000
PROMPT_CHARS = 500
PROMPT_CHARS_TRIMMED = 200
CMD_CHARS = 300
LINE_CHARS = 400

REDACTIONS = [
    (re.compile(r"-----BEGIN [A-Z0-9 ]+-----[\s\S]*?(?:-----END [A-Z0-9 ]+-----|\Z)"),
     "[REDACTED PEM]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), "gh*_[REDACTED]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "github_pat_[REDACTED]"),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "AKIA[REDACTED]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "xox-[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "sk-[REDACTED]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)([\"']?\s*[=:]\s*[\"']?)"
                r"[^\s\"',;&]+"),
     r"\1\2[REDACTED]"),
    # CLI flags (--password x, --token=x) and Gradle-style storePassword "x".
    (re.compile(r"(?i)(--?(?:password|passwd|secret|token|api[_-]?key)[ =])[\"']?[^\s\"']+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(\w*(?:password|secret))(\s+[\"'])[^\"'\n]+"), r"\1\2[REDACTED]"),
]

BASH_KEEP = re.compile(
    r"(?i)\b(test|tests|analyze|e2e|integration_test|patrol|maestro|adb|xcrun|simctl|"
    r"device|devices|curl|wget|https?://|gh\s+pr|git\s|flutter\s+(run|drive|test)|"
    r"dart\s+test|npm\s+(run\s+)?test|pytest|unittest)")
# Commands that only read files: "test" or "git" in their paths is not evidence.
BASH_SKIP = re.compile(r"^\s*(?:cd\s+\S+\s*&&\s*)?(?:grep|rg|sed|cat|ls|head|tail|find|wc|echo|mkdir)\b")
FINDING = re.compile(r"FINDING-\d+")
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SKIP_PROMPT_PREFIXES = ("<task-notification>", "<local-command-stdout>", "<local-command-caveat>",
                        "<system-reminder>", "<bash-stdout>", "<bash-stderr>", "Caveat:")
COMMAND_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.S)
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
EXIT_CODE = re.compile(r"^(?:Error: )?Exit code (\d+)")


def redact(text):
    for pattern, repl in REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def clip(text, limit):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


class Entry(object):
    """One digest line. kind drives the drop order; text is already redacted."""

    def __init__(self, kind, line, text):
        self.kind, self.line, self.text = kind, line, text
        self.exit = None
        self.ts = ""  # record timestamp (ISO 8601): orders drops oldest first across transcripts

    def render(self, prompt_chars=PROMPT_CHARS):
        if self.kind == "prompt":
            return "- L%d PROMPT: %s" % (self.line, clip(self.text, prompt_chars))
        if self.kind == "bash":
            status = "" if self.exit is None else " [exit %s]" % self.exit
            return "- L%d BASH%s: `%s`" % (self.line, status, clip(self.text, CMD_CHARS))
        label = {"skill": "SKILL", "ask": "ASK", "finding": "FINDING", "mcp": "MCP",
                 "edit": "EDIT"}[self.kind]
        return "- L%d %s: %s" % (self.line, label, self.text)


def _label(path):
    """Citation label: session id8, or id8/agent id8 for a subagent transcript."""
    name = os.path.basename(path)[:-len(".jsonl")] if path.endswith(".jsonl") else os.path.basename(path)
    parts = path.split(os.sep)
    if len(parts) >= 3 and parts[-2] == "subagents":
        return "%s/%s" % (parts[-3][:8], name.replace("agent-", "")[:8])
    return name[:8]


def _text_blocks(content):
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    return [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]


def _tool_result_text(block):
    content = block.get("content")
    if isinstance(content, list):
        return "\n".join(_text_blocks(content))
    return content if isinstance(content, str) else ""


def _ask_entry(line, questions, result_record, block):
    answers = {}
    annotations = {}
    tur = result_record.get("toolUseResult")
    if isinstance(tur, dict):
        answers = tur.get("answers") or {}
        annotations = tur.get("annotations") or {}
    pairs = []
    for q in questions:
        question = q.get("question", "") if isinstance(q, dict) else str(q)
        answer = answers.get(question)
        if isinstance(answer, list):
            answer = ", ".join(str(a) for a in answer)
        if answer is not None:
            answer = clip(redact(str(answer)), LINE_CHARS)
        else:
            raw = _tool_result_text(block)
            m = re.search(re.escape('"%s"="' % question) + r'(.*?)"(?:\.|,|$)', raw, re.S)
            answer = clip(redact(m.group(1) if m else raw), LINE_CHARS)
        note = (annotations.get(question) or {}).get("notes") if isinstance(annotations, dict) else None
        text = 'Q: "%s" → A: "%s"' % (clip(redact(question), LINE_CHARS), answer)
        if note:
            text += ' (note: "%s")' % clip(redact(note), LINE_CHARS)
        pairs.append(text)
    return Entry("ask", line, redact(" · ".join(pairs)))


def digest_file(path, branch=None):
    """Return the list of Entry objects for one transcript."""
    entries, pending, edited = [], {}, set()
    mcp_run = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line_no, raw in enumerate(f, 1):
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(record, dict) or record.get("type") not in ("user", "assistant"):
                continue
            if branch is not None and record.get("gitBranch") != branch:
                continue
            mark = len(entries)
            try:
                mcp_run = _digest_record(record, line_no, entries, pending, edited, mcp_run)
            finally:
                for entry in entries[mark:]:
                    entry.ts = record.get("timestamp") or ""
    return entries


def _digest_record(record, line_no, entries, pending, edited, mcp_run):
    """Append the entries for one record; return the updated MCP run state."""
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if record["type"] == "user":
        if record.get("isMeta") or record.get("isCompactSummary"):
            return mcp_run
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                tool = pending.pop(block.get("tool_use_id"), None)
                if tool is None:
                    continue
                kind, payload = tool
                if kind == "ask":
                    entries.append(_ask_entry(line_no, payload, record, block))
                elif kind == "bash":
                    m = EXIT_CODE.match(_tool_result_text(block).strip())
                    payload.exit = m.group(1) if m else ("error" if block.get("is_error") else 0)
        if _has_tool_results(content):
            return mcp_run  # tool results sit between consecutive calls; keep the run
        for text in _text_blocks(content):
            _user_text(entries, line_no, text)
        return None
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            for text_line in block.get("text", "").splitlines():
                if FINDING.search(text_line):
                    entries.append(Entry("finding", line_no, clip(redact(text_line), LINE_CHARS)))
            continue
        if block.get("type") != "tool_use":
            continue
        name, tool_input = block.get("name", ""), block.get("input") or {}
        if name.startswith("mcp__"):
            if mcp_run is not None and mcp_run[0] == name:
                mcp_run[1].text = "%s ×%d" % (name, mcp_run[2] + 1)
                mcp_run[2] += 1
            else:
                entry = Entry("mcp", line_no, name)
                entries.append(entry)
                mcp_run = [name, entry, 1]
            continue
        mcp_run = None
        if name == "AskUserQuestion":
            pending[block.get("id")] = ("ask", tool_input.get("questions") or [])
        elif name == "Skill":
            args = tool_input.get("args") or ""
            entries.append(Entry("skill", line_no, clip(redact(
                "%s %s" % (tool_input.get("skill", ""), args)), LINE_CHARS).strip()))
        elif name == "Bash":
            command = tool_input.get("command") or ""
            if BASH_KEEP.search(command) and not BASH_SKIP.match(command):
                entry = Entry("bash", line_no, redact(command))
                entries.append(entry)
                pending[block.get("id")] = ("bash", entry)
        elif name in EDIT_TOOLS:
            file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
            if file_path and file_path not in edited:
                edited.add(file_path)
                entries.append(Entry("edit", line_no, redact(file_path)))
    return mcp_run


def _has_tool_results(content):
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def _user_text(entries, line_no, text):
    stripped = text.strip()
    if not stripped:
        return
    name = COMMAND_NAME.search(stripped)
    if name:
        args = COMMAND_ARGS.search(stripped)
        value = name.group(1).strip() + (" " + args.group(1).strip() if args and args.group(1).strip() else "")
        entries.append(Entry("skill", line_no, clip(redact(value), LINE_CHARS)))
        return
    if stripped.startswith(SKIP_PROMPT_PREFIXES):
        return
    entries.append(Entry("prompt", line_no, redact(stripped)))


def render(sections, branch, prompt_chars=PROMPT_CHARS, notes=()):
    out = ["# Session digest", ""]
    empty = [label for label, _, entries in sections if not entries]
    out.append("branch: %s · transcripts: %d" % (branch or "(all)", len(sections)))
    if empty:
        out.append("no matching entries: %s" % ", ".join(empty))
    for note in notes:
        out.append("trimmed: %s" % note)
    for label, path, entries in sections:
        if not entries:
            continue
        out.extend(["", "## session %s" % label, "file: %s" % path])
        out.extend(e.render(prompt_chars) for e in entries)
    return "\n".join(out) + "\n"


def _size(text):
    return len(text.encode("utf-8"))


def build(paths, branch=None, max_bytes=MAX_BYTES):
    sections = [(_label(p), p, digest_file(p, branch)) for p in paths]
    prompt_chars, notes = PROMPT_CHARS, []
    text = render(sections, branch, prompt_chars)
    if _size(text) <= max_bytes:
        return text

    def drop(kind, label):
        nonlocal text
        # Oldest first across all transcripts, by record timestamp (find_sessions lists the
        # newest session first, so input order is not age order); line breaks ties.
        victims = [(e.ts, i, e.line, e) for i, (_, _, es) in enumerate(sections) for e in es if e.kind == kind]
        victims.sort(key=lambda v: v[:3])
        dropped = 0
        # Drop by each line's byte size, render once, repeat if the note line tipped it over.
        while victims and _size(text) > max_bytes:
            excess = _size(text) - max_bytes
            while victims and excess > 0:
                _, i, _, e = victims.pop(0)
                sections[i][2].remove(e)
                excess -= _size(e.render(prompt_chars)) + 1
                dropped += 1
            text = render(sections, branch, prompt_chars, notes + ["%d %s dropped" % (dropped, label)])
        if dropped:
            notes.append("%d %s dropped" % (dropped, label))
        text = render(sections, branch, prompt_chars, notes)

    drop("bash", "bash commands")
    if _size(text) > max_bytes:
        drop("edit", "edited paths")
    if _size(text) > max_bytes:
        prompt_chars = PROMPT_CHARS_TRIMMED
        notes.append("prompts truncated to %d chars" % PROMPT_CHARS_TRIMMED)
        text = render(sections, branch, prompt_chars, notes)
    for kind, label in (("mcp", "MCP calls"), ("skill", "skill invocations"), ("prompt", "prompts")):
        if _size(text) > max_bytes:
            drop(kind, label)
    if _size(text) > max_bytes:
        notes.append("still over %d bytes: AskUserQuestion and FINDING lines are never dropped" % max_bytes)
        text = render(sections, branch, prompt_chars, notes)
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--branch")
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    sys.stdout.write(build(args.paths, args.branch, args.max_bytes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
