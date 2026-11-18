#!/usr/bin/env python3
"""Find the Claude Code session transcripts that built a PR.

Usage: find_sessions.py --repo owner/name --pr N [--branch B] [--repo-root DIR]... [--exclude-session ID] [--projects-dir DIR]

Prints one transcript path per line, newest session first, each followed by its
subagents/*.jsonl. A short note on how the sessions were matched goes to stderr.

Matching:
1. Every project folder is searched for `/pull/<n>"`, the end of a JSON string value
   (closing quote included, so pull/14 never matches pull/140; an escaped quote inside
   message text never matches). Matched files' pr-link records are parsed to confirm
   prUrl, prRepository and prNumber, ignoring case (GitHub owner/repo are case-insensitive,
   and a case-insensitive scan over GBs of transcripts is far slower).
2. If nothing matches and --branch is given, sessions with a record whose gitBranch equals
   the branch are used instead (never for default-branch names, which match everything).
   With --repo-root (repeatable: the main checkout and each worktree), that record's cwd must
   also be inside one of the roots, so another repo's branch of the same name never matches.

--exclude-session drops one session (and its subagents) from either match: the reviewing
session itself matches the branch fallback when it did not build the change.

The project folder is never derived from the current directory: worktree sessions are
filed under their own folders.
"""
import argparse
import glob
import json
import os
import sys

DEFAULT_BRANCHES = {"main", "master", "develop", "HEAD"}
CHUNK = 1 << 23


def _files_containing(needle, root):
    """Paths of *.jsonl files under root containing needle verbatim.

    A byte scan in Python: macOS /usr/bin/grep -rF takes ~35s over 5 GB of transcripts,
    this takes ~4s.
    """
    needle = needle.encode("utf-8")
    hits = []
    for directory, _, files in os.walk(root):
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(directory, name)
            try:
                with open(path, "rb") as f:
                    tail = b""
                    while True:
                        chunk = f.read(CHUNK)
                        if not chunk:
                            break
                        window = tail + chunk
                        if needle in window:
                            hits.append(path)
                            break
                        tail = window[1 - len(needle):]
            except OSError:
                continue
    return hits


def _session_file(path, root):
    """Map a matched file to its top-level session transcript (<project>/<id>.jsonl)."""
    rel = os.path.relpath(path, root).split(os.sep)
    if len(rel) == 2:
        return path
    # <project>/<session-id>/subagents/<agent>.jsonl → <project>/<session-id>.jsonl
    if len(rel) == 4 and rel[2] == "subagents":
        return os.path.join(root, rel[0], rel[1] + ".jsonl")
    return None


def _records_matching(path, marker, predicate):
    """True if any JSON record on a line containing marker satisfies predicate."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if marker not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and predicate(record):
                    return True
    except OSError:
        return False
    return False


def _candidates(needle, root):
    found = set()
    for path in _files_containing(needle, root):
        session = _session_file(path, root)
        if session and os.path.isfile(session):
            found.add(session)
    return found


def by_pr(repo, pr, root):
    url = ("https://github.com/%s/pull/%d" % (repo, pr)).lower()
    needle = '/pull/%d"' % pr

    def confirm(r):
        return (r.get("type") == "pr-link"
                and str(r.get("prUrl", "")).lower() == url
                and str(r.get("prRepository", "")).lower() == repo.lower()
                and str(r.get("prNumber")) == str(pr))

    return {s for s in _candidates(needle, root) if _records_matching(s, '"pr-link"', confirm)}


def _inside(path, roots):
    path = os.path.realpath(path)
    return any(path == r or path.startswith(r + os.sep) for r in roots)


def by_branch(branch, root, repo_roots=None):
    needle = '"gitBranch":%s' % json.dumps(branch)
    roots = [os.path.realpath(os.path.expanduser(r)) for r in repo_roots or []]

    def confirm(r):
        if r.get("gitBranch") != branch:
            return False
        return not roots or (isinstance(r.get("cwd"), str) and _inside(r["cwd"], roots))

    return {s for s in _candidates(needle, root) if _records_matching(s, '"gitBranch"', confirm)}


def expand(sessions):
    """Newest session first, each followed by its subagent transcripts (*.meta.json skipped)."""
    out = []
    for session in sorted(sessions, key=lambda p: (-os.path.getmtime(p), p)):
        out.append(session)
        sub = os.path.join(session[:-len(".jsonl")], "subagents")
        out.extend(sorted(glob.glob(os.path.join(sub, "*.jsonl"))))
    return out


def find(repo, pr, branch=None, projects_dir=None, exclude=None, repo_roots=None):
    """Return (paths, how) where how is 'pr-link', 'branch' or 'none'."""
    root = os.path.expanduser(projects_dir or "~/.claude/projects")
    if not os.path.isdir(root):
        return [], "none"

    def keep(sessions):
        return {s for s in sessions if os.path.basename(s)[:-len(".jsonl")] != exclude}

    if repo and pr is not None:
        sessions = keep(by_pr(repo, pr, root))
        if sessions:
            return expand(sessions), "pr-link"
    if branch and branch not in DEFAULT_BRANCHES:
        sessions = keep(by_branch(branch, root, repo_roots))
        if sessions:
            return expand(sessions), "branch"
    return [], "none"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="owner/name")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--branch")
    parser.add_argument("--repo-root", action="append", default=[],
                        help="checkout or worktree path the branch fallback must match (repeatable)")
    parser.add_argument("--exclude-session", help="session id to leave out (with its subagents)")
    parser.add_argument("--projects-dir", default="~/.claude/projects")
    args = parser.parse_args(argv)
    paths, how = find(args.repo, args.pr, args.branch, args.projects_dir, args.exclude_session,
                      args.repo_root)
    for p in paths:
        print(p)
    notes = {
        "pr-link": "matched by pr-link to %s#%s" % (args.repo, args.pr),
        "branch": "no pr-link match; matched by gitBranch %s" % args.branch,
        "none": "no session found",
    }
    sessions = sum(1 for p in paths if os.sep + "subagents" + os.sep not in p)
    print("%s (%d session(s), %d file(s))" % (notes[how], sessions, len(paths)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
