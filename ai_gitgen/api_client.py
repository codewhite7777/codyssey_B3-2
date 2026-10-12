"""Gemini와 HTTP로 통신하여 초안으로 사용할 생성 문자열을 가져오는 모듈.

입력은 cli.main()이 준비한 Key·모델·생성 옵션·프롬프트다. 이 모듈은
요청 JSON을 만들고, 한 번 전송한 다음, 정상 완료된 응답의 텍스트를 꺼낸다.
Git 명령 실행, 환경변수 읽기, 터미널 출력은 여기서 하지 않는다.

JSON은 두 단계로 구분한다. 여기서 읽는 것은 Gemini의 전체 응답이고,
그 안의 생성 문자열에 들어 있는 title·summary 등은 formatting.py가 읽는다.
통신 실패나 응답 구조의 문제는 UserError로 전달하여 CLI가 원인을 안내하게 한다.
"""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .errors import UserError
from .safety import redact


def generate_text(
    *,
    api_key: str,
    model: str,
    temperature: float,
    max_tokens: int,
    system_instruction: str,
    prompt: str,
) -> str:
    """Gemini에 초안 생성을 요청하고, 정상 완료된 생성 문자열을 반환한다.

    입력:
        api_key는 인증 Key, model은 요청할 모델 이름이다.
        temperature는 생성 옵션, max_tokens는 생성 토큰 수의 상한이다.
        system_instruction은 커밋 또는 PR의 작성 규칙이며,
        prompt는 호출자가 수집·마스킹·선택을 마친 Git 변경 자료다.
        인자 앞의 * 때문에 호출할 때 api_key=...처럼 이름을 명시해야 한다.

    처리:
        작성 규칙과 자료를 요청 본문에 담아 POST를 한 번 보낸다.
        전체 응답에서 첫 후보의 완료 상태를 확인하고 본문 조각을 합친다.
        환경변수 읽기나 자동 재시도는 하지 않는다.

    반환:
        JSON 형식으로 요청한 AI의 생성 문자열이며, 아직 dict나 터미널 출력문이 아니다.
        생성 문자열의 JSON 유효성과 내부 필드는 format_commit() 또는 format_pr()가 검사한다.

    오류:
        통신 실패, JSON 해석 실패, 응답 구조 오류, 입력 차단, 생성 미완료,
        빈 본문은 UserError로 전달한다. 응답이 토큰 상한에서 잘려도 사용하지 않는다.
    """
    # 1. Python dict로 요청 본문을 준비한다. 아래 필드명은 Gemini API가 받는 이름이다.
    payload = {
        # 작성 규칙을 별도로 전달하여, 분석 대상인 diff의 내용과 역할을 구분한다.
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        # 실제 변경 자료는 user 역할의 메시지로 넣는다. parts는 본문 조각의 목록이다.
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            # CLI에서 받은 값을 그대로 전달한다. 옵션의 기본값·범위 검사는 CLI의 역할이다.
            "temperature": temperature,
            # CLI의 max_tokens를 Gemini의 maxOutputTokens 필드에 대응시킨다.
            # 이 값은 생성량의 상한이며, 반드시 이만큼 작성하라는 분량 지시는 아니다.
            "maxOutputTokens": max_tokens,
            # 모델의 답을 JSON 형식으로 요청한다. 필수 필드나 내용의 사실성까지
            # 보장하는 설정은 아니므로, 응답 수신 후에도 별도 검사가 필요하다.
            "responseMimeType": "application/json",
        },
    }
    # 2. Request는 전송할 요청의 설계도다. 이 객체를 만드는 순간에는 통신하지 않는다.
    # 모델 이름은 URL 경로에, 인증 Key는 x-goog-api-key 헤더에 넣는다.
    request = Request(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        # quote는 모델 이름의 특수문자가 URL 경로 구조를 바꾸지 않도록 인코딩한다.
        f"{quote(model, safe='')}:generateContent",
        # dict → JSON 문자열 → UTF-8 바이트 순서로 바꿔 HTTP 본문에 담는다.
        # ensure_ascii=False는 한국어를 읽을 수 있는 문자 형태로 유지하는 설정이다.
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        # Content-Type은 본문이 JSON이라는 뜻이며, Key를 요청 URL에 넣지 않는다.
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        # 생성할 자료와 옵션을 본문에 보내야 하므로 POST 요청을 사용한다.
        method="POST",
    )
    try:
        # 3. 실제 통신은 여기서 한 번 실행한다. 재시도 루프나 두 번째 호출은 없다.
        # timeout은 연결·읽기 같은 통신 대기의 제한이며, CLI 전체 실행을 정확히
        # 30초 안에 끝내는 타이머는 아니다. with를 벗어나면 응답 자원을 닫는다.
        with urlopen(request, timeout=30) as response:
            # HTTP 본문 바이트 → UTF-8 문자열 → Python 객체로 읽는다.
            # 아직 AI가 작성한 title 등이 아니라 candidates를 포함한 전체 응답이다.
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        # 4. HTTPError는 URLError의 하위 예외이므로 먼저 잡아 상태 코드를 보존한다.
        # 예외 분기를 반대로 두면 HTTP 인증 오류도 일반 연결 실패로 처리될 수 있다.
        # 상태 코드별 기본 안내를 마련하고, 서버가 준 구체적인 원인이 있으면 대체한다.
        reason = {
            400: "요청 내용·API Key·모델 파라미터를 확인해 주세요.",
            401: "API Key와 인증 설정을 확인해 주세요.",
            403: "API Key의 권한·제한과 지원 지역을 확인해 주세요.",
            404: "모델 이름·API 버전·접근 가능 여부를 확인해 주세요.",
            429: "요청 또는 토큰 사용 한도를 확인해 주세요.",
        }.get(error.code, "Gemini API 요청에 실패했습니다.")
        # 서버 측 오류는 5xx 범위로 묶되, 아래의 응답 본문에 자세한 사유가 있으면 사용한다.
        if 500 <= error.code < 600:
            reason = "Gemini 서버 오류 또는 일시적인 과부하가 발생했습니다."
        try:
            # HTTP 오류에도 JSON 본문이 올 수 있다. 정상 생성 결과와 별도로 읽는다.
            with error:
                body = json.loads(error.read().decode("utf-8"))
            # 서버 오류 본문도 항상 예상 형태라는 보장이 없으므로 dict인지 먼저 확인한다.
            detail = body.get("error") if isinstance(body, dict) else None
            message = detail.get("message") if isinstance(detail, dict) else None
            if isinstance(message, str) and message.strip():
                # 여러 줄인 서버 메시지를 CLI의 한 줄 오류 안내로 정리한다.
                reason = " ".join(message.split())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            # 오류 본문까지 읽을 수 없을 때는 앞에서 정한 상태 코드별 안내를 유지한다.
            pass
        # 오류 문구에도 현재 Key가 들어 있을 수 있으므로 가린 뒤 CLI에 전달한다.
        # from None은 이 오류가 표시될 때 원래 예외의 연쇄 표기를 생략하는 문법이다.
        raise UserError(
            redact(f"Gemini API 오류 (HTTP {error.code}): {reason}", api_key)
        ) from None
    except TimeoutError:
        # 직접 발생한 시간 초과를, 더 넓은 OSError 분기보다 먼저 처리한다.
        raise UserError("Gemini API 요청 시간이 초과되었습니다 (제한 30초).") from None
    except URLError as error:
        # URLError 안에 시간 초과가 담겨 오는 경우도 있다. 그 외에는 DNS 조회나
        # 연결 실패 등 reason에 담긴 원인을 안내한다. URLError도 OSError보다 먼저 잡는다.
        if isinstance(error.reason, TimeoutError):
            reason = "Gemini API 요청 시간이 초과되었습니다 (제한 30초)."
        else:
            reason = f"Gemini API 연결 실패: {error.reason}"
        raise UserError(redact(reason, api_key)) from None
    except OSError as error:
        # 앞선 구체적인 예외에 해당하지 않은 연결·읽기 등의 통신 오류를 처리한다.
        raise UserError(redact(f"Gemini API 통신 오류: {error}", api_key)) from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        # 응답을 받았더라도 UTF-8 텍스트나 JSON으로 해석하지 못하면 사용할 수 없다.
        raise UserError("Gemini API 응답을 UTF-8 JSON으로 읽을 수 없습니다.") from None

    # 5. HTTP 성공만으로 초안이 준비된 것은 아니다. 각 중첩 값의 형태를 순서대로
    # 확인해야, 누락된 응답 때문에 KeyError나 잘못된 인덱스 접근이 발생하지 않는다.
    if not isinstance(result, dict):
        raise UserError("Gemini API 응답 JSON이 객체 형식이 아닙니다.")
    feedback = result.get("promptFeedback")
    if feedback is not None:
        # promptFeedback은 없을 수 있지만, 있다면 객체여야 차단 사유를 확인할 수 있다.
        if not isinstance(feedback, dict):
            raise UserError("Gemini API의 promptFeedback 형식이 올바르지 않습니다.")
        if feedback.get("blockReason"):
            raise UserError(redact(
                f"Gemini API 입력이 차단되었습니다: {feedback['blockReason']}", api_key
            ))
    candidates = result.get("candidates")
    # 후보가 한 개 이상 있는 목록인지 확인한 뒤에만 첫 번째 항목 [0]을 읽는다.
    if not isinstance(candidates, list) or not candidates:
        raise UserError("Gemini API가 생성 후보를 반환하지 않았습니다.")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise UserError("Gemini API 생성 후보의 형식이 올바르지 않습니다.")
    # 6. 이 도구는 첫 후보 하나만 사용하며, finishReason이 STOP인 결과만 채택한다.
    # MAX_TOKENS는 뒤가 잘린 JSON일 수 있어 일부만 복구하지 않고 재실행 안내를 한다.
    finish_reason = candidate.get("finishReason")
    if finish_reason == "MAX_TOKENS":
        raise UserError(
            "Gemini API 응답이 토큰 상한에서 잘렸습니다. "
            "--max-tokens 값을 늘려 다시 실행해 주세요."
        )
    if finish_reason != "STOP":
        # 차단·기타 종료·종료 사유 누락도 정상 초안으로 간주하지 않는다.
        raise UserError(redact(
            f"Gemini API 응답이 정상 완료되지 않았습니다: {finish_reason or '종료 사유 없음'}",
            api_key,
        ))
    # 7. candidate.content.parts에 있는 조각을 순서대로 읽는다.
    # content나 parts가 누락·변형된 응답은 빈 초안으로 조용히 넘기지 않고 오류로 알린다.
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        raise UserError("Gemini API가 본문 텍스트를 반환하지 않았습니다.")
    texts = []
    for part in parts:
        # 각 조각도 객체인지 검사한 뒤 text나 thought 필드를 읽는다.
        if not isinstance(part, dict):
            raise UserError("Gemini API 본문의 parts 형식이 올바르지 않습니다.")
        if part.get("thought") is True:
            # 생각 과정으로 표시된 조각은 최종 커밋·PR의 원문으로 사용하지 않는다.
            continue
        text = part.get("text")
        if text is not None:
            # text가 없는 조각은 건너뛰지만, text 값이 문자열이 아니면 오류로 알린다.
            if not isinstance(text, str):
                raise UserError("Gemini API 본문의 text가 문자열이 아닙니다.")
            texts.append(text)
    # 원래 하나였던 JSON이 여러 조각으로 나뉘었을 수 있으므로 구분자 없이 이어 붙인다.
    # 여기서 임의의 공백이나 줄바꿈을 넣으면 JSON 안의 문자열을 바꿀 수 있다.
    generated = "".join(texts)
    if not generated.strip():
        raise UserError("Gemini API가 비어 있는 본문을 반환했습니다.")
    # 반환값은 생성 텍스트 그대로다. 포맷 함수가 이 문자열을 다시 json.loads()하여
    # summary/title/why 등의 필드를 확인하고, 사용자가 읽을 최종 출력문을 만든다.
    return generated
