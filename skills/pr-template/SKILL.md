---
name: pr-template
description: Fill the repo's PR description template from the branch's diff and return it as plain text for copy/paste. Use when asked to write a PR description or PR body, or to fill out the PR template.
---

# PR Template

Fill the PR description template from the current branch and return the finished description as plain text in the reply, for the user to copy/paste into the PR. Never write it to a file, and never create or update the PR yourself.

## The template

This block is the canonical PR description template. Format changes to PR descriptions are made by editing this block — there is no `.github/` copy.

```markdown
## Overview
*1–3 sentences describing the PR*

## What’s New
*Describe what has been newly added to the codebase in this PR. If nothing, leave blank.*

## What Has Changed
*Describe what functionality or formatting has changed (this is distinct from fixes). If nothing, leave blank.*

## What’s Fixed
*Describe bugs that have been fixed in this PR. If nothing, leave blank.*

## Testing
*Link to tests that have been added or updated to cover the changes.*

## Additional Information
*Anything else? Add it or link it here.*
```

## Filling it out

1. Review the full diff from the merge base with `main` (including uncommitted work) and the branch's commit messages.
2. Fill each section with what the diff actually does: Overview in 1–3 sentences, the rest as brief bullets.
3. The *leave blank if nothing* prompts mean drop the section entirely in the filled description — never leave an empty header.
4. Testing links point at the tests that actually cover the change; if none were added, say so.

## Output

Print the filled description as plain text in a single fenced code block with nothing else in the reply, so it copies verbatim into the PR. It ends with this attribution line, unchanged:

🤖 Generated with [Claude Code](https://claude.com/claude-code)
