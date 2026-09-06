---
name: simplify-diff-to-main
description: Review the current branch against main and repeatedly simplify its diff without changing intended behavior.
---

# Simplify Diff to Main

Use this skill when a branch's code is functionally complete and should be made as simple and maintainable as possible before merge.

## Objective

Minimize the complexity of the diff relative to the canonical base branch while preserving intended behavior.

Prioritize:

1. Correctness and behavioral equivalence.
2. Simpler logic and control flow.
3. Less duplication, state, indirection, and abstraction.
4. Fewer changed or total lines when clarity improves.
5. Lower maintenance burden.

Never sacrifice safety, validation, readability, or meaningful test behaviors to reduce line count.

## Workflow

First inspect the repository and working tree. Identify the repository's canonical base branch and review the complete branch diff from its merge base, including relevant uncommitted working-tree changes. Understand each logical change and distinguish essential behavior from incidental implementation. Determine intended behavior from the surrounding code and relevant documentation. Ask for clarification when intent is ambiguous.
Prefer deletion over rewriting and direct code over speculative abstraction.

## Iterative simplification

Make one coherent simplification at a time.

For each candidate:

1. Identify the behavior that must remain unchanged.
2. Make the simplifying edit.
3. Review the resulting diff.
4. Run the relevant validation.
5. Keep the edit only if it is clearly simpler and correct; otherwise revert it.

After every successful simplification, inspect the full diff again because the edit may expose additional removable complexity.

## Finish

Run the repository's required tests, lint, formatting, and type checks.

Report concisely:

- **What changed**
- **Why it is simpler**
- **Validation**
- **Diff impact**
- **Remaining complexity**
