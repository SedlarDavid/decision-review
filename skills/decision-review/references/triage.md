# Triage

Walk the reviewer through the ledger with `AskUserQuestion`, persist each answer in
`decisions.md`, then wrap up. The ledger file is the state: an interrupted triage resumes from
the items whose `**Status:**` is still `pending`.

## 1. Verified FYI — one bulk question

FYI items marked `❓ UNVERIFIED` (downgraded by the citation check) never go in the bulk
question: they join the "Needs your call" queue first. Skip the bulk question if no other FYI
items are pending. Otherwise one `AskUserQuestion` (single question, header `FYI`):

- **Accept all (Recommended)** — every pending FYI item → `confirmed`.
- **Pick some to inspect** — follow up with a `multiSelect: true` question listing the FYI items
  (`D-NN · <Kind> · <Category>`, max 4 options per question; split into several questions if
  more). Selected items join the "Needs your call" queue; the rest → `confirmed`.

## 2. Needs your call — batches of four

Queue = pending items under "Needs your call" (plus any FYI items picked above), in ledger
order. Each `AskUserQuestion` call carries up to **four questions, one item each**.

Each question must stand alone — the reviewer may see only the dialog:

- `header`: `D-NN` (≤ 12 chars).
- `question`: the item's claim in one or two sentences, its marker/flag, then its `→` question.
  Example: "D-06 (verified, risky fallback kept): any failed stock fetch still shows
  'Sold out' — this hid the original bug. Keep error → sold-out fallback?"
- `options` (single-select, in this order):
  1. **Confirm** — "Keep as is." Add `(Recommended)` only when the item is `✅ verified` and
     unflagged; never recommend for UNVERIFIED or flagged items.
  2. **Reject** — "Revert, or switch to the alternative" (name the alternative when the item
     has one).
  3. **Explain more** — "Show more evidence, then ask again."
  4. **Develop further** — "Right direction, needs more work."
- Free text through "Other" is the reviewer's note. Interpret it: if it clearly picks an action
  ("reject, use cache"), apply that action with the text as note; if it is a question, treat it
  as Explain more with that question; otherwise record it as `develop — <text>`.
  A note attached to a picked option (annotations) is stored with that option.
- **Tool notes.** Text that starts with `tool:` — in "Other" or an annotation, on any question
  including FYI and Next — is about the ledger itself (wrong `made by`, missed decision, noise),
  not about the PR. Append it to `## Tool notes` as `- D-NN: <text after "tool:">` (or `- <text>`
  when it isn't about one item); create the section at the end of the file if it's missing.
  It is not an answer: from "Other", the item stays pending and is asked again; in an
  annotation, the picked option still applies.

Before the first batch, say once: "Type `tool: …` in Other to note a problem with the ledger
itself."

## 3. Persist after every batch

Right after each `AskUserQuestion` returns, before anything else, rewrite the answered items'
`**Status:**` lines in `decisions.md` with Edit:

| Answer | Status line |
|---|---|
| Confirm | `**Status:** confirmed` (or `confirmed — <note>`) |
| Reject | `**Status:** rejected — <note or "no note">` |
| Develop further | `**Status:** develop — <note or "no note">` |
| Explain more | unchanged (`pending`) until answered again |

Also append each rejected / develop item to `## Follow-ups`:
`- D-NN · rejected — <one-line claim> — <note>`, and any tool notes to `## Tool notes`.
Update `counts` in the frontmatter at the end of triage, not per batch.

## 4. Explain more

For each item answered Explain more (after persisting the rest of the batch):

1. Gather **new** evidence yourself in the main session — do not re-read the item back. Sources,
   in order of usefulness:
   - code in the pinned checkout (`Read` / `Grep` under `<scratch>/pr-<n>`; callers, the test
     file, the previous version via `git -C <checkout> show <base>:<path>`);
   - the digest (`evidence/session.md`) — quote the relevant lines with their `L<n>`;
   - the diff hunk (`evidence/diff.patch`);
   - the reviewer's own question from "Other", answered directly.
2. Print a short explanation (≤ 10 lines) with citations in the ledger formats.
3. If the new evidence changes the claim (it was wrong, or now verified/unverified), Edit the
   item itself, keep its id, and say what changed.
4. Ask about that item again in the next batch (it stays in the queue). Two Explain-mores on the
   same item → in the third ask, put **Develop further** first so the reviewer can park it.

## 5. Wrap up

When no pending items remain:

1. Update frontmatter `counts`, and add `triaged: <YYYY-MM-DD>`.
2. Print one verdict line:
   - all confirmed → `All N calls confirmed — ready to merge.` (for a merged PR:
     `All N calls confirmed — nothing to follow up.`)
   - otherwise → `<r> rejected · <d> to develop · <c> confirmed`, then the Follow-ups list.
3. Log the run:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run_log.py" --ledger <decisions.md> --repo <owner/name>`
   (branch mode: `--repo <basename of main>`). It appends one summary line — evidence, counts,
   statuses, downgraded citations, verdict, tool notes — to `~/.claude/decision-review/runs.jsonl`,
   outside every repo, so problems with the tool can be reviewed across projects later. A failure
   here is reported in one line and never blocks the wrap-up.
4. `AskUserQuestion` (header `Next`), options depending on state:
   - **Fix on this branch** (only when there are follow-ups) — work the follow-ups now. If the PR is
     merged or its branch is gone, create `fix/<slug>-decisions` from the default branch first
     and mention the original PR URL in the eventual commit/PR body. Follow the project's normal
     task workflow from there.
   - **Plan it** (only when there are follow-ups and the `vgv-wingspan:plan` skill is available)
     — invoke `/vgv-wingspan:plan` with the Follow-ups section and the ledger path as input.
   - **Post summary to PR** (only when there is a GitHub PR) — see below.
   - **Keep report and exit** — print the `decisions.md` path and stop.

### Post summary to PR

1. Build the comment from ledger lines only — never digest excerpts, transcript text, or file
   contents beyond the cited snippets:

   ```markdown
   **Decision review** (<head sha7>) — <verdict line>

   | Id | Item | Outcome |
   |---|---|---|
   | D-01 | Decision · endpoint → `availability` | confirmed |
   | D-06 | Unchanged · error → sold-out fallback | develop — show retry instead |

   <sub>Generated by /decision-review from the PR diff, plan, session transcript and review findings.</sub>
   ```

2. Show the full preview in chat and ask (`AskUserQuestion`): **Post it** / **Don't post**.
3. On Post it: write the body to `<scratch>/pr-comment.md` and run
   `gh pr comment <n> --body-file <scratch>/pr-comment.md`. This command is deliberately not in
   the skill's `allowed-tools`, so the user gets a permission prompt too.

## Resume

When the skill starts and `decisions.md` exists for the same head SHA with pending items, it
offers **Resume triage (Recommended)** / **Rebuild ledger** / **Exit**. Resume skips straight to
this file's step 1 (FYI only if any FYI item is still pending) and asks only about pending items.
