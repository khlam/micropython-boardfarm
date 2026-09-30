---
name: pr-template
description: Use when the user asks for a PR description. Fill the repo's PR description template from the branch's diff and return it as plain text for copy/paste.
---

# PR Template

Fill the PR description template from the current branch and return the finished description as plain text in the reply.

## The template

```markdown
## Overview
- maximum 3 sentences describing the PR

## What’s New
- List what has been newly added to the codebase in this PR. If nothing, leave blank. Maximum 3 sentences each bulletpoint.

## What Has Changed
- List what functionality or formatting has changed (this is distinct from fixes). If nothing, leave blank. Maximum 3 sentences each bulletpoint.

## What’s Fixed
- List bugs that have been fixed in this PR. If nothing, leave blank. Maximum 3 sentences each bulletpoint.

## Testing
- Create a concise table-driven test summary with columns:

| # | Name | Input | Expected Output |

Requirements:
- Test Name must link directly to the test implementation(s).
- Use propositional/set logic notation in Input and Expected Output to communicate test intent
- Express contracts, ranges, boundaries, nullability, collections, and alternatives compactly (e.g., `x ∈ [1,100]`, `x < 1`, `x = null`, `A ∨ B`, `x ≠ ∅`, `P ⇒ Q`).
- Define all variables after the table.

## Additional Information
*List any other additional information*
```