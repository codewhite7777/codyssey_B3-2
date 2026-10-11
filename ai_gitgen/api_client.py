"""Gemini REST API에 한 번 요청하고, 정상 완료된 생성 텍스트를 꺼낸다.

환경변수 읽기·로그·초안 형식 검사는 호출자에게 맡긴다. HTTP 통신 오류와
API 응답 구조의 오류는 UserError로 바꿔 cli.main()이 원인을 안내하게 한다.
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
    """키·모델·생성 옵션·작성 규칙·변경 자료로 요청하고 생성 문자열을 반환한다.

    system_instruction은 작성 규칙, prompt는 이미 준비된 변경 자료다.
    max_tokens는 요청의 maxOutputTokens에 전달한다. 인자 앞의 *는 호출 시
    api_key=...처럼 인자 이름을 적게 한다. 자동 재시도나 환경변수 변경은 없다.
    통신 실패·잘못된 응답·차단·미완료·빈 본문은 UserError로 알린다.
    반환 문자열 안의 title/summary 등 초안 필드는 formatting.py가 검사한다.
    """
    # 1. 작성 규칙과 사용자 자료를 분리하고, 모델에게 JSON 형식으로 답하도록 요청한다.
    # responseMimeType만으로 필수 필드나 내용의 정확성까지 보장되지는 않는다.
    payload = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
        },
    }
    # 2. URL에 모델을 넣고, 인증 키는 헤더에 담는다. JSON 본문은 UTF-8 바이트로 전송한다.
    request = Request(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(model, safe='')}:generateContent",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        # 3. HTTP 요청을 한 번 실행한다. 여기서 읽는 JSON은 Gemini의 전체 응답이다.
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        # 4. 상태 코드별 기본 안내를 준비하고, 서버가 제공한 구체적인 원인이 있으면 사용한다.
        reason = {
            400: "요청 내용·API Key·모델 파라미터를 확인해 주세요.",
            401: "API Key와 인증 설정을 확인해 주세요.",
            403: "API Key의 권한·제한과 지원 지역을 확인해 주세요.",
            404: "모델 이름·API 버전·접근 가능 여부를 확인해 주세요.",
            429: "요청 또는 토큰 사용 한도를 확인해 주세요.",
        }.get(error.code, "Gemini API 요청에 실패했습니다.")
        if 500 <= error.code < 600:
            reason = "Gemini 서버 오류 또는 일시적인 과부하가 발생했습니다."
        try:
            with error:
                body = json.loads(error.read().decode("utf-8"))
            detail = body.get("error") if isinstance(body, dict) else None
            message = detail.get("message") if isinstance(detail, dict) else None
            if isinstance(message, str) and message.strip():
                reason = " ".join(message.split())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            # 오류 본문까지 읽을 수 없을 때는 앞에서 정한 상태 코드별 안내를 유지한다.
            pass
        raise UserError(
            redact(f"Gemini API 오류 (HTTP {error.code}): {reason}", api_key)
        ) from None
    except TimeoutError:
        raise UserError("Gemini API 요청 시간이 초과되었습니다 (제한 30초).") from None
    except URLError as error:
        # URLError 안에 담긴 시간 초과와 DNS·연결 실패 등의 원인을 구분한다.
        if isinstance(error.reason, TimeoutError):
            reason = "Gemini API 요청 시간이 초과되었습니다 (제한 30초)."
        else:
            reason = f"Gemini API 연결 실패: {error.reason}"
        raise UserError(redact(reason, api_key)) from None
    except OSError as error:
        raise UserError(redact(f"Gemini API 통신 오류: {error}", api_key)) from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise UserError("Gemini API 응답을 UTF-8 JSON으로 읽을 수 없습니다.") from None

    # 5. HTTP 성공 이후에도 객체 형식·입력 차단 여부·생성 후보 유무를 확인한다.
    if not isinstance(result, dict):
        raise UserError("Gemini API 응답 JSON이 객체 형식이 아닙니다.")
    feedback = result.get("promptFeedback")
    if feedback is not None:
        if not isinstance(feedback, dict):
            raise UserError("Gemini API의 promptFeedback 형식이 올바르지 않습니다.")
        if feedback.get("blockReason"):
            raise UserError(redact(
                f"Gemini API 입력이 차단되었습니다: {feedback['blockReason']}", api_key
            ))
    candidates = result.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise UserError("Gemini API가 생성 후보를 반환하지 않았습니다.")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise UserError("Gemini API 생성 후보의 형식이 올바르지 않습니다.")
    # 6. 첫 후보가 STOP으로 완료되어야 사용한다. 토큰 상한에서 잘린 초안은 오류로 알린다.
    finish_reason = candidate.get("finishReason")
    if finish_reason == "MAX_TOKENS":
        raise UserError(
            "Gemini API 응답이 토큰 상한에서 잘렸습니다. "
            "--max-tokens 값을 늘려 다시 실행해 주세요."
        )
    if finish_reason != "STOP":
        raise UserError(redact(
            f"Gemini API 응답이 정상 완료되지 않았습니다: {finish_reason or '종료 사유 없음'}",
            api_key,
        ))
    # 7. 본문의 여러 text 조각을 합친다. thought=True로 표시된 조각은 최종 답변에서 제외한다.
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        raise UserError("Gemini API가 본문 텍스트를 반환하지 않았습니다.")
    texts = []
    for part in parts:
        if not isinstance(part, dict):
            raise UserError("Gemini API 본문의 parts 형식이 올바르지 않습니다.")
        if part.get("thought") is True:
            continue
        text = part.get("text")
        if text is not None:
            if not isinstance(text, str):
                raise UserError("Gemini API 본문의 text가 문자열이 아닙니다.")
            texts.append(text)
    generated = "".join(texts)
    if not generated.strip():
        raise UserError("Gemini API가 비어 있는 본문을 반환했습니다.")
    # JSON으로 요청한 생성 텍스트를 반환한다. 실제 JSON 형식·필드는 포맷 함수가 검사한다.
    return generated
