"""Mask known secret values before text is used in an AI prompt."""

from dataclasses import replace

from .git_changes import GitChanges


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
