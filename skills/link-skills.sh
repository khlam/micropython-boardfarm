#!/usr/bin/env bash
# Keep the two agent skill trees in sync with skills/, and enforce the
# 600-word cap on SKILL.md / AGENTS.md.
#
# A skill lives once at skills/<name>/SKILL.md and is linked into the directory
# each agent scans — .claude/skills (Claude Code) and .agents/skills (Codex) —
# because a skill missing from either is silently invisible to that agent.
#
#   link-skills.sh           sync links, print a summary
#   link-skills.sh --check   verify links + word cap, change nothing, exit 1 on drift
#
# --check is the CI guard (.github/workflows/ci.yml, "Repo guards" job).

set -euo pipefail

readonly MAX_WORDS=600
readonly TREES=(.claude/skills .agents/skills)

case "${1-}" in
  --check) check=1 ;;
  "") check=0 ;;
  *)
    echo "usage: ${0##*/} [--check]" >&2
    exit 2
    ;;
esac

cd "$(git rev-parse --show-toplevel)"

violations=0

# Report a problem. In --check these are GitHub annotations that fail the run;
# when syncing they are the cases the script will not fix on its own.
fail() {
  echo "::error::$1" >&2
  violations=1
}

skills=()
for dir in skills/*; do
  [[ -f "$dir/SKILL.md" ]] || continue
  skills+=("${dir##*/}")
done

if ((${#skills[@]} == 0)); then
  fail "no skills found under skills/ — expected at least one skills/<name>/SKILL.md"
  exit 1
fi

for tree in "${TREES[@]}"; do
  for name in "${skills[@]}"; do
    link="$tree/$name"
    want="../../skills/$name"

    [[ "$(readlink "$link" 2>/dev/null)" == "$want" ]] && continue

    if [[ -e "$link" && ! -L "$link" ]]; then
      # A real file or directory is never touched — it may be hand-authored.
      fail "$link exists but is not a symlink — remove it by hand, then rerun"
    elif ((check)); then
      fail "$link should be a symlink to '$want' (run 'make skills')"
    else
      mkdir -p "$tree"
      ln -sfn "$want" "$link"
      echo "  + $link"
    fi
  done

  # Prune the links a renamed or deleted skill left behind. Only broken
  # symlinks into skills/ qualify; anything else is left alone.
  for link in "$tree"/*; do
    [[ -L "$link" && ! -e "$link" && "$(readlink "$link")" == ../../skills/* ]] || continue

    if ((check)); then
      fail "$link is a broken link into skills/ (run 'make skills')"
      continue
    fi
    rm "$link"
    echo "  - $link (stale)"
  done
done

# SKILL.md comes from the filesystem, so a skill that is not staged yet is
# still capped; AGENTS.md comes from git, which is nesting-agnostic.
while IFS= read -r file; do
  words=$(($(wc -w <"$file")))
  if ((words > MAX_WORDS)); then
    fail "$file is $words words, over the $MAX_WORDS-word cap"
  fi
done < <(printf '%s\n' skills/*/SKILL.md; git ls-files '*AGENTS.md')

if ((violations)); then
  echo "skills: unresolved problems above." >&2
  exit 1
fi

echo "skills: ${#skills[@]} skills linked in ${#TREES[@]} trees, all within the $MAX_WORDS-word cap."
