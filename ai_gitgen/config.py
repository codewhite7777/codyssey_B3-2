"""명령 옵션의 기본값과 현재 터미널에서 전달받은 API Key를 제공한다.

build_parser()는 아래 기본값을 사용하고, cli.main()은 API가 필요한 경로에서만
load_api_key()를 호출한다. Git 자료 수집과 외부 인증은 이 모듈의 역할이 아니다.
Key를 파일에 저장하거나 터미널에 출력하지 않으며 .env도 자동으로 읽지 않는다.
"""

# os.environ은 이 Python 프로세스가 시작될 때 물려받은 환경변수에 접근하는 인터페이스다.
import os

# 모듈에서 사용자 안내용 오류를 발생시키면 cli.main()이 잡아 짧은 안내로 출력한다.
from .errors import UserError

# 옵션을 생략했을 때 사용할 초기값이다. 사용자가 옵션을 넣으면 그 실행에서만 덮어쓴다.
# 모델 문자열은 요청 URL에, temperature와 max_tokens는 요청 본문의 생성 설정에 들어간다.
# max_tokens는 글자 수나 반드시 생성할 분량이 아니라 생성 토큰 수의 상한이다.
DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_TEMPERATURE = 1.0
DEFAULT_MAX_TOKENS = 4096


def load_api_key() -> str:
    """현재 환경변수의 Key를 읽고, 사용할 값이 있는지 확인한다.

    입력: 함수 인자는 없고 os.environ의 AI_API_KEY를 읽는다.
    처리: 값을 가져와 앞뒤 공백을 제거하고, 남은 문자가 있는지 검사한다.
    반환: 공백을 제거한 Key 문자열. 원래 환경변수의 값은 바꾸지 않는다.
    오류: 미설정, 빈 문자열, 공백만 있는 값은 모두 UserError로 안내한다.

    Key의 유효성이나 Google 권한을 확인하는 함수는 아니다. 실제 인증은
    generate_text()의 HTTP 요청에서 처리하며, 다른 이름의 환경변수로 대체하지 않는다.
    """
    # get의 기본값 "" 덕분에 변수가 없어도 KeyError가 나지 않는다.
    # strip은 복사·붙여넣기 과정에서 값 앞뒤에 붙은 공백이나 줄바꿈을 제거한다.
    api_key = os.environ.get("AI_API_KEY", "").strip()
    if not api_key:
        # 빈 값으로 API를 호출하기 전에 중단한다. 실제 Key를 오류에 포함하지 않고
        # 사용자가 같은 터미널에서 다시 설정할 수 있도록 README의 항목을 안내한다.
        raise UserError(
            "AI_API_KEY 환경변수가 설정되지 않았습니다. "
            "README.md의 'API Key 입력' 안내에 따라 같은 터미널에서 설정해 주세요."
        )
    # 호출한 main()이 마스킹과 인증 헤더 구성에 사용하도록 값만 반환한다.
    return api_key
