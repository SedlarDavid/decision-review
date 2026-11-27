# decision-review

Review the **decisions** an agent made in a PR, not the code.

`/vgv-wingspan:review` and `/code-review` answer "what in the code should change?".
`/decision-review` answers the questions a human reviewer of an agent-written PR actually has:

- What did the agent decide — and did I approve that, or did it decide alone?
- What behavior changed, for whom?
- What did it leave unchanged, on purpose or silently?
- Is each of those claims proven, or just stated in the PR body?

It builds a **decision ledger** of short, cited claims, then walks you through them with
Confirm / Reject / Explain more / Develop further.

## Usage

### Requirements

- **Claude Code.** The "who decided what" evidence comes from Claude Code session transcripts,
  the ledger is written by a Claude Code subagent, and triage uses its question dialogs. Other
  agents (Codex, Cursor, …) are not supported yet.
- `gh`, authenticated, for PR mode. Without it the skill reviews the local branch diff.
- Python 3 (the scripts use the standard library only).

### Install

```bash
claude plugin marketplace add SedlarDavid/decision-review
claude plugin install decision-review@decision-review
```

Then `/reload-plugins` in an open session. Update later with
`claude plugin marketplace update decision-review`.

### Run

```text
/decision-review            # PR of the current branch (or the branch diff if there is no PR)
/decision-review 140        # PR number in the current repo
/decision-review https://github.com/owner/repo/pull/140
```

Run it after `/vgv-wingspan:review` and before merging. Best in a **fresh session**: the ledger
is always written by a fresh subagent, but Explain-more answers come from the session you run it
in. The skill is user-invoked only (`disable-model-invocation`), so the word "review" never
triggers it.

**Who runs it.** The "who decided what" evidence comes from the Claude Code transcripts on the
machine that built the PR. Run it on your **own** PR before asking for review, then pick **Post
summary to PR** so the reviewer sees the outcome. Run on someone else's PR (or one built without
Claude Code), it still produces the behavior / unchanged / tests / scope items, but `made by` is
`unknown` and transcript-only claims stay `❓ UNVERIFIED`.

`vgv-wingspan` is optional: its `review.md` findings and `/vgv-wingspan:plan` hand-off are used
when present.

## Example item

```markdown
### D-06 · Unchanged · Error fallback · ✅ verified · ⚠️ risky fallback kept
Any failed stock fetch (403, offline, 5xx) still resolves to an empty entity → "Sold out".
This is the mechanism that hid the original bug. Not discussed in the plan or the session.
Evidence: `lib/product/stock_view_model.dart:275` ".catchError((_) => const Stock.empty())"
**Status:** pending
→ Keep error → sold-out fallback?
```

Item kinds: **Decision** (with `made by: user | plan | agent (implicitly approved) | agent-alone |
unknown` and the alternatives the session discussed), **Behavior** (before → after),
**Unchanged** (one per checklist category: API contract, backend permissions, caching,
loading/empty/error states, persistence, navigation, platform differences, request count,
legacy parity, anything outside the intent — each stated as changed, unchanged with a citation,
or N/A with a reason), **Tests** (what is asserted and what is not; e2e claims matched to
transcript evidence), **Scope** (plan vs delivered, review findings not addressed in the PR head).

Every claim cites code at the PR head (`path:line` + snippet), a transcript line
(`session <id8>:L<n>`), the plan or the PR body — or is marked `❓ UNVERIFIED`. A script checks
every code citation against the pinned checkout and downgrades the ones that don't hold.

## How it works

1. Resolves the PR (`gh pr view`); falls back to the local branch diff when there is no PR or
   `gh` can't reach it (e.g. Azure DevOps).
2. Pins a detached `git worktree` at the PR head in the session scratchpad — your working tree
   can be on any branch, and merged PRs whose branch is gone still work. Removed at the end.
3. Gathers evidence into the scratchpad:
   - the PR diff (generated and lock files listed by name only) and the PR body;
   - the plan doc, only when the PR, session or diff names a `docs/plan/*.md` path;
   - the Claude Code transcripts that built the PR (`scripts/find_sessions.py`: exact pr-link
     match across all `~/.claude/projects/` folders, including worktree sessions and subagent
     transcripts; falls back to sessions on the same git branch in this repo's checkouts), reduced to a ≤ 40 KB redacted digest
     (`scripts/session_digest.py`);
   - VGV review findings from `docs/code-review/<slug>/review.md` in any worktree, or the
     FINDING lines in the transcript when the report is gone.
4. A fresh `decision-ledger-agent` writes the ledger from those files only.
5. `scripts/check_citations.py` verifies each code citation within ±3 lines, and suggests
   splitting the PR when there are more than 10 calls.
6. Triage: the calls first, four per question, then the verified FYI items in one bulk question
   at the end; each answer is written to the item's `**Status:**` line immediately, so an
   interrupted triage resumes.
7. Wrap-up: verdict line, one line in the run log (below), then fix on this branch / plan the
   follow-ups / post a summary comment (preview first, ledger lines only, extra permission
   prompt) / keep the report.

## Output

`docs/code-review/<branch-slug>/decisions.md` in the **main checkout** (resolved from the git
common dir, so it survives worktree deletion), next to VGV's `review.md`. The skill warns if
the path isn't git-ignored; add `docs/code-review/` to `.gitignore`.

Re-running on the same head offers to resume triage. On a new head the old file is kept as
`decisions-<sha7>.md` and the new ledger reports whether each previous Rejected / Develop item
was addressed.

## Feedback on the tool

Status notes judge the PR. Notes about the **ledger itself** — a wrong `made by`, a missed
decision, noise — go elsewhere:

- **During triage:** answer any question's "Other" with `tool: <note>` (e.g.
  `tool: missed the retry decision`). It goes to the ledger's `## Tool notes` section and doesn't
  count as an answer about the PR.
- **Run log:** every finished triage appends one line to `~/.claude/decision-review/runs.jsonl`:
  repo, PR, head, ledger path, evidence found/missing, counts, statuses, downgraded citations,
  verdict and tool notes (`scripts/run_log.py`). It sits outside every repo, so client repo names
  never reach git. A resumed triage logs again; the last line for a ledger + head wins.
- **Any time:** write free-form notes in `~/.claude/decision-review/notes.md` (name the repo and PR).

To act on it, open Claude Code in a checkout of this repo and ask it to "review the
decision-review feedback": it reads the run log, the notes and the ledgers they point to,
groups the issues, and fixes each with a regression test. Or open an issue here.
Quick look:

```bash
jq -c 'select(.tool_notes | length > 0) | {repo, pr, verdict, tool_notes}' ~/.claude/decision-review/runs.jsonl
```

## Privacy and retention

- Transcripts can contain tokens and passwords. Only the digest is read, and it redacts
  GitHub tokens (`gh[pousr]_…`, `github_pat_…`), `sk-…` keys, AWS (`AKIA…`) and Slack (`xox?-…`)
  tokens, `Bearer …` headers, `password/secret/token/api_key = …` assignments, `--password x`
  style flags, `storePassword "…"` and PEM blocks — before any truncation. Digests stay in the
  session scratchpad.
- Nothing is posted unless you pick **Post summary to PR** and approve the preview; the comment
  holds ledger lines only.
- The run log holds ledger metadata and your tool notes only — no transcript or digest text.
- Claude Code deletes transcripts after `cleanupPeriodDays` (default 30 days). Older PRs get
  `sessions: missing` and `made by: unknown`.

## Develop

```bash
python3 -m unittest discover -s tests
claude plugin validate .
```

To work on the plugin, add your checkout as a local marketplace so edits load in place:
`claude plugin marketplace add ~/path/to/decision-review`, install from it, and run
`/reload-plugins` after each change.

The scripts are stdlib-only Python 3. Tests use small synthetic transcripts under
`tests/fixtures/`; the transcript format (pr-link, gitBranch, tool_use/tool_result records) is
undocumented, so a format change shows up as a fixture to update.
