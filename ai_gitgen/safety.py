"""Mask known secret values before text is used in an AI prompt."""

from dataclasses import replace

from .git_changes import GitChanges

MAX_FILES = 10
MAX_DIFF_LINES = 200


def redact(text: str, secret: str) -> str:
    """Replace exact secret matches, preserving text when secret is empty."""
    if not secret:
        return text
    return text.replace(secret, "[REDACTED]")


def redact_changes(changes: GitChanges, secret: str) -> GitChanges:
    """Return a masked analysis copy after all Git reads have finished."""
    return replace(
        changes,
        branch=redact(changes.branch, secret),
        files=tuple(
            replace(
                item,
                path=redact(item.path, secret),
                old_path=(
                    None if item.old_path is None else redact(item.old_path, secret)
                ),
                staged_diff=redact(item.staged_diff, secret),
                unstaged_diff=redact(item.unstaged_diff, secret),
            )
            for item in changes.files
        ),
    )


def limit_changes(changes: GitChanges) -> GitChanges:
    """Keep up to 10 files and 200 total diff lines for safe-mode input."""
    selected = []
    remaining = MAX_DIFF_LINES
    for item in changes.tracked_files:
        if len(selected) >= MAX_FILES or remaining == 0:
            break
        staged = item.staged_diff.splitlines(keepends=True)[:remaining]
        remaining -= len(staged)
        unstaged = item.unstaged_diff.splitlines(keepends=True)[:remaining]
        remaining -= len(unstaged)
        if staged or unstaged:
            selected.append(replace(
                item,
                staged_diff="".join(staged),
                unstaged_diff="".join(unstaged),
            ))
    return replace(changes, files=tuple(selected))
