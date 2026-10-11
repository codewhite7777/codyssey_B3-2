"""CLI orchestration; Git collection lives in a separate module."""

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
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise argparse.ArgumentTypeError("모델은 영문·숫자·점·밑줄·하이픈의 단일 이름으로 입력해 주세요.")
    return value


def _temperature(value: str) -> float:
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("temperature는 0~2 사이의 숫자여야 합니다.") from error
    if not 0 <= number <= 2:
        raise argparse.ArgumentTypeError("temperature는 유한한 0~2 사이의 값이어야 합니다.")
    return number


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("max-tokens는 양의 정수여야 합니다.") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("max-tokens는 양의 정수여야 합니다.")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Git 변경 사항으로 커밋 메시지와 PR 초안 생성",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("command", choices=("inspect", "commit", "pr"))
    parser.add_argument(
        "--safe-mode", action="store_true",
        help="commit/pr 입력을 최대 10개 파일·합계 200줄의 diff로 제한",
    )
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
    arguments = build_parser().parse_args(argv)
    api_key = ""
    api_calls = 0
    try:
        changes = collect_changes()
        if not changes.files:
            print("[INFO] 변경 사항이 없습니다.")
            return 0
        if arguments.command in ("commit", "pr") and changes.tracked_files:
            api_key = load_api_key()
            # Use real paths for Git reads, then mask before displaying paths.
            changes = redact_changes(changes, api_key)
        print(f"[INFO] Git status 수집 완료: {len(changes.files)}개 파일 변경 감지")
        print(f"[INFO] Git diff 수집 완료: {changes.diff_lines}줄")
        for item in changes.files:
            print(f"  {item.status} {json.dumps(item.path, ensure_ascii=False)}")
        if not changes.tracked_files:
            print("[INFO] 추적되지 않은 새 파일만 있습니다. git add 후 다시 실행해 주세요.")
            return 0
        if arguments.command == "inspect":
            return 0
        print("[INFO] AI_API_KEY 환경변수 설정을 확인했습니다.")
        print("[INFO] 현재 API Key 마스킹 적용 완료: diff·파일명·브랜치")
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
        is_pr = arguments.command == "pr"
        instruction = PR_SYSTEM_INSTRUCTION if is_pr else COMMIT_SYSTEM_INSTRUCTION
        prompt = build_change_prompt(changes, redact(arguments.context, api_key), partial)
        print(redact(
            f"[INFO] Gemini 요청 설정: model={arguments.model}, "
            f"temperature={arguments.temperature}, max_tokens={arguments.max_tokens}",
            api_key,
        ))
        print("[INFO] Gemini API 요청 중...")
        api_calls = 1
        response = generate_text(
            api_key=api_key, model=arguments.model,
            temperature=arguments.temperature, max_tokens=arguments.max_tokens,
            system_instruction=instruction, prompt=prompt,
        )
        formatter = format_pr if is_pr else format_commit
        output, adjusted = formatter(response, secret=api_key)
        if adjusted:
            print(f"[WARN] {'PR' if is_pr else '커밋'} 제목의 공백 또는 길이를 정리했습니다. 내용을 검토해 주세요.")
        print(f"[DONE] {'PR 초안' if is_pr else '커밋 메시지'} 생성 완료")
        print(output)
        print("[INFO] AI가 만든 초안입니다. 변경 내용과 제목을 검토한 뒤 적용해 주세요.")
        return 0
    except UserError as error:
        print(f"[ERROR] {redact(str(error), api_key)}", file=sys.stderr)
        return 1
    finally:
        if arguments.command in ("commit", "pr"):
            print(f"[INFO] Gemini API 호출 횟수: {api_calls}회")


if __name__ == "__main__":
    raise SystemExit(main())
