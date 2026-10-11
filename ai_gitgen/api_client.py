"""Send one Gemini REST request and extract its completed text response."""

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
    """Generate text once; configuration, output formatting and logs belong to callers."""
    payload = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
        },
    }
    request = Request(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(model, safe='')}:generateContent",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
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
            pass
        raise UserError(
            redact(f"Gemini API 오류 (HTTP {error.code}): {reason}", api_key)
        ) from None
    except TimeoutError:
        raise UserError("Gemini API 요청 시간이 초과되었습니다 (제한 30초).") from None
    except URLError as error:
        if isinstance(error.reason, TimeoutError):
            reason = "Gemini API 요청 시간이 초과되었습니다 (제한 30초)."
        else:
            reason = f"Gemini API 연결 실패: {error.reason}"
        raise UserError(redact(reason, api_key)) from None
    except OSError as error:
        raise UserError(redact(f"Gemini API 통신 오류: {error}", api_key)) from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise UserError("Gemini API 응답을 UTF-8 JSON으로 읽을 수 없습니다.") from None

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
    return generated
