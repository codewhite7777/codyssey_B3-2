"""수집한 Git 정보의 현재 API Key를 마스킹하고 안전 모드의 전송량을 제한한다.

실제 파일과 Git 인덱스는 건드리지 않고, 분석에 사용할 메모리상의 복사본을 만든다.
"""

from dataclasses import replace

from .git_changes import GitChanges

# diff가 있는 파일 수와, 모든 선택 파일의 diff를 합친 줄 수의 상한이다.
MAX_FILES = 10
MAX_DIFF_LINES = 200


def redact(text: str, secret: str) -> str:
    """text에서 secret과 정확히 일치하는 문자열을 [REDACTED]로 바꿔 반환한다.

    secret이 비어 있으면 원문을 반환한다. 다른 Key나 개인정보의 패턴 탐지는 하지 않는다.
    """
    if not secret:
        return text
    return text.replace(secret, "[REDACTED]")


def redact_changes(changes: GitChanges, secret: str) -> GitChanges:
    """브랜치·경로·diff에서 secret을 치환한 GitChanges 복사본을 반환한다.

    실제 경로를 사용하는 Git 수집이 끝난 뒤 호출하여, 경로 마스킹 때문에 파일을
    읽지 못하는 일을 피한다. 원래 객체와 작업 파일의 내용은 수정하지 않는다.
    """
    # frozen 데이터 객체의 필요한 필드만 교체한 새 객체를 만든다.
    # 이전 경로가 없는 파일의 None은 유지하고, 문자열인 항목만 마스킹한다.
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


def limit_changes(changes: GitChanges) -> GitChanges:
    """안전 모드용으로 diff가 있는 최대 10개 파일·전체 200줄을 남겨 반환한다.

    입력 순서대로 추적 파일을 선택하고, 각 파일에서는 staged를 먼저 담는다.
    줄 제한에는 diff 헤더·문맥도 포함되며, context나 전체 프롬프트의 길이 제한은 아니다.
    """
    selected = []
    # 모든 파일의 staged·unstaged가 하나의 남은 줄 수를 공유한다.
    remaining = MAX_DIFF_LINES
    for item in changes.tracked_files:
        if len(selected) >= MAX_FILES or remaining == 0:
            break
        # 선택한 줄을 다시 합칠 때 줄바꿈이 사라지지 않게 보존한다.
        # staged를 담고 남은 범위에서 같은 파일의 unstaged를 선택한다.
        staged = item.staged_diff.splitlines(keepends=True)[:remaining]
        remaining -= len(staged)
        unstaged = item.unstaged_diff.splitlines(keepends=True)[:remaining]
        remaining -= len(unstaged)
        if staged or unstaged:
            # diff가 실제로 남은 파일만 개수에 넣고, 원본 대신 제한된 복사본을 만든다.
            selected.append(replace(
                item,
                staged_diff="".join(staged),
                unstaged_diff="".join(unstaged),
            ))
    return replace(changes, files=tuple(selected))
