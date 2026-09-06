---
name: simplify-diff-to-main
description: Review the current branch against main, understand every change, then iteratively simplify the patch by reducing line count, logic, duplication, and unnecessary abstractions without changing intended behavior.
---

# Simplify Diff to Main

Use this skill when a branch is functionally complete and just needs to be simplified before merge to main.

## Objective

Minimize the complexity and size of the branch's diff relative to `main` while preserving intended behavior.

Optimize for, in order:

1. Correctness.
2. Behavioral equivalence with the intended branch changes.
3. Simpler logic and control flow.
4. Fewer lines changed and fewer total lines where that improves clarity.
5. Less duplication and fewer unnecessary abstractions.
6. Lower maintenance burden.

Do not optimize for line count at the expense of readability, correctness, type safety, useful tests, or clear error handling.

## Core workflow

### 1. Establish the baseline

Start by understanding the repository and the branch before editing anything.

If `main` branch is unavailable locally, use the repository's actual default branch or the appropriate remote tracking branch.

Inspect any uncommitted changes separately.

Do not accidentally mix unrelated pre-existing working-tree changes into the simplification work.

### 2. Build a change map

Before modifying code, summarize the diff by logical change rather than only by file.

For each logical change, identify:

- What behavior was added, removed, or changed.
- Which files participate in that behavior.
- Whether the implementation introduces new helpers, branches, state, types, dependencies, tests, or configuration.
- What appears essential versus incidental.
- Where multiple edits solve the same problem in different ways.
- Where the patch duplicates behavior already present on `main`.

Pay special attention to:

- New abstractions used once.
- Wrapper functions that only forward arguments.
- Helpers that duplicate standard-library or existing project utilities.
- Parallel code paths that can be unified.
- Defensive checks made redundant by upstream invariants.
- Temporary compatibility logic that is no longer necessary.
- Repeated transformations, parsing, validation, or error handling.
- New state that can be derived instead of stored.
- Comments that explain complexity that can instead be removed.
- Tests that overlap heavily or assert implementation details rather than behavior.

### 3. Work iteratively, one simplification at a time

Do not rewrite the entire patch in one pass.

For each candidate simplification:

1. State the intended behavior being preserved.
2. Identify the unnecessary complexity.
3. Make the smallest coherent edit that removes it.
4. Review the resulting diff.
5. Run the narrowest relevant validation.
6. Keep the edit only if the result is clearly simpler and still correct.

Prefer a sequence of small reductions over a large refactor.

After each meaningful edit, inspect:

```bash
git diff --stat main...HEAD
git diff main...HEAD -- <affected paths>
```

When uncommitted edits are being evaluated, also inspect plain `git diff` so the current simplification is visible independently of the committed branch diff.

### 4. Simplification heuristics

Apply these heuristics aggressively but safely.

#### Delete before rewriting

Ask whether code can be removed entirely before trying to improve it.

Examples:

- Remove dead branches.
- Remove unnecessary adapters.
- Remove redundant conditionals.
- Remove duplicated tests.
- Remove variables that merely rename expressions.
- Remove configuration that duplicates defaults.
- Remove comments made obsolete by simpler code.

#### Reuse existing project behavior

Search the codebase before adding or keeping a new helper.

Prefer:

- Existing utilities.
- Existing conventions.
- Existing types.
- Existing validation paths.
- Existing error handling.
- Existing framework primitives.

Do not keep branch-local abstractions when the repository already has an adequate equivalent.

#### Collapse duplicate paths

If two branches differ only slightly, look for a shared expression or a single normalized path.

Prefer data-driven differences over duplicated control flow when that is clearer.

#### Derive instead of synchronize

Avoid storing values that can be cheaply and reliably derived from existing state.

Remove synchronization code when a single source of truth is sufficient.

#### Prefer direct code over speculative abstraction

A small amount of straightforward duplication can be better than an abstraction that obscures behavior, but true repeated logic should still be consolidated when the shared concept is stable and obvious.

Do not create abstractions for hypothetical future use.

#### Flatten control flow

Prefer:

- Early returns over deep nesting.
- Guard clauses over multi-level conditionals.
- Straight-line transformations over mutable state machines when behavior permits.
- Built-in collection operations when they make intent clearer.

Avoid clever compression that makes debugging harder.

#### Tighten interfaces

If the diff expanded an API surface unnecessarily:

- Remove unused parameters.
- Narrow return types.
- Avoid exposing helpers that only need local scope.
- Avoid passing data that can be obtained at the point of use.
- Remove option flags that represent only one real behavior.

#### Simplify types without weakening them

Remove duplicate or mechanically-derived types when existing project types can express the same contract.

Do not replace useful static guarantees with `any`, broad casts, unchecked dictionaries, or equivalent escape hatches merely to reduce lines.

#### Simplify tests while preserving coverage

Tests are part of the diff and should be simplified too.

Look for:

- Repeated setup that can use existing fixtures.
- Multiple tests that can be expressed as a small parameterized table.
- Assertions that duplicate one another.
- Tests of private implementation details that can become behavior-level tests.
- Tests for cases already guaranteed by a lower-level well-tested primitive.

Do not delete meaningful regression coverage merely to shrink the diff.

### 5. Validate continuously

Use repository-native validation commands discovered from project files and documentation.

Prefer the fastest relevant checks during iteration, then run the broader required suite before finishing.

Typical validation includes some combination of:

```bash
# examples only; use the repository's real commands
npm test
npm run lint
npm run typecheck
pytest
cargo test
go test ./...
```

Also run formatting or static analysis if the project requires it.

If a simplification changes externally observable behavior, revert it unless that behavior change is clearly part of the branch's intended purpose.

### 6. Re-read the entire diff after local simplifications

Once individual edits are complete, review the full diff again from top to bottom.

Ask:

- Can any newly-adjacent changes now be combined?
- Did simplifying one area make another helper unnecessary?
- Are there imports, types, tests, comments, flags, or files that are now dead?
- Does the branch still contain two ways to accomplish the same thing?
- Is every new line carrying its weight?
- Does the final code look like the simplest implementation someone would write if starting from the requirements today?

Repeat the simplify → validate → review loop until another pass finds no clearly beneficial reduction.

## Decision rules

Keep a simplification when it:

- Preserves intended behavior.
- Reduces cognitive load.
- Removes duplication or indirection.
- Reduces the amount of code that must be maintained.
- Aligns the change more closely with existing repository patterns.
- Makes the diff easier to review.

Reject or revert a simplification when it:

- Makes behavior less explicit in a risky area.
- Introduces cleverness for the sake of fewer lines.
- Weakens tests or types materially.
- Changes public behavior that the branch did not intend to change.
- Replaces readable code with dense expressions merely to reduce line count.

## Scope discipline

The target is the delta from `main`, not a general repository cleanup.

You may simplify nearby existing code only when doing so directly eliminates complexity introduced or exposed by the branch and keeps the patch easier to understand.

Do not opportunistically refactor unrelated modules.

Do not modify generated files unless the source-of-truth change requires regeneration.

Do not remove compatibility, migration, security, validation, or error-handling code unless you have verified it is redundant under the repository's actual invariants.

Use reduced lines as a signal, not a score. A smaller diff is desirable only when the implementation is readable and correct.

## Final review

Before finishing:

1. Run the repository's required tests, type checks, lint, and formatting checks.
2. Inspect `git status` and confirm no unrelated files were modified.
3. Inspect the complete diff against `main` one final time.
4. Remove newly-unused imports, helpers, variables, comments, tests, files, and dependencies.
5. Confirm the resulting patch still fully implements the branch's intended behavior.

## Final response format

Report:

- **What changed:** the major simplifications made.
- **Why it is simpler:** removed branches, helpers, state, duplication, abstractions, or lines.
- **Validation:** commands run and their results.
- **Diff impact:** before/after line counts from `git diff --numstat` or equivalent when available.
- **Remaining complexity:** anything that looked removable but was intentionally kept, with a short reason.

Keep the report concise.