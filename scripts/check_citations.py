#!/usr/bin/env python3
"""Check a decision ledger's code citations against a checkout pinned to the PR head.

Usage: check_citations.py --ledger decisions.md --root <pr-checkout>

A code citation is `path:line` followed by a quoted snippet:  `lib/a.dart:54` "ref(path: x)".
The snippet must appear (whitespace-insensitive; "…" separates parts that must appear in
order) within ±3 lines of the cited line. Paths are relative to --root.

Ledger items are `### D-NN …` sections. An item with a failing citation is rewritten in
place: its `✅ verified` marker becomes `❓ UNVERIFIED (citation not found)` (or that marker
is appended to the heading), and the failing citation is tagged `(not found)`.
On `Evidence:` lines, a backticked `path:line` (or `path:a-b`) without a well-formed
double-quoted snippet counts as a failure too ("no checkable snippet"), so a near-miss
format can't leave an item ✅ unchecked. An item already marked UNVERIFIED keeps its one marker.

It also counts the items under `## Needs your call` (before the collapsed FYI block). More than
10 → the split note is added under that heading if the ledger lacks it, and printed.
A summary goes to stdout. Exit status is always 0: failures are reported, not fatal.
"""
import argparse
import os
import re
import sys

TOLERANCE = 3
CITATION = re.compile(r'`(?P<path>[^`\s:]+):(?P<line>\d+)`\s*"(?P<snippet>.*?)"(?=\s|$|[·,;:)\]])')
LOOSE = re.compile(r"`(?P<path>[^`\s:]+):(?P<line>\d+(?:-\d+)?)`")
ITEM = re.compile(r"^### (D-\d+)\b")
HEADING = re.compile(r"^#{1,3} ")
VERIFIED = "✅ verified"
UNVERIFIED = "❓ UNVERIFIED (citation not found)"
ANY_UNVERIFIED = "❓ UNVERIFIED"
NOT_FOUND = " (not found)"
CALLS_HEADING = re.compile(r"^## Needs your call\s*$")
SPLIT_LIMIT = 10
SPLIT_LINE = "More than %d calls — consider splitting this PR." % SPLIT_LIMIT


def _norm(text):
    return " ".join(text.split())


def check(root, path, line, snippet):
    """Return None if the citation holds, else a short reason."""
    if os.path.isabs(path):
        return "absolute path"
    full = os.path.realpath(os.path.join(root, path))
    if not full.startswith(os.path.realpath(root) + os.sep):
        return "path outside checkout"
    if not os.path.isfile(full):
        return "file not found"
    with open(full, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    if line < 1 or line > len(lines):
        return "line %d out of range (file has %d)" % (line, len(lines))
    window = _norm(" ".join(lines[max(0, line - 1 - TOLERANCE):line + TOLERANCE]))
    pos = 0
    for part in (_norm(p) for p in snippet.split("…")):
        if not part:
            continue
        found = window.find(part, pos)
        if found < 0:
            return "snippet not within ±%d lines" % TOLERANCE
        pos = found + len(part)
    return None


def process(text, root):
    """Return (new_text, results) where results is a list of (item, citation, reason)."""
    lines = text.split("\n")
    results, item, heading_idx, failed_items = [], None, None, {}
    for i, raw in enumerate(lines):
        m = ITEM.match(raw)
        if m:
            item, heading_idx = m.group(1), i
            continue
        if HEADING.match(raw):
            item, heading_idx = None, None
        new, offset = raw, 0
        found = []
        for c in CITATION.finditer(raw):
            reason = check(root, c.group("path"), int(c.group("line")), c.group("snippet"))
            found.append((c, reason))
        if raw.lstrip().startswith("Evidence:"):
            covered = [c.span() for c, _ in found]
            for loose in LOOSE.finditer(raw):
                if not any(a <= loose.start() < b for a, b in covered):
                    found.append((loose, "no checkable snippet"))
            found.sort(key=lambda f: f[0].start())
        for c, reason in found:
            cite = "%s:%s" % (c.group("path"), c.group("line"))
            results.append((item, cite, reason))
            if reason is None:
                continue
            end = c.end() + offset
            if not new[end:].startswith(NOT_FOUND):
                new = new[:end] + NOT_FOUND + new[end:]
                offset += len(NOT_FOUND)
            if heading_idx is not None:
                failed_items[heading_idx] = item
        lines[i] = new
    for idx in failed_items:
        heading = lines[idx]
        if ANY_UNVERIFIED in heading:
            continue
        lines[idx] = heading.replace(VERIFIED, UNVERIFIED) if VERIFIED in heading \
            else heading.rstrip() + " · " + UNVERIFIED
    return "\n".join(lines), results


def split_note(text):
    """Return (new_text, calls). Counts `### D-NN` items under `## Needs your call`, stopping at
    the next `## ` heading or the collapsed FYI `<details>`; adds the split note under the
    heading when calls exceed SPLIT_LIMIT and the ledger has no such note yet."""
    lines = text.split("\n")
    start = next((i for i, raw in enumerate(lines) if CALLS_HEADING.match(raw)), None)
    if start is None:
        return text, 0
    calls = 0
    for raw in lines[start + 1:]:
        if raw.startswith("## ") or raw.lstrip().startswith("<details"):
            break
        if ITEM.match(raw):
            calls += 1
    if calls > SPLIT_LIMIT and "consider splitting" not in text:
        lines[start + 1:start + 1] = ["", "> " + SPLIT_LINE]
    return "\n".join(lines), calls


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    with open(args.ledger, encoding="utf-8") as f:
        text = f.read()
    new_text, results = process(text, args.root)
    new_text, calls = split_note(new_text)
    if new_text != text:
        with open(args.ledger, "w", encoding="utf-8") as f:
            f.write(new_text)
    failures = [r for r in results if r[2] is not None]
    items = sorted({r[0] for r in failures if r[0]})
    print("checked %d citation(s): %d ok, %d failed%s" % (
        len(results), len(results) - len(failures), len(failures),
        " → downgraded %s" % ", ".join(items) if items else ""))
    for item, cite, reason in failures:
        print("- %s %s: %s" % (item or "(outside items)", cite, reason))
    if calls > SPLIT_LIMIT:
        print(SPLIT_LINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
