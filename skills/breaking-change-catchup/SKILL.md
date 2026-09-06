---
name: breaking-change-catchup
description: Check whether the current branch would break other active branches if merged into main now. If impacted branches exist, ask the user to select one, create catchup/<selected-branch> from main, and write an uncommitted catch-up plan only. Never implement, commit, or push. Abort immediately if the working tree is dirty.
---

# Breaking Change Catch-up Planner

Use this skill when the user wants to know whether the **current branch** contains changes that would make other in-progress branches fail or require adaptation if the current branch were merged into `main` now.

This skill is **planning-only**. It may inspect Git history, diffs, repository instructions, CI/test commands, and branch contents. It may create one catch-up branch and one plan file after the user selects an impacted branch. It must not implement the fix.

## Non-negotiable rules

1. **Abort immediately if the working tree is dirty.**
   - Run:
     ```bash
     git status --porcelain=v1 --untracked-files=all
     ```
   - Any output means dirty, including untracked files.
   - If dirty, report that the skill ended because a clean tree is required.
   - Do **not** stash, reset, clean, checkout files, or otherwise modify the user's work.

2. **Never commit or push.**
   - Do not run `git commit`, `git push`, `git reset --hard`, destructive checkout commands, or force operations.
   - Do not amend, rebase, or rewrite user branches.
   - Do not create tags.

3. **Do not implement code.**
   - The final catch-up branch may contain only the plan file created by this skill as an intentional uncommitted change.
   - Do not edit source, tests, configs, generated files, lockfiles, migrations, or documentation other than the catch-up plan.

4. **The user chooses the impacted branch.**
   - If one or more branches are meaningfully impacted, show the impacted branches with concise evidence and ask the user to choose exactly one.
   - Even if there is only one impacted branch, ask the user to confirm/select it rather than auto-selecting.

5. **Create the catch-up branch from `main`.**
   - For selected logical branch `<project/feature>`, create:
     ```text
     catchup/<project/feature>
     ```
   - Example:
     ```text
     project/payments-v2
     -> catchup/project/payments-v2
     ```
   - Strip a remote prefix such as `origin/` when deriving the catch-up branch name.
   - Preserve the selected branch's remaining slash structure.
   - The catch-up branch must start from `main`, not from the selected feature branch and not from the current branch.

6. **Stop after writing the plan.**
   - Leave the user checked out on `catchup/<selected-branch>`.
   - Leave the plan uncommitted.
   - Do not offer to start implementation in the same run.
   - End with a concise handoff stating the branch name and plan path.

## Dirty-tree gate semantics

The clean-tree check is mandatory:
- at skill entry; and
- again immediately before switching/creating the catch-up branch after the user selects a branch.

The **only** allowed dirty state at the end is the plan file this skill intentionally writes on the new catch-up branch. No other tracked or untracked changes may be introduced by this skill.

## Phase 1: establish repository state

After the clean-tree gate:

1. Confirm this is a Git repository.
2. Read repository-local agent instructions before analysis, including files such as:
   - `AGENTS.md`
   - `CLAUDE.md`
   - `CONTRIBUTING.md`
   - relevant README/development docs
   - CI configuration and package/build manifests when needed
3. Determine:
   - current branch name
   - `HEAD` SHA
   - `main` SHA
   - merge base of `main` and current branch
4. If in detached HEAD state, stop and explain that a named current branch is required.
5. If the current branch is `main`, report that there is no feature-branch delta to evaluate and end.
6. If `main` does not exist, stop rather than guessing another default branch.

Use the current local refs as the analysis snapshot. If repository instructions explicitly require fetching before analysis, a fetch is allowed because it does not alter the working tree; never pull, merge, or rebase user branches just to make refs fresh. Record the exact SHAs used in the final evidence/plan.

## Phase 2: identify the current branch's new changes

Analyze the current branch relative to `main` using the merge-base-aware range:

```bash
git diff --stat main...HEAD
git diff --name-status main...HEAD
git diff main...HEAD
git log --oneline --decorate main..HEAD
```

Build a compact **change contract** describing what could affect other branches. Pay special attention to:

- deleted or renamed files/modules
- public API or exported symbol changes
- function/method signature changes
- type/interface changes
- schema, migration, serialization, protocol, or event-shape changes
- CLI flags and environment/config keys
- routing or URL contract changes
- shared build-system/toolchain changes
- dependency or runtime-version changes
- generated-code/source-of-truth changes
- database assumptions
- authentication/authorization behavior
- shared test fixtures or mocks
- file moves and import-path changes
- behavior changes that invalidate assumptions in consumers

Do not label a change "breaking" merely because the same file is touched on another branch.

## Phase 3: enumerate candidate branches

Consider active branches other than:
- the current branch
- `main`
- symbolic remote `HEAD`
- `catchup/*` planning branches

Prefer branches that have commits not yet in `main`. Normalize local and remote names so a local branch and `origin/<same-name>` are not reported twice. Remote-only feature branches may be analyzed.

Useful commands include:

```bash
git for-each-ref --format='%(refname:short)' refs/heads refs/remotes
git branch --no-merged main
git branch -r --no-merged main
```

A branch that is already fully merged into `main` is normally not a catch-up candidate.

## Phase 4: determine whether each branch would break

For each candidate branch, compare its code against the current branch's change contract and gather **concrete evidence**.

Classify a branch as impacted only when at least one of these is true:

1. **Integration conflict**
   - A merge simulation shows a real content conflict in files relevant to the current change.
   - Prefer non-mutating analysis such as `git merge-tree` when available.
   - Temporary worktrees are allowed for deeper checks, but never alter the user's primary worktree.

2. **New validation failure**
   - The branch's relevant baseline build/typecheck/test succeeds by itself, but an isolated integration simulation with the current branch's changes causes it to fail.
   - Do not blame the current branch for failures that already exist on the target branch.

3. **Proven contract dependency break**
   - The current branch deletes/renames/changes a contract and the candidate branch demonstrably imports, calls, implements, serializes, configures, or otherwise depends on the old contract.
   - Cite the relevant files/symbols/commands in the evidence.

4. **Required generated/schema migration**
   - The target branch consumes a schema, generated interface, migration sequence, or protocol changed by the current branch and cannot remain valid without an explicit catch-up change.

Use repository-native checks where discoverable, for example build, typecheck, unit tests, lint, schema validation, or targeted package tests. Prefer the narrowest reliable command over an unnecessarily expensive full-suite run.

In this repository every check runs inside Docker (see `AGENTS.md` "Host policy"); never install or invoke host toolchains. Run tests from the repo root with:

```bash
docker compose up pytest --build --exit-code-from pytest
docker compose up pytest --build --exit-code-from pytest -- /firmware-packages/vl53l0x/tests
```

The second form narrows the run to one project or package — prefer it over the full suite.

### Confidence labels

For every impacted branch, attach one of:

- **Confirmed** — conflict or baseline-to-integrated validation proves breakage.
- **High confidence** — direct contract dependency proves an adaptation is required.
- **Needs review** — suspicious overlap exists, but evidence is insufficient to call it breaking.

Only **Confirmed** and **High confidence** branches belong in the user selection list by default. Put **Needs review** items in a separate note, not as proven breakages.

## Phase 5: if no branches are broken

If there are no Confirmed or High-confidence impacted branches:

- do not create a catch-up branch;
- do not create a plan file;
- summarize the evidence checked;
- state that no proven cross-branch breaking change was found in the analyzed snapshot;
- end the skill.

## Phase 6: ask the user to select one impacted branch

If one or more proven impacted branches exist, present a compact selection list containing:

- branch name
- confidence
- one-line reason
- most relevant files/contracts

Then ask:

> Which one branch should I prepare a catch-up plan for?

Do not create or switch branches until the user answers.

This branch choice is the one synchronous decision this skill requires. Implementation choices discovered later should normally be preserved as open decisions in the plan so the catch-up work can continue asynchronously.

## Phase 7: revalidate before creating the catch-up branch

After the user selects a branch:

1. Re-run:
   ```bash
   git status --porcelain=v1 --untracked-files=all
   ```
2. If there is any output, end the skill immediately. Do not stash or clean it.
3. Verify the selected branch still resolves.
4. Verify `main` still resolves.
5. Refresh the relevant SHAs in the plan evidence if they changed since Phase 1.

## Phase 8: preserve or continue catch-up decision context

Before creating the new branch, inspect any existing committed catch-up planning history without checking it out.

Look for related branches such as:

```text
catchup/*
origin/catchup/*
```

When a prior committed catch-up plan is relevant to the same shared breaking change:

- reference it as a **parent/related catch-up plan**;
- carry forward unresolved decisions that also apply to the selected branch;
- preserve decision IDs if possible;
- record any earlier user decisions as constraints, with source branch/plan references.

Because this skill must create the selected catch-up branch **from `main`**, "continue an existing chain of fixes" means continuing the **logical planning/decision chain**, not changing Git ancestry away from `main`.

If no relevant prior plan is available, make the new plan fully standalone.

Never assume an answer to an unresolved decision merely because another branch made a similar choice.

## Phase 9: create the catch-up branch

Derive the logical selected branch name:
- local `project/feature` -> `project/feature`
- remote `origin/project/feature` -> `project/feature`

Catch-up branch:
```text
catchup/project/feature
```

Create it from `main`:

```bash
git switch -c catchup/<logical-selected-branch> main
```

If that catch-up branch already exists:
- do not overwrite, delete, or force-reset it;
- inspect whether it is an existing continuation branch for the same target;
- if safe and clearly the intended branch, switch to it only if it is based on the expected `main` lineage and does not require rewriting;
- otherwise stop and explain the collision.

Do not pull, merge, rebase, or cherry-pick.

## Phase 10: write the plan only

Use the repository's established planning location if repository instructions define one. Otherwise write:

```text
CATCHUP_PLAN.md
```

The plan must be implementation-ready but contain **no code changes**.

Use this structure:

```markdown
# Catch-up Plan: <selected branch>

Status: PLAN ONLY — NOT IMPLEMENTED
Catch-up branch: catchup/<selected branch>
Base branch: main
Base SHA: <sha>
Breaking-change source branch: <original current branch>
Breaking-change source SHA: <sha>
Target branch: <selected branch/ref>
Target SHA analyzed: <sha>
Analysis snapshot date: <date>
Parent/related catch-up plan: <branch:path or none>

## Goal
Explain what must become compatible and what "caught up" means.

## Breaking-change evidence
- Changed contract/file/symbol:
- Evidence from source branch:
- Evidence from target branch:
- Integration/test evidence:
- Confidence:

## Scope
### In scope
- ...

### Out of scope
- Implementing unrelated refactors
- Opportunistic cleanup
- Any code not required for compatibility

## Constraints inherited from prior catch-up work
- Decision/constraint ID:
- Source plan:
- Recorded user choice:
- Effect on this branch:

## Open decisions
For every unresolved choice, use a durable decision record:

### D1 — <short decision title>
Status: OPEN
Why this decision is required:
Options:
1. ...
2. ...
Recommended default: ...
What changes depending on the answer:
- ...
Exact question for the user:
> <question a future agent should ask verbatim or near-verbatim>

Repeat for D2, D3, etc.

If there are no open decisions, write:
`No unresolved user decisions identified during planning.`

## Catch-up steps
1. ...
2. ...
3. ...

Each step should name likely files/modules, intended behavior, dependency order, and any prerequisite decision IDs.

## Validation plan
- Targeted build/typecheck:
- Targeted tests:
- Contract/schema validation:
- Integration check with updated main:
- Regression checks:

## Risks and rollback boundaries
- ...

## Async handoff for the next agent
1. Read this entire plan before editing code.
2. Re-check repository instructions and current `main`.
3. If any decision is `OPEN`, ask the user the recorded exact question before making code changes that depend on it.
4. Do not silently choose among unresolved options.
5. Preserve resolved decision IDs and add the user's answer to this plan or the project's normal decision record.
6. Follow the catch-up steps only after required decisions are resolved.
7. Keep this catch-up scoped to compatibility with the breaking-change source.
```

### Multiple-decision rule

When several implementation choices exist, do **not** force the user through all of them during this planning skill unless a decision is required to produce a coherent plan.

Instead:
- capture each choice in `## Open decisions`;
- give stable IDs (`D1`, `D2`, ...);
- include concrete options;
- include a recommended default when evidence supports one;
- include the exact question a future agent should ask;
- map each catch-up step to the decision IDs it depends on.

This makes the catch-up work resumable by another agent without losing required user input.

## Phase 11: final verification and stop

After writing the plan:

1. Run:
   ```bash
   git branch --show-current
   git status --porcelain=v1 --untracked-files=all
   ```
2. Confirm:
   - current branch is exactly `catchup/<selected-branch>`;
   - there are no source-code changes;
   - there are no commits created by this skill;
   - nothing was pushed;
   - the only intentional working-tree change is the catch-up plan file.

If anything else changed, report it clearly and stop without attempting destructive cleanup.

End with a handoff similar to:

```text
Prepared catchup/<selected-branch> from main.
Wrote the catch-up plan to <plan path>.
No implementation, commit, or push was performed.
Stopping here for you to take over.
```

Do not continue into implementation.
