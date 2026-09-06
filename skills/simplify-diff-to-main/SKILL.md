---
name: simplify-diff-to-main
description: Review the current branch against main and repeatedly simplify its diff without changing intended behavior. Continue searching until five consecutive full passes find no beneficial simplification.
---

# Simplify Diff to Main

Use this skill when a branch is functionally complete and should be made as simple, small, and maintainable as possible before merge.

## Objective

Minimize the complexity of the diff relative to `main` while preserving intended behavior.

Prioritize:

1. Correctness and behavioral equivalence.
2. Simpler logic and control flow.
3. Less duplication, state, indirection, and abstraction.
4. Fewer changed or total lines when clarity improves.
5. Lower maintenance burden.

Never sacrifice readability, type safety, validation, error handling, or meaningful test coverage merely to reduce line count.

## Workflow

First inspect the repository, working tree, and complete diff against `main`. Understand each logical change and distinguish essential behavior from incidental implementation.

Search for simplifications including:

- Code, branches, checks, variables, imports, comments, files, dependencies, or tests that can be deleted.
- One-use abstractions, forwarding wrappers, or unnecessary helpers.
- Logic already provided by existing project utilities or framework primitives.
- Duplicate or nearly identical code paths.
- Stored state that can be derived.
- Deeply nested control flow that can be flattened.
- Unnecessary parameters, flags, types, or API surface.
- Repeated test setup or overlapping assertions.
- Complexity introduced to handle situations already prevented by repository invariants.

Prefer deletion over rewriting and direct code over speculative abstraction.

## Iterative simplification

Make one coherent simplification at a time.

For each candidate:

1. Identify the behavior that must remain unchanged.
2. Make the smallest simplifying edit.
3. Review the resulting diff.
4. Run the narrowest relevant validation.
5. Keep the edit only if it is clearly simpler and correct; otherwise revert it.

After every successful simplification, inspect the full diff again because the edit may expose additional removable complexity.

## Five-failure stopping rule

Maintain a counter called `consecutive_failed_passes`, initially `0`.

A **pass** means reviewing the entire current diff specifically looking for another safe, worthwhile simplification.

- If a pass finds and applies any simplification, validate it and reset `consecutive_failed_passes` to `0`.
- If a complete pass finds no beneficial simplification, increment the counter by `1`.
- Continue until `consecutive_failed_passes == 5`.

Do not stop after the first clean pass. Each of the five failed passes must independently reconsider the full diff for deletion, consolidation, reuse, flattened logic, narrower interfaces, simpler tests, and newly dead code.

## Finish

Run the repository's required tests, lint, formatting, and type checks. Inspect `git status` and the complete final diff.

Report concisely:

- **What changed**
- **Why it is simpler**
- **Validation**
- **Diff impact**
- **Remaining complexity**
- **Stopping condition:** confirm five consecutive passes found no further worthwhile simplification.
