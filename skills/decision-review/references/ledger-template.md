# Decision ledger template

The ledger is `docs/code-review/<slug>/decisions.md`. It is written for a human reviewer who has
not read the diff: every item is a short claim they can Confirm, Reject, ask to Explain more,
or send back to Develop further. English prose; quote UI copy and prompts in their original
language, exactly as written ("Ausverkauft").

## File shape

```markdown
---
pr: 140                                  # or "branch" when there is no PR
url: https://github.com/owner/repo/pull/140
head: <full head SHA>
base: <baseRefName>
slug: <head branch with / → ->
evidence:
  plan: docs/plan/2026-11-10-fix-stock.md | missing (no plan named in PR body, session or diff)
  sessions: 3f9a1c2e (+8 subagents) | missing (no transcript matched; older than 30 days?)
  review: docs/code-review/<slug>/review.md | digest (FINDING lines from session) | missing
counts: { needs_call: 7, fyi: 9, unverified: 1 }
---

# Decision review — PR #140: <PR title>

## Intent

<One sentence: what the PR is for.> Source: plan | PR body | session <id8>:L<n>

## Needs your call

### D-01 · <Kind> · <qualifiers> · <marker>
...

<details><summary>Verified FYI (N items)</summary>

### D-08 · Unchanged · Navigation · ✅ verified
...

</details>

## Follow-ups

<!-- Filled during triage: one line per Rejected / Develop item. -->
- D-03 · rejected — <reviewer note>

## Tool notes

<!-- Filled during triage: problems with this ledger itself (reviewer typed "tool: …"). -->
- D-05: made-by should be user — I picked option 2 in the session
```

The agent writes both closing sections with only their `<!-- … -->` comment; triage fills them.

Ids are `D-NN`, two digits, assigned in the order items appear (Needs your call first, then FYI).
On a re-run against a new head SHA the ids restart; never reuse an old id for a different claim
inside one file.

## Item format

```markdown
### D-NN · <Kind> · <qualifiers> · <marker>[ · <flag>]
<Claim: 1–3 sentences, before → after where it applies.>
<Kind-specific lines, see below.>
Evidence: <citation> · <citation>
**Status:** pending
→ <the one question the reviewer answers, phrased so Confirm means "yes, keep it">
```

- **Marker** — exactly one of:
  - `✅ verified`: every claim in the item has a citation that `check_citations.py` can check, or a
    transcript / PR-body citation the agent read itself.
  - `❓ UNVERIFIED (<why>)`: the claim has no evidence, or the only evidence is the PR body or
    the agent's own inference. Common reasons: `no transcript`, `PR body only`,
    `citation not found` (set by `check_citations.py`).
- **Flag** (optional, after the marker): `⚠️ rationale removed`, `⚠️ risky fallback kept`,
  `⚠️ not addressed`, `needs your call`. A flag moves an Unchanged item into "Needs your call".
- **Status** — `pending` when written. Triage rewrites it to
  `confirmed`, `rejected — <note>`, or `develop — <note>`, optionally `confirmed — <note>`.
  Nothing else edits it.
- The `→` question is omitted for FYI items.
- N/A lines and `see D-MM` pointer lines have no Evidence or Status line and are never triaged.

## Citations

Every claim needs one, or the item is `❓ UNVERIFIED`. Formats:

| Source | Format | Example |
|---|---|---|
| Code at PR head | `` `path:line` "snippet" `` | `` `lib/api/products.dart:54` "ref(path: '$productId/availability')" `` |
| Transcript | `session <id8>:L<n>` (subagent: `session <id8>/<agent8>:L<n>`) | `session 3f9a1c2e:L812` |
| PR body | `PR body` | `PR body ("Gate logic … is unchanged")` |
| Plan | `plan:<heading or line>` | `plan:L42` |
| Diff only (deleted lines) | `diff <path> -L<old line> "snippet"` | `diff lib/repo.dart -L27 "stock is volatile"` |

Code citation rules (enforced by `check_citations.py`):

- `path` is relative to the PR checkout root; `line` is 1-based in the **PR head** file.
- The snippet is copied verbatim from that line or the 3 lines around it. Whitespace differences
  are fine. Use `…` to elide between two parts on nearby lines, in order.
- Keep snippets short (≤ 80 chars) and distinctive. No backticks or double quotes inside them;
  pick a different part of the line instead.
- Deleted code has no head line: cite it with the `diff` form (not machine-checked) and describe
  what was removed.

## Item kinds

### Decision

What was chosen, why, and who chose it.

```markdown
### D-02 · Decision · made by: agent (from BE audit) · ✅ verified
Stock check now calls `product/{id}/availability` instead of `admin/stock`.
Reason: old endpoint is admin-only (403 for regular/anonymous users → read as 0 stock → "Sold out").
Alternatives considered: BE permission change — rejected in session ("no BE change needed").
Evidence: `lib/api/products_api.dart:54` "ref(path: '$productId/availability')" · session 3f9a1c2e:L812
**Status:** pending
→ Confirm this endpoint choice?
```

`made by` (pick the most specific that the evidence supports; a parenthetical source is allowed):

| Value | When |
|---|---|
| `user` | A user prompt or AskUserQuestion answer names **this** choice. Cite it. |
| `plan` | The plan doc states it. Cite it. |
| `agent (implicitly approved)` | Only a vague approval covers it ("ok, do it", "go", picking a recommended option without the choice spelled out). |
| `agent-alone` | Sessions exist and nothing in them shows the user weighing in. |
| `unknown` | No session evidence at all. |

`Alternatives considered:` lists options the session, plan or PR body actually discussed, with
the reason each was dropped and its citation. PR bodies often state the rejected option as a
negative ("No BE permission change needed", "instead of caching it", "kept X rather than Y") —
those count; cite `PR body` and mark them `(PR body only)` when the session doesn't confirm them.
If nothing names an alternative, write `Alternatives considered: none recorded`.

### Behavior

A user-visible change: before → after, for which users, on which screens.

```markdown
### D-04 · Behavior · ✅ verified
Regular and anonymous users now see real stock on the product page instead of "Sold out".
Evidence: `lib/product/stock_view_model.dart:270` "_repo.stock(productId)" · session 3f9a1c2e:L1290
**Status:** pending
→ Confirm this is the intended visible change?
```

### Unchanged

One item per checklist category below. Each category resolves to exactly one of:

- **Changed** → write a Behavior (or Decision) item instead and mention the category in it.
- **Unchanged** → an `Unchanged · <Category>` item with a citation showing the current code.
- **N/A** → one FYI line: `### D-NN · Unchanged · <Category> · N/A` + one-line reason. Never skip a
  category silently: an N/A is a stated decision.

Flag an Unchanged item (→ Needs your call) when:

- the diff deleted the comment, test or doc that explained why it stays this way
  (`⚠️ rationale removed`);
- it is the mechanism behind the bug the PR fixes, or it silently swallows errors into a
  plausible-looking value (`⚠️ risky fallback kept`);
- the PR body claims it is unchanged but the agent could not confirm it (`❓ UNVERIFIED`).

```markdown
### D-06 · Unchanged · Error fallback · ✅ verified · ⚠️ risky fallback kept
Any failed stock fetch (403, offline, 5xx) still resolves to an empty entity → "Sold out".
This is the mechanism that hid the original bug. Not discussed in the plan or the session.
Evidence: `lib/product/stock_view_model.dart:275` ".catchError((_) => const Stock.empty())"
**Status:** pending
→ Keep error → sold-out fallback?
```

#### Checklist categories

1. **API contract** — endpoint, method, params, response shape.
2. **Backend permissions/auth** — per user type (anonymous, regular, admin, …).
3. **Caching and freshness** — what is cached, for how long, what invalidates it.
4. **Loading, empty and error states** — including error fallbacks and what the user sees.
5. **Persistence and migrations** — local storage, DB schema, stored-data compatibility.
6. **Navigation and deep links** — routes, arguments, back behavior, links into the screen.
7. **Platform-specific behavior** — iOS / Android / web / desktop differences.
8. **Request count and performance** — extra calls, N+1, rebuilds, startup cost.
9. **Parity with previous or legacy behavior** — what an existing user notices.
10. **Anything else outside the stated intent** — config, dependencies, analytics, copy,
    generated or built files, CI.

### Tests

What each new or changed test asserts — and what it does not.

```markdown
### D-07 · Tests · ✅ verified · needs your call
New `products_api_test.dart` asserts the request URL and response parsing only.
Not asserted: the sold-out gate (`stock_view_model.dart`) for 0 / >0 / error stock.
E2E: Pixel (Android) — session 3f9a1c2e/a1b2c3d4:L88 (mobile MCP tap + screenshot); iPhone — ❓ UNVERIFIED (PR body only).
Evidence: `test/api/products_api_test.dart:31` "expect(uri.path, endsWith('/availability'))"
**Status:** pending
→ Accept test coverage as is?
```

- Match every E2E / manual claim in the PR's "Test plan" against digest evidence: device or
  simulator MCP calls, `flutter test` / `analyze` runs with exit status, curl or staging requests.
- A claim without evidence is `❓ UNVERIFIED`, never "not run": the transcript may simply be
  missing.
- A failing run (`[exit 1]`) followed by no passing run is a finding of its own.

### Scope

Plan vs delivered, and review findings vs the PR head.

```markdown
### D-03 · Scope · ✅ verified · ⚠️ not addressed
FINDING-02 (gate untested for error stock) was accepted in triage ("Fix now") but no fix is in the PR head.
Source: session 3f9a1c2e:L2310 (AskUserQuestion answer "Fix now"); PR head has no change to `stock_view_model_test.dart`.
Evidence: session 3f9a1c2e:L2310
**Status:** pending
→ Fix before merge?
```

- Plan tasks: `done` / `partial` / `missing` / `extra` (delivered but not planned). One item per
  partial, missing or extra task; all `done` tasks share one FYI item.
- Review findings: match by content (file + what the finding asks for), not by line number.
  A finding is addressed only when the PR head contains the change; cite it. A finding the
  reviewer deferred or declined in the session is FYI with that citation.

## Ordering

"Needs your call", in this order (ids follow it; an item the citation check later downgrades
keeps its id and place):

1. `❓ UNVERIFIED` claims
2. Review findings not addressed
3. `agent-alone` and `agent (implicitly approved)` decisions
4. Behavior changes
5. Scope extras or missing items
6. Flagged Unchanged items (rationale removed, risky fallback kept)

Then **Verified FYI** (collapsed): `user`/`plan` decisions with ✅, unflagged Unchanged items, N/A
lines, done plan tasks, addressed or deferred findings.

**One claim, one item.** When a review finding and a checklist category point at the same code
(e.g. FINDING-02 "error shows sold out" and the Error-fallback Unchanged item), write one item:
keep the finding's Scope item, add the category's flag to its heading
(`⚠️ not addressed · ⚠️ risky fallback kept`), and resolve the category in FYI with one line
`### D-NN · Unchanged · <Category> · see D-MM`. Same for a Tests gap that is also an unaddressed
finding.

If "Needs your call" has more than 10 items, add one line right under its heading:
`> More than 10 calls — consider splitting this PR.`

## Re-run against a new head

When the skill passes previous Rejected / Develop items, add one `Scope` item per previous
follow-up: `Previously D-NN (<old sha7>): <claim>` → `addressed` (cite the new code) or
`not addressed` (`⚠️ not addressed`, Needs your call).
