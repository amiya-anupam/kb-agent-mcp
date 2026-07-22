#!/usr/bin/env python3
"""
update_changelog.py
-------------------
Reads the last 3 commits from git log and rewrites the
## Changelog section in README.md between the two sentinel comments:

    <!-- CHANGELOG_START -->
    ...dynamic content...
    <!-- CHANGELOG_END -->

Run manually:
    python3 scripts/update_changelog.py

Or let the GitHub Actions workflow call it automatically on every push.
"""

import subprocess
import sys
import textwrap

README = "README.md"
START_MARKER = "<!-- CHANGELOG_START -->"
END_MARKER = "<!-- CHANGELOG_END -->"
NUM_COMMITS = 3

# Exclude commits that are the auto-changelog update itself
SKIP_PATTERNS = ["chore: update changelog", "auto: update changelog"]


def git_log(n: int) -> list[dict]:
    """Return up to `n` commits as dicts with keys: hash, subject, body."""
    # %x00 separates fields; %x01 separates records
    fmt = "%H%x00%s%x00%b%x01"
    raw = subprocess.check_output(
        ["git", "log", f"-{n * 3}", f"--format={fmt}"],  # fetch extra to allow skipping
        text=True,
    )
    commits = []
    for record in raw.split("\x01"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x00", 2)
        if len(parts) < 2:
            continue
        full_hash, subject, *rest = parts
        body = rest[0].strip() if rest else ""
        short_hash = full_hash[:7]
        # Skip the auto-update commits so they don't pollute the log
        if any(subject.startswith(p) for p in SKIP_PATTERNS):
            continue
        commits.append({"hash": short_hash, "subject": subject, "body": body})
        if len(commits) == n:
            break
    return commits


def format_entry(commit: dict, index: int) -> str:
    """Format a single changelog entry from a commit dict."""
    label = "_(latest)_" if index == 0 else ""
    heading = f"### `{commit['hash']}` — {commit['subject']} {label}".rstrip()

    lines = [heading, ""]

    if commit["body"]:
        # Wrap long body lines at 100 chars; preserve blank lines as paragraph breaks
        paragraphs = commit["body"].split("\n\n")
        for para in paragraphs:
            wrapped = textwrap.fill(para.replace("\n", " "), width=100)
            lines.append(wrapped)
            lines.append("")
    else:
        lines.append("_No description provided._")
        lines.append("")

    return "\n".join(lines)


def build_changelog_block(commits: list[dict]) -> str:
    """Build the full replacement block (excluding the sentinel lines)."""
    parts = []
    for i, commit in enumerate(commits):
        parts.append("---\n")
        parts.append(format_entry(commit, i))
    return "\n".join(parts)


def update_readme(new_block: str) -> None:
    with open(README, "r", encoding="utf-8") as f:
        content = f.read()

    start_idx = content.find(START_MARKER)
    end_idx = content.find(END_MARKER)

    if start_idx == -1 or end_idx == -1:
        print("ERROR: sentinel comments not found in README.md", file=sys.stderr)
        sys.exit(1)

    # Keep everything before start sentinel (inclusive) and after end sentinel (inclusive)
    before = content[: start_idx + len(START_MARKER)]
    after = content[end_idx:]

    updated = before + "\n" + new_block + "\n" + after

    with open(README, "w", encoding="utf-8") as f:
        f.write(updated)

    print(f"README.md changelog section updated with {NUM_COMMITS} most recent commits.")


if __name__ == "__main__":
    commits = git_log(NUM_COMMITS)
    if not commits:
        print("No commits found — nothing to do.", file=sys.stderr)
        sys.exit(0)
    block = build_changelog_block(commits)
    update_readme(block)
