"""터미널 명령을 해석하고 Git 변경에서 커밋·PR 초안까지의 순서를 연결한다.

main.py가 이 모듈의 main()을 호출한다. 옵션 검사 함수와 build_parser()는
입력 규칙을 담당하고, main()은 각 기능 모듈을 언제 호출할지 결정한다.
Git 수집 → Key 확인·안전 처리 → 프롬프트 → Gemini 요청 → 후처리 순서이며,
변경이 없거나 inspect 명령인 경우에는 API 요청까지 진행하지 않는다.
사용자에게 보이는 로그·오류·요청 횟수와 프로그램 종료 코드도 이곳에서 관리한다.
"""

# argparse는 명령·옵션 해석, json은 파일명 표시, re는 모델 이름 형식 검사,
# sys는 정상 출력과 오류 출력의 경로를 구분하는 데 사용한다.
import argparse
import json
import re
import sys

# 앞의 점은 같은 ai_gitgen 패키지의 모듈을 뜻한다. 세부 작업을 분리해 가져오므로
# main()에서는 Git 명령이나 HTTP 본문을 직접 만들지 않고 실행 순서에 집중한다.
from .api_client import generate_text
from .config import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, DEFAULT_TEMPERATURE, load_api_key
from .errors import UserError
from .formatting import format_commit, format_pr
from .git_changes import collect_changes
from .prompts import COMMIT_SYSTEM_INSTRUCTION, PR_SYSTEM_INSTRUCTION, build_change_prompt
from .safety import MAX_DIFF_LINES, MAX_FILES, limit_changes, redact, redact_changes


def _model_name(value: str) -> str:
    """--model로 입력한 문자열이 단일 모델 이름 형식인지 검사한다.

    입력: 터미널에서 받은 모델 이름 문자열 value.
    처리: 전체 문자열이 허용한 문자 조합인지 정규표현식으로 확인한다.
    반환: 형식이 맞으면 입력 문자열을 그대로 반환한다.
    오류: 형식이 틀리면 ArgumentTypeError를 발생시켜 argparse가 사용법을 안내한다.
    실제 모델의 존재·사용 권한을 확인하는 함수는 아니며 이는 API 응답에서 확인한다.
    """
    # fullmatch는 문자열 전체를 검사한다. 첫 글자는 영문·숫자여야 하고 이후에는
    # 점·밑줄·하이픈도 허용한다. '/'가 포함된 경로를 모델 이름으로 넣는 것은 거절한다.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise argparse.ArgumentTypeError("모델은 영문·숫자·점·밑줄·하이픈의 단일 이름으로 입력해 주세요.")
    return value


def _temperature(value: str) -> float:
    """--temperature의 문자열을 API에 전달할 유한한 실수로 바꾼다.

    입력: '0.5'처럼 터미널에서 받은 숫자 문자열.
    처리: float로 변환한 뒤 0 이상 2 이하인지 검사한다.
    반환: 검사에 통과한 float 값. 예를 들어 '0.5'는 0.5가 된다.
    오류: 숫자로 바꿀 수 없거나 범위를 벗어나면 ArgumentTypeError를 발생시킨다.
    """
    try:
        # 명령행 값은 문자열이므로 API의 숫자 필드에 넣기 전에 자료형을 바꾼다.
        number = float(value)
    except ValueError as error:
        # 파이썬 변환 오류를 그대로 보여 주지 않고, 사용자가 고칠 옵션을 알려 준다.
        raise argparse.ArgumentTypeError("temperature는 0~2 사이의 숫자여야 합니다.") from error
    # 양 끝값 0과 2는 허용한다. 무한대는 범위를 벗어나고, NaN은 범위 비교가
    # 참이 되지 않으므로 이 조건으로 모두 거절한다.
    if not 0 <= number <= 2:
        raise argparse.ArgumentTypeError("temperature는 유한한 0~2 사이의 값이어야 합니다.")
    return number


def _positive_int(value: str) -> int:
    """--max-tokens의 문자열을 1 이상의 정수로 바꾼다.

    입력: '4096'처럼 터미널에서 받은 정수 문자열.
    처리: int로 변환하고 0보다 큰지 확인한다.
    반환: API의 maxOutputTokens 필드에 사용할 정수 값.
    오류: 소수 표기·숫자가 아닌 값·0·음수는 ArgumentTypeError로 거절한다.
    """
    try:
        # int('4096')은 가능하지만 int('4.5')는 실패하므로 토큰 상한의 소수 입력도 막는다.
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("max-tokens는 양의 정수여야 합니다.") from error
    if number <= 0:
        # 생성량의 상한으로 사용할 수 있도록 최소 1 이상의 정수만 받는다.
        raise argparse.ArgumentTypeError("max-tokens는 양의 정수여야 합니다.")
    return number


def build_parser() -> argparse.ArgumentParser:
    """CLI가 받을 명령과 옵션의 규칙을 등록한다.

    입력: 직접 받는 인자는 없다. config.py의 기본 설정을 사용한다.
    처리: 필수 명령 하나, 선택 옵션, 기본값과 값 검사 함수를 파서에 등록한다.
    반환: 규칙이 준비된 ArgumentParser 객체. 실제 해석은 main()의 parse_args()가 한다.
    도움말(-h/--help)과 잘못된 옵션의 사용법 안내는 argparse가 제공한다.
    """
    parser = argparse.ArgumentParser(
        description="Git 변경 사항으로 커밋 메시지와 PR 초안 생성",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,  # 도움말에 옵션 기본값도 표시한다.
    )
    # command는 '--' 없이 받는 필수 위치 인자다. choices로 세 명령 이외의 입력을 막는다.
    # inspect는 Git 수집 확인용이고, commit/pr는 같은 변경으로 서로 다른 초안을 만든다.
    parser.add_argument("command", choices=("inspect", "commit", "pr"))
    parser.add_argument(
        "--safe-mode", action="store_true",  # 값을 받지 않고 지정 여부를 True/False로 저장한다.
        help="commit/pr 입력을 최대 10개 파일·합계 200줄의 diff로 제한",
    )
    # 생성 옵션은 생략하면 config.py의 기본값을 사용한다. 사용자가 값을 넣으면
    # type으로 지정한 함수가 API 요청 전에 변환·검사한다. 두 이름은 같은 옵션의 별칭이다.
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
    # diff만으로 알기 어려운 변경 배경을 사용자가 보충하는 문자열이다.
    # 전달하지 않아도 실행 가능하며, main()에서 현재 Key를 가린 뒤 프롬프트에 넣는다.
    parser.add_argument("--context", default="", help="변경 이유·요구사항")
    return parser


def main(argv: list[str] | None = None) -> int:
    """명령 한 번의 입력 해석부터 초안 출력까지 실행하고 종료 결과를 반환한다.

    입력: argv가 None이면 실제 명령행 인자를 읽는다. 테스트에서는
    ['commit', '--safe-mode'] 같은 목록을 전달해 같은 흐름을 실행할 수 있다.
    처리: Git 수집 → Key·안전 처리 → 프롬프트 구성 → API 요청 → 결과 검증·출력.
    반환: 정상 처리·안내 후 종료는 0, UserError로 처리한 실패는 1이다.
    잘못된 옵션은 try 진입 전에 argparse가 SystemExit(2)로 종료한다.

    변경 없음·미추적 새 파일만 존재·inspect는 API를 호출하지 않는다.
    commit/pr에 추적 변경이 있으면 Key를 확인하며, 실제 전송할 diff가 남아 있을 때
    요청을 한 번 시도한다. 이 함수는 실제 git add/commit/push/PR 생성을 하지 않는다.
    """
    # 1. 옵션을 읽어 arguments.command, arguments.safe_mode 같은 속성에 담는다.
    # 잘못된 옵션은 여기서 종료하므로 아래 try/finally의 요청 횟수 안내도 실행되지 않는다.
    arguments = build_parser().parse_args(argv)
    # Key를 읽기 전 오류가 나도 오류 출력에 사용할 변수가 존재하도록 빈 값으로 시작한다.
    api_key = ""
    # API 횟수는 성공 횟수가 아니라 요청을 시도한 횟수다. 실제 요청 직전에 1로 바꾼다.
    api_calls = 0
    try:
        # 2. 현재 루트의 상태·diff를 수집한다. 변경이 없으면 키도 읽지 않고 끝낸다.
        changes = collect_changes()
        if not changes.files:
            # 분석할 입력이 없으면 인증과 통신도 필요 없다. Key 미설정 오류를 확인하려면
            # 사용자가 먼저 추적 파일의 변경을 준비해야 하는 이유가 이 순서에 있다.
            print("[INFO] 변경 사항이 없습니다.")
            return 0
        if arguments.command in ("commit", "pr") and changes.tracked_files:
            # inspect와 미추적 파일만 있는 경우에는 Key가 필요 없다.
            # 생성할 변경이 있는 경우에는 파일명 로그를 출력하기 전에 Key부터 확인한다.
            api_key = load_api_key()
            # Git은 실제 경로로 파일을 읽어야 하므로 수집한 다음 마스킹한다.
            # 치환 대상은 메모리에 담긴 자료이며 실제 파일명이나 파일 내용은 바꾸지 않는다.
            changes = redact_changes(changes, api_key)
        # 3. 수집 결과를 알려 준다. 파일 수에는 미추적 파일도 포함되지만 그 파일의
        # diff 본문은 아직 없다. diff_lines에는 변경 줄 외에 헤더·문맥 줄도 포함된다.
        print(f"[INFO] Git status 수집 완료: {len(changes.files)}개 파일 변경 감지")
        print(f"[INFO] Git diff 수집 완료: {changes.diff_lines}줄")
        for item in changes.files:
            # JSON 문자열 표기로 경로를 감싸면 파일명 안의 줄바꿈이 실제 로그 줄을
            # 나누지 않는다. ensure_ascii=False는 한글 파일명을 읽을 수 있게 유지한다.
            print(f"  {item.status} {json.dumps(item.path, ensure_ascii=False)}")
        # 새 파일의 내용을 임의로 읽거나 git add하지 않는다. inspect도 여기서 종료한다.
        if not changes.tracked_files:
            # 새 파일을 임의로 열어 본문을 만들지 않는다. 사용자가 git add하면
            # 다음 실행에서 staged diff로 읽을 수 있다. 이는 정상적인 안내 종료다.
            print("[INFO] 추적되지 않은 새 파일만 있습니다. git add 후 다시 실행해 주세요.")
            return 0
        if arguments.command == "inspect":
            # 수집 확인 명령의 목적은 여기까지다. 생성용 안전 처리·프롬프트·API는 생략한다.
            return 0
        # 이 안내는 환경변수에 값이 있다는 뜻이다. Key의 실제 인증 성공은 아직 확인 전이다.
        print("[INFO] AI_API_KEY 환경변수 설정을 확인했습니다.")
        print("[INFO] 현재 API Key 마스킹 적용 완료: diff·파일명·브랜치")
        # 4. 선택한 안전 모드의 범위로 줄이고, 일부 diff라는 사실을 출력·프롬프트에 알린다.
        partial = False
        if arguments.safe_mode:
            # 제한 전후의 전체 diff 줄 수를 비교해 일부 자료가 제외되었는지 판단한다.
            # --safe-mode가 없으면 현재 Key 마스킹만 적용하고 이 수량 제한은 건너뛴다.
            original_lines = changes.diff_lines
            changes = limit_changes(changes)
            print(
                f"[INFO] 안전 모드 적용: {len(changes.files)}개 파일, "
                f"{changes.diff_lines}줄 (최대 {MAX_FILES}개 파일·{MAX_DIFF_LINES}줄)"
            )
            partial = changes.diff_lines < original_lines
            if partial:
                # 사용자에게도 알리고 아래 프롬프트의 partial_diff로 AI에도 전달한다.
                print("[WARN] 전송 제한으로 일부 변경만 AI 입력에 포함합니다.")
        if not changes.diff_lines:
            # 상태 변화가 있어도 전송할 diff 문자열이 없다면 빈 입력으로 요청하지 않는다.
            print("[INFO] 전송할 diff가 없습니다.")
            return 0
        # 5. 명령에 맞는 작성 규칙과 변경 자료를 준비한다. 추가 맥락의 키도 치환한다.
        is_pr = arguments.command == "pr"
        # 입력 수집과 API는 두 명령이 공유한다. 여기의 작성 규칙과 아래 formatter만 달라진다.
        instruction = PR_SYSTEM_INSTRUCTION if is_pr else COMMIT_SYSTEM_INSTRUCTION
        # context는 변경 이유를 담은 별도 입력이므로 diff와 별개로 Key를 치환한다.
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
        # 7. API 함수가 돌려준 것은 생성 JSON 문자열이다. formatter가 필수 내용을 검사하고
        # 제목·섹션을 정리해 (출력문, 제목 조정 여부) 두 값을 함께 돌려준다.
        formatter = format_pr if is_pr else format_commit
        output, adjusted = formatter(response, secret=api_key)
        if adjusted:
            # Key를 가린 제목에서 공백 또는 길이를 추가 조정한 경우에만 경고한다.
            # 제목을 줄이면서 의미가 달라지지 않았는지는 사용자가 확인해야 한다.
            print(f"[WARN] {'PR' if is_pr else '커밋'} 제목의 공백 또는 길이를 정리했습니다. 내용을 검토해 주세요.")
        print(f"[DONE] {'PR 초안' if is_pr else '커밋 메시지'} 생성 완료")
        print(output)
        print("[INFO] AI가 만든 초안입니다. 변경 내용과 제목을 검토한 뒤 적용해 주세요.")
        return 0
    except UserError as error:
        # 설정·Git·HTTP·출력 검증의 예상 가능한 오류를 같은 방식으로 보여 준다.
        # 정상 안내와 구분하도록 stderr에 쓰고, 읽어 둔 현재 Key가 문구에 있으면 가린다.
        # 모든 Exception을 잡지는 않으므로 예상하지 못한 코딩 오류까지 숨기지는 않는다.
        print(f"[ERROR] {redact(str(error), api_key)}", file=sys.stderr)
        return 1
    finally:
        # try 안에서 return하거나 UserError가 나도 이 블록은 실행된다.
        # API 요청 전 종료는 0회, 요청 후 실패도 시도 자체는 있었으므로 1회로 표시한다.
        # inspect는 API를 쓰는 명령이 아니므로 호출 횟수 안내도 출력하지 않는다.
        if arguments.command in ("commit", "pr"):
            print(f"[INFO] Gemini API 호출 횟수: {api_calls}회")


if __name__ == "__main__":
    # python3 -m ai_gitgen.cli로 실행한 경우에도 같은 진입 함수를 사용한다.
    raise SystemExit(main())
