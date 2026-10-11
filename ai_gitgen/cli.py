"""CLI orchestration; Git collection lives in a separate module."""

import argparse
import json
import sys

from .config import load_api_key
from .errors import UserError
from .git_changes import collect_changes
from .safety import MAX_DIFF_LINES, MAX_FILES, limit_changes, redact_changes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Git 변경 사항으로 커밋/PR 초안 생성")
    parser.add_argument("command", choices=("inspect", "commit", "pr"))
    parser.add_argument(
        "--safe-mode", action="store_true",
        help="commit/pr 입력을 최대 10개 파일·합계 200줄의 diff로 제한",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
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
        if arguments.safe_mode:
            original_lines = changes.diff_lines
            changes = limit_changes(changes)
            print(
                f"[INFO] 안전 모드 적용: {len(changes.files)}개 파일, "
                f"{changes.diff_lines}줄 (최대 {MAX_FILES}개 파일·{MAX_DIFF_LINES}줄)"
            )
            if changes.diff_lines < original_lines:
                print("[WARN] 전송 제한으로 일부 변경만 AI 입력에 포함합니다.")
        print("[INFO] Gemini API 호출 횟수: 0회")
        raise UserError(
            "Gemini API 호출과 초안 생성은 아직 구현되지 않았습니다. "
            "현재 단계는 최소 안전 모드까지입니다."
        )
    except UserError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
