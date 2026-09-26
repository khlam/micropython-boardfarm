---
name: tidy-pr
description: Rewrite a branch's PR description into the repo's PR template and its commits into a readable history of atomic commits. Confirm with the user before force-pushing.
disable-model-invocation: true
argument-hint: "[branch]"
---

# Tidy a PR

Run only when the user invokes this skill by name. The branch is the argument, or the
current branch if none is given. The rewrite changes history, never content.

## 1. Prepare

- Require a clean working tree; stop and ask otherwise.
- Read the current PR title, body, URL, base branch, head branch, and head repository:
  `gh pr view <branch> --json title,body,url,baseRefName,headRefName,headRepository`
  when `gh` is on the host, otherwise ask the user to paste the body and identify the
  PR's base branch and head remote.
- Resolve the remote containing the PR head branch and the remote containing the PR
  base branch. Do not assume either is `origin`. If either cannot be resolved
  unambiguously, stop and ask.
- Fetch both remotes, check out the branch, and record the SHAs of its tip as `OLD` and
  of the fetched remote head branch as `REMOTE`. If `REMOTE` is not an ancestor of
  `OLD`, stop and ask.
- Back it up: `git branch backup/<branch>-<YYYYMMDD> OLD`.
- `BASE` is `git merge-base <base-remote>/<base-branch> HEAD`. Do not rebase onto newer
  `<base-branch>` unless asked. If `BASE..OLD` contains work already on the base branch
  (e.g. a squash-merged parent branch), or commits by other authors, stop and ask.
- Read the full `BASE..OLD` diff and the existing commit messages.

## 2. Rewrite history

1. Plan atomic commits: each holds one logical change and leaves the tree working
   without any later commit. Put dependencies first (a package before the project
   using it). Fold fix-ups, reverts, and review-feedback commits into the change they
   amend. Fewer is better.
2. `git reset BASE` to leave every change unstaged.
3. Stage each commit with `git add <paths>`. To split one file's hunks across commits,
   stage a trimmed patch from the scratchpad with `git apply --cached`. Before every
   commit, inspect `git diff --cached` and confirm it contains only that logical change.
   Inspect `git diff` as needed to understand what remains unstaged.
4. Match the repo's message style: an imperative sentence ending in a period, at most
   about 72 characters (e.g. "Check merged image size only once, before flashing.").
   Add a body only to explain *why* when the subject cannot. Carry over
   `Co-Authored-By` trailers from the commits each one absorbs.
5. Confirm `git diff OLD HEAD` is empty and
   `git rev-parse OLD^{tree}` equals `git rev-parse HEAD^{tree}`. Also confirm the
   working tree and index are clean. If any check fails, fix it or restart from
   `git reset --hard OLD`.

## 3. Rewrite the PR description

Fill the template below from the final diff, not from the old commit messages. Write
for a reviewer who has not seen the branch: plain language, concrete module and file
names, no process narration ("simplified", "addressed review"). Keep links, images,
and hardware notes from the old body that the diff cannot supply. Replace each italic
prompt with content, or leave the section empty. Link files with permalinks,
``[`path/to/file`](https://github.com/<owner>/<repo>/blob/<new HEAD SHA>/path/to/file)``;
relative paths do not resolve in PR bodies. Write the PR title in the commit-subject
style.

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

## 4. Publish

Show the user `git log --oneline BASE..HEAD` and the new PR title and body, then wait
for approval.

- `git push --force-with-lease=<branch>:REMOTE origin <branch>`
- With `gh` on the host: `gh pr edit <branch> --title <title> --body-file <file>`.
  Never install `gh`; without it, print the title and body for the user to paste.

Report the backup branch name. Delete it only when the user asks.