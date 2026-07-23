#!/usr/bin/env bash
# scripts/sync_skill.sh — sync knowledge-qa skill files from live → repo
#
# Run this whenever you edit ~/.bob/skills/knowledge-qa/ (ingest.py,
# network_audit.py, or SKILL.md) so the repo stays in sync and fresh
# cloners get your latest security enhancements via setup.py.
#
# Usage:
#   bash scripts/sync_skill.sh              # copy + show diff, no commit
#   bash scripts/sync_skill.sh --commit     # copy + auto-commit to git
#   bash scripts/sync_skill.sh --help

set -euo pipefail

# ── Resolve repo root (script lives in scripts/) ─────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SRC_DIR="$HOME/.bob/skills/knowledge-qa"
DEST_DIR="$REPO_ROOT/skills/knowledge-qa"

FILES=(ingest.py network_audit.py SKILL.md)

# ── Helpers ───────────────────────────────────────────────────────────────────
green()  { printf "\033[32m  ✓ %s\033[0m\n" "$*"; }
yellow() { printf "\033[33m  ⚠ %s\033[0m\n" "$*"; }
red()    { printf "\033[31m  ✗ %s\033[0m\n" "$*"; }
info()   { printf "\033[36m  → %s\033[0m\n" "$*"; }
bold()   { printf "\033[1m%s\033[0m\n" "$*"; }

usage() {
  cat <<EOF
Usage: bash scripts/sync_skill.sh [--commit] [--help]

  (no flag)   Copy changed files from ~/.bob/skills/knowledge-qa/ into
              skills/knowledge-qa/ and show a git diff. Does NOT commit.

  --commit    Copy + stage + commit with an auto-generated message.
              Exits with code 0 and prints "Nothing to sync" if no files changed.

  --help      Show this message.
EOF
}

# ── Argument parsing ──────────────────────────────────────────────────────────
DO_COMMIT=false
for arg in "$@"; do
  case "$arg" in
    --commit) DO_COMMIT=true ;;
    --help|-h) usage; exit 0 ;;
    *) red "Unknown argument: $arg"; usage; exit 1 ;;
  esac
done

# ── Pre-flight checks ─────────────────────────────────────────────────────────
bold ""
bold "KnowledgeBase Agent — sync knowledge-qa skill files"
bold "════════════════════════════════════════════════════"

if [[ ! -d "$SRC_DIR" ]]; then
  red "Source directory not found: $SRC_DIR"
  red "Nothing to sync — have you set up the knowledge-qa skill yet?"
  exit 1
fi

if [[ ! -d "$DEST_DIR" ]]; then
  yellow "Destination directory missing — creating: $DEST_DIR"
  mkdir -p "$DEST_DIR"
fi

# Confirm we are inside a git repo
if ! git -C "$REPO_ROOT" rev-parse --git-dir &>/dev/null; then
  red "Not a git repository: $REPO_ROOT"
  exit 1
fi

# ── Copy files ────────────────────────────────────────────────────────────────
info "Source : $SRC_DIR"
info "Dest   : $DEST_DIR"
echo ""

CHANGED=()
MISSING=()

for f in "${FILES[@]}"; do
  src="$SRC_DIR/$f"
  dest="$DEST_DIR/$f"

  if [[ ! -f "$src" ]]; then
    yellow "Not found in source, skipping: $f"
    MISSING+=("$f")
    continue
  fi

  if [[ -f "$dest" ]] && cmp -s "$src" "$dest"; then
    green "$f  (unchanged)"
  else
    cp "$src" "$dest"
    green "$f  (updated)"
    CHANGED+=("$f")
  fi
done

# ── Report ────────────────────────────────────────────────────────────────────
echo ""
if [[ ${#MISSING[@]} -gt 0 ]]; then
  yellow "Skipped (not in source): ${MISSING[*]}"
fi

if [[ ${#CHANGED[@]} -eq 0 ]]; then
  info "Nothing to sync — all files already up to date."
  exit 0
fi

info "Changed: ${CHANGED[*]}"

# ── Git diff (always shown when files changed) ────────────────────────────────
echo ""
info "Git diff (skills/knowledge-qa/):"
git -C "$REPO_ROOT" diff -- skills/knowledge-qa/ || true

# ── Commit ────────────────────────────────────────────────────────────────────
if [[ "$DO_COMMIT" == true ]]; then
  echo ""
  git -C "$REPO_ROOT" add "$DEST_DIR"

  # Build a commit message listing which files changed
  FILES_LINE=$(IFS=", "; echo "${CHANGED[*]}")
  git -C "$REPO_ROOT" commit -m "chore: sync knowledge-qa skill files from live

Updated: $FILES_LINE

Synced from ~/.bob/skills/knowledge-qa/ using scripts/sync_skill.sh." || {
    yellow "git commit reported nothing to commit (files may already be staged)."
    exit 0
  }
  green "Committed."
  info  "Run: git push knowledgebase-agent main"
else
  echo ""
  info "To stage and commit, run:"
  info "  bash scripts/sync_skill.sh --commit"
  info "  git push knowledgebase-agent main"
fi
