"""AI가 생성한 JSON 필드를 검사하고 제목·불릿·터미널 구획을 정리한다.

API 응답에서 꺼낸 생성 문자열을 입력으로 받는다. 재요청 없이 형식을 후처리하며,
변경 이유의 사실성이나 테스트 수행 여부는 사용자가 최종 검토해야 한다.
"""

import json

from .errors import UserError
from .safety import redact


def format_commit(text: str, secret: str = "") -> tuple[str, bool]:
    """생성 JSON과 현재 키를 받아 (커밋 출력문, 제목 조정 여부)를 반환한다.

    summary 목록과 title 문자열을 검사하고, 키 치환·한 줄 정리·최대 72자 제한을
    적용한다. 잘못된 JSON이나 빈 필드는 UserError다. 별도 커밋 본문은 만들지 않는다.
    bool 값은 키를 가린 제목에서 공백/길이를 추가로 정리했는지를 뜻한다.
    """
    # 1. API 전체 응답이 아니라, 모델이 작성한 JSON 문자열의 내부 필드를 읽는다.
    try:
        draft = json.loads(text)
    except json.JSONDecodeError as error:
        raise UserError("AI가 생성한 커밋 결과를 JSON으로 읽을 수 없습니다.") from error
    if not isinstance(draft, dict):
        raise UserError("커밋 결과는 summary와 title을 가진 JSON 객체여야 합니다.")
    # 2. 제목과 요약의 타입·빈 값을 검사한다. 접두사와 요약 개수 상한은 별도로 강제하지 않는다.
    original_title = draft.get("title")
    summary = draft.get("summary")
    if not isinstance(original_title, str) or not original_title.strip():
        raise UserError("커밋 제목(title)은 비어 있지 않은 문자열이어야 합니다.")
    if not isinstance(summary, list) or not summary or any(
        not isinstance(item, str) or not item.strip() for item in summary
    ):
        raise UserError("변경 요약(summary)은 비어 있지 않은 문자열 목록이어야 합니다.")

    # 3. JSON 이스케이프를 해석한 문자열에서 키를 가린 뒤 제목을 정리한다.
    # 50자는 프롬프트의 권장값이고, 코드는 말줄임표를 포함한 최대 72자를 적용한다.
    masked_title = redact(original_title, secret)
    title = " ".join(masked_title.split())
    if len(title) > 72:
        title = title[:71].rstrip() + "…"
    # 4. 변경 요약은 불릿으로, 복사할 커밋 제목은 별도 구획으로 출력한다.
    lines = ["--- Change Summary ---"]
    lines.extend("- " + " ".join(redact(item, secret).split()) for item in summary)
    lines.extend(["", "--- Commit Message ---", title, "----------------------"])
    return "\n".join(lines), title != masked_title


def format_pr(text: str, secret: str = "") -> tuple[str, bool]:
    """생성 JSON과 현재 키를 받아 (PR 출력문, 제목 조정 여부)를 반환한다.

    title은 비어 있지 않은 문자열인지, summary/why/what/how_to_test는
    비어 있지 않은 문자열 목록인지 검사한다.
    제목은 한 줄·최대 80자로 정리하고 각 목록은 불릿으로 구성한다.
    필수 값 누락·잘못된 타입·JSON 오류는 UserError이며 임의 문장으로 채우지 않는다.
    bool 값은 키를 가린 제목에서 공백/길이를 추가로 정리했는지를 뜻한다.
    """
    # 1. 모델이 작성한 JSON을 읽고, 제목이 비어 있지 않은 문자열인지 확인한다.
    try:
        draft = json.loads(text)
    except json.JSONDecodeError as error:
        raise UserError("AI가 생성한 PR 결과를 JSON으로 읽을 수 없습니다.") from error
    if not isinstance(draft, dict):
        raise UserError("PR 결과는 title과 필수 목록을 가진 JSON 객체여야 합니다.")
    original_title = draft.get("title")
    if not isinstance(original_title, str) or not original_title.strip():
        raise UserError("PR 제목(title)은 비어 있지 않은 문자열이어야 합니다.")
    # 2. 필수 목록마다 최소 한 개의 비어 있지 않은 문자열이 있어야 불릿을 만들 수 있다.
    fields = ("summary", "why", "what", "how_to_test")
    for field in fields:
        items = draft.get(field)
        if not isinstance(items, list) or not items or any(
            not isinstance(item, str) or not item.strip() for item in items
        ):
            raise UserError(f"PR의 {field}는 비어 있지 않은 문자열 목록이어야 합니다.")

    # 3. 해석된 문자열의 키를 먼저 가리고, 제목은 말줄임표까지 포함해 최대 80자로 정리한다.
    masked_title = redact(original_title, secret)
    title = " ".join(masked_title.split())
    if len(title) > 80:
        title = title[:79].rstrip() + "…"
    # 4. 모든 문장의 키·공백을 정리하고, AI 문구 앞에 Python이 '- '를 붙여 불릿을 만든다.
    bullets = {
        field: ["- " + " ".join(redact(item, secret).split()) for item in draft[field]]
        for field in fields
    }
    # 5. 고정된 세 섹션에 문장을 배치한다. *는 각 목록의 항목을 이 목록에 펼쳐 넣는다.
    lines = [
        "--- Change Summary ---", *bullets["summary"], "",
        "--- PR Title ---", title, "",
        "--- PR Body ---",
        "## Why", *bullets["why"], "",
        "## What", *bullets["what"], "",
        "## How to Test", *bullets["how_to_test"],
        "----------------------",
    ]
    return "\n".join(lines), title != masked_title
