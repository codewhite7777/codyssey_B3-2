"""CLI orchestration; Git collection lives in a separate module."""

import argparse
import json
import sys

from .config import load_api_key
from .errors import UserError
from .git_changes import collect_changes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Git 변경 사항으로 커밋/PR 초안 생성")
    parser.add_argument("command", choices=("inspect", "commit", "pr"))
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        changes = collect_changes()
        if not changes.files:
            print("[INFO] 변경 사항이 없습니다.")
            return 0
        print(f"[INFO] Git status 수집 완료: {len(changes.files)}개 파일 변경 감지")
        print(f"[INFO] Git diff 수집 완료: {changes.diff_lines}줄")
        for item in changes.files:
            print(f"  {item.status} {json.dumps(item.path, ensure_ascii=False)}")
        if not changes.tracked_files:
            print("[INFO] 추적되지 않은 새 파일만 있습니다. git add 후 다시 실행해 주세요.")
            return 0
        if arguments.command == "inspect":
            return 0
        load_api_key()
        print("[INFO] AI_API_KEY 환경변수 설정을 확인했습니다.")
        print("[INFO] Gemini API 호출 횟수: 0회")
        raise UserError(
            "Gemini API 호출과 초안 생성은 아직 구현되지 않았습니다. "
            "현재 단계는 API Key 설정 확인까지입니다."
        )
    except UserError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
