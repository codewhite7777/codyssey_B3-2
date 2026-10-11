"""Validate generated commit fields and format terminal output locally."""

import json

from .errors import UserError
from .safety import redact


def format_commit(text: str, secret: str = "") -> tuple[str, bool]:
    """Return the formatted draft and whether its title was adjusted."""
    try:
        draft = json.loads(text)
    except json.JSONDecodeError as error:
        raise UserError("AI가 생성한 커밋 결과를 JSON으로 읽을 수 없습니다.") from error
    if not isinstance(draft, dict):
        raise UserError("커밋 결과는 summary와 title을 가진 JSON 객체여야 합니다.")
    original_title = draft.get("title")
    summary = draft.get("summary")
    if not isinstance(original_title, str) or not original_title.strip():
        raise UserError("커밋 제목(title)은 비어 있지 않은 문자열이어야 합니다.")
    if not isinstance(summary, list) or not summary or any(
        not isinstance(item, str) or not item.strip() for item in summary
    ):
        raise UserError("변경 요약(summary)은 비어 있지 않은 문자열 목록이어야 합니다.")

    # Decode JSON escapes before masking, then enforce the title length.
    masked_title = redact(original_title, secret)
    title = " ".join(masked_title.split())
    if len(title) > 72:
        title = title[:71].rstrip() + "…"
    lines = ["--- Change Summary ---"]
    lines.extend("- " + " ".join(redact(item, secret).split()) for item in summary)
    lines.extend(["", "--- Commit Message ---", title, "----------------------"])
    return "\n".join(lines), title != masked_title
