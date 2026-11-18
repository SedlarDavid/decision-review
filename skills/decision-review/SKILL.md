---
name: decision-review
description: Review the decisions an agent made in a PR, not the code. Builds a cited decision ledger — intent, decisions with who made them, behavior changes, explicit "unchanged" assertions, test/e2e evidence, scope vs plan and unaddressed review findings — from the PR diff, plan doc, Claude Code session transcripts and VGV review findings, then walks the human reviewer through Confirm / Reject / Explain more / Develop further.
when_to_use: Use only when the user runs /decision-review, or asks to "review the decisions" in a PR, "what did the agent decide", or "is this PR ready for me to merge" as a human reviewer. Not for code-quality findings or bug hunting — that is /vgv-wingspan:review or /code-review.
argument-hint: "[PR number|URL]"
disable-model-invocation: true
allowed-tools: Bash(python3 *decision-review/scripts/*) Bash(python3 *decision-review/*/scripts/*) Bash(gh pr view *) Bash(gh pr diff *) Bash(gh repo view *) Bash(git fetch origin *) Bash(git worktree *) Bash(git rev-parse *) Bash(git merge-base *) Bash(git diff *) Bash(git -C * show *) Bash(git -C * diff *) Bash(git -C * log *) Bash(git -C * check-ignore *) Bash(mkdir -p *) Bash(mv */docs/code-review/*/decisions.md */docs/code-review/*/decisions-*.md)
---

# Decision review

VGV `/review` answers "what in the code should change?". This skill answers:
**what did the agent decide, what behavior changed, what did it deliberately leave alone, and is
each claim proven?** The output is a ledger the reviewer triages item by item.

<pr_argument>$ARGUMENTS</pr_argument>

Files of this plugin:

- Scripts: `${CLAUDE_PLUGIN_ROOT}/scripts/{find_sessions,session_digest,check_citations,run_log}.py`
- Ledger format: `${CLAUDE_SKILL_DIR}/references/ledger-template.md`
- Triage procedure: `${CLAUDE_SKILL_DIR}/references/triage.md`
- Ledger agent: `decision-review:decision-ledger-agent`

Nothing in this skill posts anywhere unless the reviewer picks **Post summary to PR** at the end
and approves the preview.

## 1. Scope

1. Resolve the PR. With an argument (number or URL), run
   `gh pr view <arg> --json number,url,title,state,body,headRefName,headRefOid,baseRefName,baseRefOid,mergedAt`.
   Without one, run the same command with no argument (the current branch's PR).
2. Parse `owner/name` from the PR `url` (`https://github.com/<owner>/<name>/pull/<n>`) and compare
   it with `gh repo view --json nameWithOwner -q .nameWithOwner` (case-insensitive). On a mismatch
   (a URL for another repo, or `origin` is a fork) stop: "PR is in <owner/name>, this checkout is
   <other> — run it from a checkout of <owner/name>."
3. **No PR, or `gh` fails** (not authenticated, no PR for the branch, non-GitHub remote such as
   Azure DevOps): switch to **branch mode** and say so in one line. In branch mode:
   - head = `git rev-parse HEAD`, branch = `git rev-parse --abbrev-ref HEAD`;
   - base = `git rev-parse --abbrev-ref @{upstream}` if the branch tracks a *different* branch,
     else `git rev-parse --abbrev-ref origin/HEAD` (e.g. `origin/main`), else the first of
     `main`, `master`, `develop` that `git rev-parse --verify --quiet <name>` finds (repos with
     no remote), else ask the user for the base;
   - if branch is the default branch, stop: "Nothing to review — on the default branch."
   - the ledger covers committed work only: if `git status --porcelain` shows changes, say
     "Uncommitted changes are not reviewed" and record it in `scope.md`.
4. `slug` = head branch name with `/` replaced by `-` (matches VGV `/review`'s
   `docs/code-review/<slug>/`).
5. `main` = the main checkout: `dirname "$(git rev-parse --path-format=absolute --git-common-dir)"`.
   The report always goes under `<main>/docs/code-review/<slug>/` so it survives worktree deletion.
6. `scratch` = a new directory `decision-review-<n or slug>` inside your scratchpad directory
   (`mkdir -p <scratch>/evidence`).

Announce: PR #, title, state (open / merged), head SHA (7), base, mode.

## 2. Re-run check

If `<main>/docs/code-review/<slug>/decisions.md` exists, read its frontmatter `head:`.

- **Same head SHA** → `AskUserQuestion`: **Resume triage (Recommended)** (only if any
  `**Status:** pending` remains) / **Rebuild ledger** / **Exit**. Resume → run steps 3 and 4
  (Explain more needs the pinned checkout and evidence), skip 5–6, go to step 7.
  Rebuild → continue; the old file is overwritten.
- **Different head SHA** → collect its items whose Status is `rejected` or `develop` (id, claim,
  note) as `PREVIOUS_FOLLOWUPS`, say so in one line and continue. The old file is renamed in
  step 6.2, once the new ledger exists, so a failed run never loses it.

## 3. Pin the code

The ledger agent and the citation check read **only** a detached checkout of the PR head. The
user's working tree may be on any branch, and a merged PR's branch may be gone.

1. PR mode: `git fetch origin pull/<n>/head` and `git fetch origin <baseRefName>`.
   Branch mode: skip fetching; use the local head SHA.
2. `checkout` = `<scratch>/pr-<n>` (branch mode: `<scratch>/pr-<slug>`). If
   `git worktree list --porcelain` already lists it (an interrupted earlier run), run
   `git worktree remove --force <checkout>` and `git worktree prune` first. Then
   `git worktree add --detach <checkout> <headSha>`.
3. **From here on, every exit path you control — success, error, triage finished, the user
   choosing Exit — ends with `git worktree remove --force <checkout>`.** If removal fails, run
   `git worktree prune` and tell the user the path. An Esc interrupt can't run cleanup; step 3.2
   of the next run removes the leftover.

## 4. Gather evidence (`<scratch>/evidence/`)

Run independent commands in parallel.

1. **Diff.** `mb = git merge-base <baseRefOid or base ref> <headSha>`. Then
   - `git -C <checkout> diff --name-status <mb> HEAD` → file list;
   - `git -C <checkout> diff <mb> HEAD -- . <excludes> > <scratch>/evidence/diff.patch`, with
     excludes for generated and lock files:
     `':(exclude,glob)**/*.g.dart' ':(exclude,glob)**/*.freezed.dart' ':(exclude,glob)**/*.gr.dart' ':(exclude,glob)**/*.mocks.dart' ':(exclude,glob)**/*.lock' ':(exclude,glob)**/package-lock.json' ':(exclude,glob)**/pnpm-lock.yaml' ':(exclude,glob)**/*.min.js' ':(exclude,glob)**/*.map' ':(exclude,glob)**/build/**' ':(exclude,glob)**/dist/**'`.
   - If `merge-base` fails (base not fetchable), equals `headSha`, or `diff.patch` comes out
     empty, fall back to `gh pr diff <n> > …/diff.patch` and list generated files from
     `gh pr diff <n> --name-only`; note the fallback in `scope.md`.
   - Excluded files are listed **by name only** in `scope.md` under "Generated / lock files".
   - Any remaining single file whose diff exceeds ~3000 lines: also list by name, and say so.
2. **PR body** → `pr-body.md` (from the `gh pr view` JSON; empty in branch mode).
3. **Sessions.**
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/find_sessions.py" --repo <owner/name> --pr <n> --branch <head branch>`
   plus one `--repo-root <path>` for `main` and for each path in `git worktree list --porcelain`
   (scopes the branch fallback to this repo). Branch mode: drop `--repo` and `--pr`. It prints transcript paths on stdout and how it matched on
   stderr. Add `--exclude-session ${CLAUDE_SESSION_ID}` unless this session built the change:
   the branch fallback would otherwise match this review-only session, which is not evidence.
   If any paths:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/session_digest.py" --branch <head branch> <paths…> > <scratch>/evidence/session.md`.
   Do **not** read the raw JSONL files yourself — they are multi-MB and may contain secrets.
4. **Plan doc.** Use a plan only when the PR body, `session.md` or the diff file list names a
   `docs/plan/*.md` path explicitly. Read it from `checkout` (else `main`) and save it as
   `plan.md`. Several candidates → ask once with `AskUserQuestion`. None → "no plan found".
5. **Review findings.** Look for `docs/code-review/<slug>/review.md` in `main` and in every path
   from `git worktree list --porcelain`. Found → copy its content to `review.md`. Not found →
   the agent uses the FINDING / ASK lines in `session.md`; record "review: digest" (or
   "missing" if the digest has none).
6. **`scope.md`** — write: mode, PR number + URL + title + state, head SHA, base ref + merge-base,
   slug, changed-file count, generated/lock files by name, and the evidence line for each
   source (plan / sessions with the find_sessions note / review: found, digest, or missing).

## 5. Build the ledger

Spawn **one** fresh `decision-review:decision-ledger-agent` (Agent tool). It is fresh on purpose:
it must not be anchored on the build session's reasoning, even when this skill runs inside that
session. Prompt:

```text
EVIDENCE_DIR: <scratch>/evidence
CHECKOUT: <checkout>
TEMPLATE: ${CLAUDE_SKILL_DIR}/references/ledger-template.md
PREVIOUS_FOLLOWUPS: <items from step 2, or "none">
Build the decision ledger for PR #<n> (<owner/name>, head <sha7>). Return only the decisions.md content.
```

Do not add your own opinions of the PR to the prompt.

## 6. Write and check

1. `git -C <main> check-ignore -q docs/code-review/<slug>/decisions.md`. Exit status 1 (not
   ignored) → warn once: "`docs/code-review/` is not git-ignored — add `docs/code-review/` to
   `.gitignore` so ledgers aren't committed." Continue either way.
2. If step 2 found a ledger for an older head, `mv` it to `decisions-<old sha7>.md` in the same
   folder now. Then write the agent's output to `<main>/docs/code-review/<slug>/decisions.md`
   (strip a wrapping code fence if the agent added one).
3. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_citations.py" --ledger <that file> --root <checkout>`.
   It rewrites failing items to `❓ UNVERIFIED (citation not found)` in place and prints a summary.
4. Downgraded items stay where they are, with their ids; triage asks about every UNVERIFIED
   item individually, even inside Verified FYI. Recount `counts.unverified` in the frontmatter.
5. Print a short summary: intent line, counts (needs call / FYI / unverified), evidence missing,
   citation-check result, and the file path. If "Needs your call" has more than 10 items, repeat
   the split recommendation.

## 7. Triage

Keep `checkout` and `<scratch>/evidence` until triage ends — Explain more reads them. Follow
`${CLAUDE_SKILL_DIR}/references/triage.md`: FYI bulk question, batches of four
Confirm / Reject / Explain more / Develop further questions, persist Status lines after every
batch, `tool:` notes about the ledger itself, Explain-more loop, wrap-up verdict, run log and
next-step menu.

## 8. Clean up

Remove the worktree (step 3.3). Leave `decisions.md` in place. Scratch evidence stays in the
session scratchpad only — never copy `session.md` into the repo or a PR.

## Gotchas

- **Merged PRs**: the head branch may be deleted; `pull/<n>/head` still fetches. Fixes go on a new
  branch from the default branch (triage wrap-up handles it).
- **Stacked PRs**: always diff against `baseRefName`/`baseRefOid`, never the default branch.
- **Transcript retention**: Claude Code deletes transcripts after `cleanupPeriodDays` (default
  30). Older PRs get "sessions: missing" and `made by: unknown`; that is expected, not an error.
- **Worktree sessions** are filed under their own `~/.claude/projects/` folder;
  `find_sessions.py` searches all folders, so never pass it a folder derived from the cwd.
- **Fresh session gives the best result.** The ledger agent is fresh either way, but triage's
  Explain-more answers come from this session — say so once if this session built the PR.
- **Codegraph/LSP** describe the user's working tree, not the PR head — don't use them for claims
  about the PR; read `checkout` directly.
- **Secrets**: transcripts can contain tokens and passwords. Only the redacted digest is read; a
  PR comment holds ledger lines only.
