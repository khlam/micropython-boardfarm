---
name: pr-template
description: Use when the user asks for a PR description. Fill the repo's PR description template from the branch's diff and return it as plain text for copy/paste.
---

# PR Template

Fill the PR description template from the current branch and return the finished description as plain text in the reply.

## Audience

Write for a reviewer who has never seen the code. Describe what the device, tool, or workflow now does differently, not which functions moved. Follow the `talking-to-a-user` skill.

## The template

```markdown
## Overview
- maximum 3 sentences describing the PR in terms of behaviour and process

## What’s New
- List what has been newly added to the codebase in this PR. If nothing, leave blank. Maximum 3 sentences each bulletpoint. Lead each bullet with a bold plain-English summary. Use a table when a feature maps states to outcomes.

## What Has Changed
- Use a Before/Now table for changed functionality or formatting (this is distinct from fixes). If nothing, leave blank.

| Area | Before | Now |

- Add a Mermaid diagram when a multi-step process changes, showing Before and Now side by side.
- Use bullets for changes that have no clear Before, such as docs or skills.

## What’s Fixed
- Use a Before/Now table for bugs fixed in this PR. If nothing, leave blank.

| Bug | Before | Now |

## Testing
- Create a concise table-driven test summary with columns:

| # | Name | Input | Expected Output |

Requirements:
- Test Name must link directly to the test implementation(s).
- Use propositional/set logic notation in Input and Expected Output to communicate test intent
- Express contracts, ranges, boundaries, nullability, collections, and alternatives compactly (e.g., `x ∈ [1,100]`, `x < 1`, `x = null`, `A ∨ B`, `x ≠ ∅`, `P ⇒ Q`).
- Define all variables after the table.

## Additional Information
*List any other additional information: breaking API changes, removed or moved files, version bumps, and how to run the tests.*
```

## Rules

- Keep each table cell to one or two short sentences.
- Never use the words "After" or "Previously"; use "Before" and "Now".
