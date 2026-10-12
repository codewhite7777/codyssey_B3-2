"""AI에 보낼 수집 결과에서 현재 API Key를 가리고 diff 전송량을 줄인다.

redact()는 문자열 하나를, redact_changes()는 파일 목록·브랜치·diff를 마스킹한다.
limit_changes()는 --safe-mode를 선택했을 때 사용할 파일 수·diff 줄 수 상한을
적용한다. 현재 Key와 같은 문자열 치환과 전송량 제한은 서로 다른 처리다.

입력은 Git 수집을 마친 뒤의 문자열 또는 GitChanges 객체다. 실제 파일·Git
인덱스는 건드리지 않고 새 문자열·객체를 반환한다. 다른 Key나 개인정보까지
자동으로 찾아내는 기능은 없으므로 전송 내용은 사용자가 검토해야 한다.
"""

from dataclasses import replace

from .git_changes import GitChanges

# 기본 과제의 최소 안전 모드 정책이다. 전체 선택 파일의 staged·unstaged diff를
# 합쳐 200줄까지만 남긴다. 파일별로 200줄이 아니며 CLI에서 바꾸는 값도 아니다.
MAX_FILES = 10
MAX_DIFF_LINES = 200


def redact(text: str, secret: str) -> str:
    """문자열에 현재 API Key가 그대로 드러나지 않도록 치환한다.

    text는 검사할 문자열, secret은 환경변수에서 읽은 현재 Key다. 일치하는
    모든 부분을 [REDACTED]로 바꾼 새 문자열을 반환하고, secret이 비어 있으면
    입력 text를 그대로 반환한다. 원문을 파일에 다시 저장하는 처리는 없다.

    diff·파일명뿐 아니라 CLI의 추가 맥락·출력 등에서도 재사용하는 공통 처리다.
    정확히 같은 문자열만 대상으로 하며, 다른 Key·이메일이나 변형된 값의
    패턴을 탐지하지 않는다. 문자열 입력에서는 별도의 오류를 발생시키지 않는다.
    """
    if not secret:
        # 빈 문자열을 치환하면 모든 문자 사이에 마스킹 문구가 끼므로 그대로 돌려준다.
        return text
    # 일치하는 값의 길이나 위치와 관계없이 모든 등장 위치를 같은 표시로 가린다.
    return text.replace(secret, "[REDACTED]")


def redact_changes(changes: GitChanges, secret: str) -> GitChanges:
    """수집 결과에 포함된 현재 Key를 가린 GitChanges 복사본을 반환한다.

    changes는 Git 수집 결과, secret은 현재 API Key다. 브랜치 문자열과 모든
    파일의 현재 경로·이전 경로·staged/unstaged diff에 redact()를 적용한다.
    상태 값과 파일 순서는 유지하고, 이전 경로가 없음을 뜻하는 None도 유지한다.

    실제 경로로 Git 명령을 모두 실행한 뒤 호출한다. 경로를 먼저 가리면 Git이
    원래 파일을 찾지 못하기 때문이다. 원본 객체·작업 파일은 바꾸지 않는다.
    올바른 GitChanges와 문자열을 입력받으면 별도의 UserError를 만들지 않는다.
    """
    # 바깥 replace는 전체 결과를, 안쪽 replace는 각 파일을 복사한다. frozen 객체의
    # 필드를 직접 수정하지 않아 원본 diff와 마스킹한 전송용 diff를 구분할 수 있다.
    return replace(
        changes,
        branch=redact(changes.branch, secret),
        # 미추적 파일도 경로는 출력될 수 있으므로 추적 여부와 관계없이 모두 가린다.
        files=tuple(
            replace(
                item,
                path=redact(item.path, secret),
                # None은 문자열이 아니며 '이전 경로 없음'이라는 뜻을 보존해야 한다.
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
    """--safe-mode에서 보낼 diff 양을 제한한 GitChanges 복사본을 만든다.

    입력 changes의 추적 파일을 원래 순서대로 읽어, diff가 남는 최대 10개
    파일과 전체 합계 최대 200줄을 선택한다. 각 파일에서는 staged를 먼저
    담고 그 뒤 unstaged를 담으며, 상한에 도달하면 이후 내용은 제외한다.

    반환 객체에는 선택한 파일과 제한된 diff, 원래 브랜치 정보가 들어간다.
    제한은 오류가 아니라 의도된 일부 선택이므로 UserError를 발생시키지 않는다.
    CLI는 적용 전후를 비교해 일부 변경만 전달되는지 안내한다.

    diff 헤더·문맥도 줄 수에 포함한다. --context나 전체 프롬프트의 길이,
    API 토큰 수를 제한하는 기능은 아니며, 민감정보 여부도 판단하지 않는다.
    """
    # diff가 한 줄 이상 남은 파일만 이 목록에 넣어 실제 전송 파일 수를 센다.
    selected = []
    # 모든 파일의 staged·unstaged가 하나의 남은 줄 수를 공유한다.
    remaining = MAX_DIFF_LINES
    for item in changes.tracked_files:
        # 파일 상한과 전체 줄 상한 중 하나라도 도달하면 이후 파일을 더 선택하지 않는다.
        if len(selected) >= MAX_FILES or remaining == 0:
            break
        # 선택한 줄을 다시 합칠 때 줄바꿈이 사라지지 않게 보존한다.
        # staged를 담고 남은 범위에서 같은 파일의 unstaged를 선택한다.
        staged = item.staged_diff.splitlines(keepends=True)[:remaining]
        # 이번에 담은 staged 줄을 차감해야 unstaged와 다음 파일이 같은 상한을 공유한다.
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
    # 빈 diff뿐이었다면 files가 빈 튜플이 된다. 그 상태의 안내·종료는 CLI가 결정한다.
    return replace(changes, files=tuple(selected))
