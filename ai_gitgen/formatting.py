"""AI가 작성한 초안을 검사하고, 사람이 읽을 터미널 출력문을 만드는 모듈.

입력은 api_client.py가 전체 HTTP 응답에서 꺼낸 '생성 문자열'이다.
이 문자열을 다시 JSON으로 읽어 필수 필드의 자료형과 빈 값을 검사한 다음,
Key 마스킹·제목 길이 제한·섹션과 불릿 구성을 적용한다.

두 함수 모두 (출력 문자열, 제목 조정 여부)를 반환하며 직접 print하지 않는다.
CLI는 제목을 조정했다면 안내를 추가한 뒤 반환된 문자열을 터미널에 출력한다.
API 재요청은 하지 않으며, 내용의 사실성과 테스트 수행 여부는 사용자가 검토한다.
"""

import json

from .errors import UserError
from .safety import redact


def format_commit(text: str, secret: str = "") -> tuple[str, bool]:
    """커밋 초안의 필드를 검사하고, 변경 요약과 커밋 제목을 구획으로 나눈다.

    입력:
        text는 summary·title을 담은 AI 생성 JSON 문자열이다.
        secret은 출력에서 가릴 현재 API Key이며, 기본값은 빈 문자열이다.

    처리:
        필수 값의 자료형과 빈 값을 검사하고, 해석된 문자열에서 Key를 가린다.
        제목의 줄바꿈·연속 공백을 정리하고, Python len() 기준 최대 72자로 맞춘다.
        요약은 별도 구획에 불릿으로 표시하며, 복사할 커밋 본문은 만들지 않는다.

    반환:
        (출력문, 제목 조정 여부) 튜플이다. 두 번째 bool은 Key를 가린 제목에서
        공백이나 길이를 추가로 정리했는지이며, Key 마스킹 자체는 포함하지 않는다.

    오류:
        잘못된 JSON, 객체가 아닌 결과, title·summary의 누락·잘못된 타입·빈 값은
        UserError다. 필수 내용을 새로 만들거나 AI에 재요청하지 않는다.
    """
    # 1. 두 번째 JSON 해석 단계다. 첫 번째는 api_client.py가 HTTP 응답을 읽을 때다.
    # 여기서는 모델이 쓴 {"summary": [...], "title": "..."}의 내부 필드를 읽는다.
    try:
        draft = json.loads(text)
    except json.JSONDecodeError as error:
        # 형식이 깨진 JSON을 임의로 복구하지 않고, 사용자가 알아볼 오류로 전달한다.
        raise UserError("AI가 생성한 커밋 결과를 JSON으로 읽을 수 없습니다.") from error
    # 유효한 JSON이어도 목록·숫자·문자열이면 필드 이름으로 값을 꺼낼 수 없으므로 거부한다.
    if not isinstance(draft, dict):
        raise UserError("커밋 결과는 summary와 title을 가진 JSON 객체여야 합니다.")
    # 2. get()은 해당 필드가 없으면 None을 돌려주므로 누락도 아래 검사에서 처리된다.
    # 접두사와 요약 1~3개라는 상한은 프롬프트 지시이며, 이 함수는 따로 강제하지 않는다.
    original_title = draft.get("title")
    summary = draft.get("summary")
    # 문자열인지 먼저 확인해야 strip()을 안전하게 호출할 수 있다.
    # strip()은 양끝 공백을 빼므로 공백·줄바꿈만 있는 제목도 빈 값으로 판정한다.
    if not isinstance(original_title, str) or not original_title.strip():
        raise UserError("커밋 제목(title)은 비어 있지 않은 문자열이어야 합니다.")
    # summary는 목록이어야 하고, 최소 한 항목이 있어야 하며, 모든 항목이 유효해야 한다.
    # any()는 문자열이 아니거나 빈 항목이 하나라도 있으면 True가 되어 오류를 발생시킨다.
    if not isinstance(summary, list) or not summary or any(
        not isinstance(item, str) or not item.strip() for item in summary
    ):
        raise UserError("변경 요약(summary)은 비어 있지 않은 문자열 목록이어야 합니다.")

    # 3. JSON의 이스케이프를 해석한 실제 문자열에서 Key를 가린다.
    # 원본 JSON 글자만 치환하면 이스케이프로 표현된 같은 Key를 놓칠 수 있기 때문이다.
    masked_title = redact(original_title, secret)
    # split()은 줄바꿈·탭·연속 공백을 기준으로 나누고 join()은 공백 하나로 다시 잇는다.
    # 따라서 여러 줄로 온 제목도 한 줄이 된다.
    title = " ".join(masked_title.split())
    # 50자는 권장값이고 코드가 강제하는 최대 길이는 72자다.
    if len(title) > 72:
        # 앞 71자에서 끝 공백을 지우고 말줄임표 한 글자를 붙여 최대 72자를 지킨다.
        title = title[:71].rstrip() + "…"
    # 4. 출력할 줄들을 목록으로 준비한다. 이곳에서는 내용을 작성할 뿐 print하지 않는다.
    lines = ["--- Change Summary ---"]
    # 각 요약도 Key와 공백을 정리하고 Python이 '- '를 붙여 불릿 한 줄로 만든다.
    # extend()는 생성된 여러 줄을 lines 목록의 뒤에 각각 추가한다.
    lines.extend("- " + " ".join(redact(item, secret).split()) for item in summary)
    # 변경 요약과 복사할 커밋 제목의 위치를 나누며, 빈 문자열은 출력 시 빈 줄이 된다.
    lines.extend(["", "--- Commit Message ---", title, "----------------------"])
    # 줄 목록을 하나의 문자열로 합친다. 비교 기준은 원본이 아닌 masked_title이므로
    # 마스킹만 하고 제목의 공백·길이는 그대로라면 두 번째 값은 False다.
    return "\n".join(lines), title != masked_title


def format_pr(text: str, secret: str = "") -> tuple[str, bool]:
    """PR 초안을 검사하고, 제목과 필수 세 섹션을 갖춘 출력문을 만든다.

    입력:
        text는 title·summary·why·what·how_to_test를 담은 AI 생성 JSON 문자열이다.
        secret은 출력에서 가릴 현재 API Key이며, 기본값은 빈 문자열이다.

    처리:
        제목과 필수 목록을 검사한 뒤 Key를 가리고 공백을 정리한다.
        제목은 한 줄·최대 80자로 제한하고, Python이 각 목록에 불릿을 붙여
        Why·What·How to Test 헤더 아래에 배치한다.

    반환:
        (출력문, 제목 조정 여부) 튜플이다. 두 번째 bool은 Key를 가린 제목에서
        공백이나 길이를 추가로 정리했는지이며, 본문의 변경 여부를 뜻하지 않는다.

    오류:
        잘못된 JSON·누락된 필드·잘못된 자료형·빈 제목이나 목록은 UserError다.
        내용이 없으면 임의 문장으로 채우지 않으며, 사실 여부를 판정하는 함수도 아니다.
    """
    # 1. 전체 HTTP 응답은 이미 읽었으므로, 여기서는 모델이 작성한 JSON만 해석한다.
    try:
        draft = json.loads(text)
    except json.JSONDecodeError as error:
        raise UserError("AI가 생성한 PR 결과를 JSON으로 읽을 수 없습니다.") from error
    if not isinstance(draft, dict):
        raise UserError("PR 결과는 title과 필수 목록을 가진 JSON 객체여야 합니다.")
    original_title = draft.get("title")
    # 필드 누락(None), 문자열이 아닌 값, 공백뿐인 제목을 모두 오류로 구분한다.
    if not isinstance(original_title, str) or not original_title.strip():
        raise UserError("PR 제목(title)은 비어 있지 않은 문자열이어야 합니다.")
    # 2. 네 목록에 같은 검사를 적용한다. summary는 전체 변경 요약이며,
    # 나머지 세 목록은 실제 PR 본문의 필수 섹션이 된다.
    fields = ("summary", "why", "what", "how_to_test")
    for field in fields:
        items = draft.get(field)
        # 목록이 없거나 비었거나 잘못된 항목이 하나라도 있으면 섹션을 만들지 않는다.
        # 모든 항목이 비어 있지 않은 문자열이어야 최소 한 개 이상의 불릿이 보장된다.
        if not isinstance(items, list) or not items or any(
            not isinstance(item, str) or not item.strip() for item in items
        ):
            # 문제가 있는 필드 이름을 메시지에 넣어 어떤 부분이 잘못됐는지 알린다.
            raise UserError(f"PR의 {field}는 비어 있지 않은 문자열 목록이어야 합니다.")

    # 3. Key를 가린 뒤 split/join으로 제목의 줄바꿈·탭·연속 공백을 공백 하나로 정리한다.
    masked_title = redact(original_title, secret)
    title = " ".join(masked_title.split())
    if len(title) > 80:
        # 79자까지 남긴 뒤 말줄임표 한 글자를 붙인다. 끝 공백은 rstrip()으로 제거한다.
        title = title[:79].rstrip() + "…"
    # 4. 딕셔너리 컴프리헨션은 필드별 불릿 목록을 만들고, 내부 리스트 컴프리헨션은
    # 해당 필드의 문장을 하나씩 정리한다. AI에게 Markdown 구조 자체를 맡기지 않는다.
    # 요약·본문의 모든 문장에서도 Key를 가리고 줄바꿈을 정리한 뒤 '- '를 붙인다.
    bullets = {
        field: ["- " + " ".join(redact(item, secret).split()) for item in draft[field]]
        for field in fields
    }
    # 5. 고정된 헤더 아래에 검사를 통과한 문장을 배치하므로 필수 섹션이 빠지지 않는다.
    # *bullets[...]는 목록 자체를 한 항목으로 넣는 대신 각 문자열을 한 줄씩 펼쳐 넣는다.
    # 빈 문자열은 구획 사이의 빈 줄이며, Change Summary는 PR 본문과 별도 표시한다.
    lines = [
        "--- Change Summary ---", *bullets["summary"], "",
        "--- PR Title ---", title, "",
        "--- PR Body ---",
        "## Why", *bullets["why"], "",
        "## What", *bullets["what"], "",
        "## How to Test", *bullets["how_to_test"],
        "----------------------",
    ]
    # 제목 조정 여부는 마스킹 후 제목과 비교한다. 마스킹만 수행했거나 본문만 정리했다면
    # False이며, 제목의 공백·길이까지 바뀐 경우에만 CLI에 조정 사실을 알린다.
    return "\n".join(lines), title != masked_title
