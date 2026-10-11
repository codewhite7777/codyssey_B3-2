"""사용자 명령을 읽고 Git 수집 → 안전 처리 → Gemini 요청 → 출력을 연결한다.

main()을 위에서 아래로 읽으면 실행 순서를 볼 수 있다. 세부 처리는 각 모듈에
맡기고, 이 파일에서 로그·조기 종료·오류 표시·API 요청 횟수를 관리한다.
"""

import argparse
import json
import re
import sys

from .api_client import generate_text
from .config import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, DEFAULT_TEMPERATURE, load_api_key
from .errors import UserError
from .formatting import format_commit, format_pr
from .git_changes import collect_changes
from .prompts import COMMIT_SYSTEM_INSTRUCTION, PR_SYSTEM_INSTRUCTION, build_change_prompt
from .safety import MAX_DIFF_LINES, MAX_FILES, limit_changes, redact, redact_changes


def _model_name(value: str) -> str:
    """모델 문자열이 허용한 단일 이름인지 검사해 반환하고, 아니면 옵션 오류를 낸다."""
    # 영문·숫자로 시작하고 이후에는 점·밑줄·하이픈도 허용한다. 경로(/)는 받지 않는다.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise argparse.ArgumentTypeError("모델은 영문·숫자·점·밑줄·하이픈의 단일 이름으로 입력해 주세요.")
    return value


def _temperature(value: str) -> float:
    """문자열을 0~2의 실수로 바꾸고, 숫자가 아니거나 범위를 벗어나면 옵션 오류를 낸다."""
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("temperature는 0~2 사이의 숫자여야 합니다.") from error
    # 범위 비교로 음수·초과값뿐 아니라 무한대와 NaN도 거부한다.
    if not 0 <= number <= 2:
        raise argparse.ArgumentTypeError("temperature는 유한한 0~2 사이의 값이어야 합니다.")
    return number


def _positive_int(value: str) -> int:
    """max-tokens 문자열을 양의 정수로 바꾸고, 변환 실패·0·음수를 옵션 오류로 알린다."""
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("max-tokens는 양의 정수여야 합니다.") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("max-tokens는 양의 정수여야 합니다.")
    return number


def build_parser() -> argparse.ArgumentParser:
    """명령·선택 옵션·기본값·입력 검사를 등록한 argparse 파서를 반환한다.

    여기서는 입력 규칙만 정의한다. 실제 해석은 main()의 parse_args()가 수행한다.
    """
    parser = argparse.ArgumentParser(
        description="Git 변경 사항으로 커밋 메시지와 PR 초안 생성",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # inspect는 Git 수집 확인용이고, commit/pr는 Gemini로 각각의 초안을 생성한다.
    parser.add_argument("command", choices=("inspect", "commit", "pr"))
    parser.add_argument(
        "--safe-mode", action="store_true",  # 값을 받지 않고 지정 여부를 True/False로 저장한다.
        help="commit/pr 입력을 최대 10개 파일·합계 200줄의 diff로 제한",
    )
    # 생성 옵션은 생략하면 기본값을 쓰며, type 함수가 API 요청 전에 입력을 검증한다.
    parser.add_argument(
        "--model", "-model", type=_model_name,
        default=DEFAULT_MODEL, help="Gemini 모델 이름",
    )
    parser.add_argument(
        "--temperature", "-temperature", type=_temperature,
        default=DEFAULT_TEMPERATURE, help="표현의 변동성 (0~2)",
    )
    parser.add_argument(
        "--max-tokens", "-max-tokens", type=_positive_int,
        default=DEFAULT_MAX_TOKENS, help="생성 토큰 수 상한",
    )
    parser.add_argument("--context", default="", help="변경 이유·요구사항")
    return parser


def main(argv: list[str] | None = None) -> int:
    """명령 한 번의 전체 흐름을 실행하고 정상 종료 0 또는 처리 오류 1을 반환한다.

    argv가 None이면 터미널 인자를 읽고, 테스트에서는 문자열 목록을 직접 받는다.
    변경 없음·새 파일만 존재·inspect는 생성 없이 정상 종료할 수 있다.
    commit/pr에 추적 파일이 있으면 키를 읽고, 전송할 diff가 있을 때 API를 한 번 시도한다.
    잘못된 CLI 옵션은 try 진입 전 argparse가 사용법을 표시하며 종료 코드 2로 끝낸다.
    """
    # 1. 옵션을 해석한다. API 횟수는 성공 횟수가 아니라 요청을 시도한 횟수다.
    arguments = build_parser().parse_args(argv)
    api_key = ""
    api_calls = 0
    try:
        # 2. 현재 루트의 상태·diff를 수집한다. 변경이 없으면 키도 읽지 않고 끝낸다.
        changes = collect_changes()
        if not changes.files:
            print("[INFO] 변경 사항이 없습니다.")
            return 0
        if arguments.command in ("commit", "pr") and changes.tracked_files:
            api_key = load_api_key()
            # Git은 실제 경로로 읽은 뒤, 로그에 파일명을 표시하기 전에 키를 가린다.
            changes = redact_changes(changes, api_key)
        # 3. 변경 규모와 파일명을 보여 준다. JSON 표기로 경로의 줄바꿈 등도 구분한다.
        print(f"[INFO] Git status 수집 완료: {len(changes.files)}개 파일 변경 감지")
        print(f"[INFO] Git diff 수집 완료: {changes.diff_lines}줄")
        for item in changes.files:
            print(f"  {item.status} {json.dumps(item.path, ensure_ascii=False)}")
        # 새 파일의 내용을 임의로 읽거나 git add하지 않는다. inspect도 여기서 종료한다.
        if not changes.tracked_files:
            print("[INFO] 추적되지 않은 새 파일만 있습니다. git add 후 다시 실행해 주세요.")
            return 0
        if arguments.command == "inspect":
            return 0
        print("[INFO] AI_API_KEY 환경변수 설정을 확인했습니다.")
        print("[INFO] 현재 API Key 마스킹 적용 완료: diff·파일명·브랜치")
        # 4. 선택한 안전 모드의 범위로 줄이고, 일부 diff라는 사실을 출력·프롬프트에 알린다.
        partial = False
        if arguments.safe_mode:
            original_lines = changes.diff_lines
            changes = limit_changes(changes)
            print(
                f"[INFO] 안전 모드 적용: {len(changes.files)}개 파일, "
                f"{changes.diff_lines}줄 (최대 {MAX_FILES}개 파일·{MAX_DIFF_LINES}줄)"
            )
            partial = changes.diff_lines < original_lines
            if partial:
                print("[WARN] 전송 제한으로 일부 변경만 AI 입력에 포함합니다.")
        if not changes.diff_lines:
            print("[INFO] 전송할 diff가 없습니다.")
            return 0
        # 5. 명령에 맞는 작성 규칙과 변경 자료를 준비한다. 추가 맥락의 키도 치환한다.
        is_pr = arguments.command == "pr"
        instruction = PR_SYSTEM_INSTRUCTION if is_pr else COMMIT_SYSTEM_INSTRUCTION
        prompt = build_change_prompt(changes, redact(arguments.context, api_key), partial)
        print(redact(
            f"[INFO] Gemini 요청 설정: model={arguments.model}, "
            f"temperature={arguments.temperature}, max_tokens={arguments.max_tokens}",
            api_key,
        ))
        print("[INFO] Gemini API 요청 중...")
        # 6. 요청 직전에 1회로 기록한다. HTTP 오류가 나도 요청 시도는 이미 발생했다.
        api_calls = 1
        response = generate_text(
            api_key=api_key, model=arguments.model,
            temperature=arguments.temperature, max_tokens=arguments.max_tokens,
            system_instruction=instruction, prompt=prompt,
        )
        # 7. 생성 JSON을 검증·정리한다. adjusted는 제목의 공백/길이를 정리했는지 뜻한다.
        formatter = format_pr if is_pr else format_commit
        output, adjusted = formatter(response, secret=api_key)
        if adjusted:
            print(f"[WARN] {'PR' if is_pr else '커밋'} 제목의 공백 또는 길이를 정리했습니다. 내용을 검토해 주세요.")
        print(f"[DONE] {'PR 초안' if is_pr else '커밋 메시지'} 생성 완료")
        print(output)
        print("[INFO] AI가 만든 초안입니다. 변경 내용과 제목을 검토한 뒤 적용해 주세요.")
        return 0
    except UserError as error:
        # 예상한 실패는 짧은 원인 안내로 표시한다. 오류 문구에 포함된 현재 키도 가린다.
        print(f"[ERROR] {redact(str(error), api_key)}", file=sys.stderr)
        return 1
    finally:
        # try 안에서 일찍 return하거나 오류가 나도 호출 횟수 안내는 실행한다.
        if arguments.command in ("commit", "pr"):
            print(f"[INFO] Gemini API 호출 횟수: {api_calls}회")


if __name__ == "__main__":
    # python3 -m ai_gitgen.cli로 실행한 경우에도 같은 진입 함수를 사용한다.
    raise SystemExit(main())
