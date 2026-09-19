---
name: new-skill
description: How SKILL.md and AGENTS.md files are authored in this repo — user-prompted only, 600 words maximum, canonical under skills/, linked into both agent trees by script. Use before creating, editing, renaming, or deleting any skill or AGENTS.md file.
---

# Authoring skills and AGENTS.md

## Never write one unprompted

`SKILL.md` and `AGENTS.md` files are created, edited, renamed, and deleted **only when
the user explicitly asks for it**. If one seems warranted, suggest it and wait for an
answer.

## 600 words maximum

Every `SKILL.md` and `AGENTS.md` file stays at or below 600 words, frontmatter
included, as counted by `wc -w`. CI enforces this in the "Repo guards" job.

## Linking

The one canonical copy lives at `skills/<name>/SKILL.md`, kebab-case, matching the
frontmatter `name`.

After adding, renaming, or removing a skill, run `make skills` and commit the symlinks
it produces. It links each skill into `.claude/skills/` (Claude Code) and
`.agents/skills/` (Codex); a skill missing from either is invisible to that agent. Never
write those symlinks by hand.
