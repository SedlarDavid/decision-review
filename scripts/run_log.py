#!/usr/bin/env python3
"""Append one summary line per /decision-review run to a global JSONL log.

Usage: run_log.py --ledger <decisions.md> [--repo owner/name] [--log PATH]

Reads only the ledger: its frontmatter (pr, url, head, slug, evidence, counts, triaged), each
item's `**Status:**` line, `citation not found` markers, and the `## Tool notes` section the
reviewer filled with "tool: …" answers. Appends one JSON object to
~/.claude/decision-review/runs.jsonl (or --log). The log sits outside every repo, so client
repo names never reach git, and it never holds transcript or digest text.

A resumed triage logs the same ledger again; the last line for a ledger + head wins.
Prints the log path. Exit status 1 only when the ledger can't be read.
"""
import argparse
import datetime
import json
import os
import re
import sys

DEFAULT_LOG = os.path.join(os.path.expanduser("~"), ".claude", "decision-review", "runs.jsonl")
ITEM = re.compile(r"^### (D-\d+)\b")
STATUS = re.compile(r"^\*\*Status:\*\*\s*([a-z]+)", re.I)
TOOL_NOTE = re.compile(r"^- (?:(D-\d+):\s*)?(.+)$")
REPO_FROM_URL = re.compile(r"github\.com/([^/\s]+/[^/\s]+)/pull/\d+")
COMMENT = re.compile(r"\s+#\s.*$")  # "pr: 140  # or branch"; keeps "FINDING #3"
VALUE_CHARS = 200
NOTE_CHARS = 500
STATUSES = ("confirmed", "rejected", "develop", "pending")


def _scalar(value):
    value = value.strip().strip('"').strip("'")
    if value.isdigit():
        return int(value)
    return value[:VALUE_CHARS]


def _inline_map(value):
    out = {}
    for pair in value.strip().strip("{}").split(","):
        key, sep, val = pair.partition(":")
        if sep and key.strip():
            out[key.strip()] = _scalar(val)
    return out


def frontmatter(text):
    """Parse the ledger's small YAML header: scalars, one level of nesting, inline {a: 1} maps."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    data, parent = {}, None
    for raw in text[4:end].splitlines():
        line = COMMENT.sub("", raw.rstrip())
        key, sep, value = line.strip().partition(":")
        if not sep or not key:
            continue
        nested = line.startswith(" ") and isinstance(data.get(parent), dict)
        target = data[parent] if nested else data
        value = value.strip()
        if value.startswith("{"):
            target[key] = _inline_map(value)
        elif value or nested:
            target[key] = _scalar(value)
        else:
            data[key], parent = {}, key
    return data


def tool_notes(lines):
    notes, inside = [], False
    for line in lines:
        if line.startswith("## "):
            inside = line.strip() == "## Tool notes"
            continue
        m = TOOL_NOTE.match(line.strip()) if inside else None
        if m:
            notes.append({"item": m.group(1), "note": m.group(2).strip()[:NOTE_CHARS]})
    return notes


def verdict(statuses):
    if statuses["pending"]:
        return "%d pending" % statuses["pending"]
    if not statuses["rejected"] and not statuses["develop"]:
        return "all %d confirmed" % statuses["confirmed"]
    return "%(rejected)d rejected · %(develop)d to develop · %(confirmed)d confirmed" % statuses


def summarize(text, ledger_path, repo=None):
    lines = text.splitlines()
    fm = frontmatter(text)
    statuses = dict.fromkeys(STATUSES, 0)
    downgraded = 0
    for line in lines:
        if ITEM.match(line) and "citation not found" in line:
            downgraded += 1
        m = STATUS.match(line)
        if m and m.group(1).lower() in statuses:
            statuses[m.group(1).lower()] += 1
    url = fm.get("url") if isinstance(fm.get("url"), str) else None
    from_url = REPO_FROM_URL.search(url or "")
    return {
        "v": 1,
        "logged": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "repo": repo or (from_url.group(1) if from_url else None),
        "pr": fm.get("pr"),
        "url": url,
        "head": fm.get("head"),
        "slug": fm.get("slug"),
        "ledger": os.path.abspath(ledger_path),
        "triaged": fm.get("triaged"),
        "evidence": fm.get("evidence") if isinstance(fm.get("evidence"), dict) else {},
        "counts": fm.get("counts") if isinstance(fm.get("counts"), dict) else {},
        "statuses": statuses,
        "citations_downgraded": downgraded,
        "verdict": verdict(statuses),
        "tool_notes": tool_notes(lines),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--repo", help="owner/name, or the repo folder name in branch mode")
    parser.add_argument("--log", default=DEFAULT_LOG)
    args = parser.parse_args(argv)
    try:
        with open(args.ledger, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print("run_log: can't read ledger: %s" % e, file=sys.stderr)
        return 1
    record = summarize(text, args.ledger, args.repo)
    os.makedirs(os.path.dirname(os.path.abspath(args.log)), exist_ok=True)
    with open(args.log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print("logged run → %s" % args.log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
