"""Read runtime configuration without printing or persisting credentials."""

import os

from .errors import UserError

DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_TEMPERATURE = 1.0
DEFAULT_MAX_TOKENS = 4096


def load_api_key() -> str:
    """Return AI_API_KEY without surrounding whitespace, or explain its absence."""
    api_key = os.environ.get("AI_API_KEY", "").strip()
    if not api_key:
        raise UserError(
            "AI_API_KEY 환경변수가 설정되지 않았습니다. "
            "READ.md의 3.3절에 따라 같은 터미널에서 설정해 주세요."
        )
    return api_key
