"""CLI 기본 설정과 환경변수 API Key를 제공한다.

키를 읽는 역할을 Git 수집·HTTP 통신과 분리하며, 파일에 저장하거나 출력하지 않는다.
"""

import os

from .errors import UserError

# 옵션을 생략했을 때 사용하는 값이다. max_tokens는 글자 수가 아닌 토큰 상한이다.
DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_TEMPERATURE = 1.0
DEFAULT_MAX_TOKENS = 4096


def load_api_key() -> str:
    """AI_API_KEY의 앞뒤 공백을 제거해 반환하고, 값이 없으면 UserError를 낸다.

    실행한 터미널에서 물려받은 환경변수만 읽는다. .env 파일을 읽거나
    Google에 인증하는 함수는 아니며, 실제 인증은 이후 API 요청에서 확인된다.
    """
    # 미설정·빈 문자열·공백만 있는 값을 같은 누락 오류로 처리한다.
    api_key = os.environ.get("AI_API_KEY", "").strip()
    if not api_key:
        raise UserError(
            "AI_API_KEY 환경변수가 설정되지 않았습니다. "
            "README.md의 'API Key 입력' 안내에 따라 같은 터미널에서 설정해 주세요."
        )
    return api_key
