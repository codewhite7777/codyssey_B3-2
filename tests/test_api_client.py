"""HTTP 호출을 가짜 응답·오류로 교체해 Gemini 요청 구성과 응답 해석을 검증합니다.

실제 API Key와 네트워크 없이 성공·실패 상황을 반복해서 확인하는 테스트입니다.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from ai_gitgen.api_client import generate_text
from ai_gitgen.errors import UserError


FAKE_KEY = "FAKE_KEY_FOR_TEST"
OPTIONS = {
    "api_key": FAKE_KEY,
    "model": "gemini-3.1-flash-lite",
    "temperature": 0.3,
    "max_tokens": 987,
    "system_instruction": "한국어 커밋 초안을 JSON으로 작성하세요.",
    "prompt": "README.md의 실행 안내를 수정했습니다.",
}


def completed_response(parts=None):
    """정상 종료된 Gemini 응답 구조를 만들며, parts를 주면 그 내용을 응답에 넣습니다."""
    return {"candidates": [{
        "finishReason": "STOP",
        "content": {"parts": parts if parts is not None else [{"text": '{"title":"docs: 안내 수정"}'}]},
    }]}


class GeminiApiClientTests(unittest.TestCase):
    """generate_text의 요청 형식·텍스트 추출·실패 원인 안내를 검증합니다."""

    def test_request_contract_and_single_call_without_printing(self):
        """정상 응답에서 텍스트를 추출하고, 요청 URL·헤더·본문·호출 횟수가 맞는지 확인합니다."""
        # BytesIO는 네트워크 응답처럼 read할 수 있는 메모리 데이터이며 실제 전송은 하지 않습니다.
        response = io.BytesIO(json.dumps(completed_response()).encode("utf-8"))
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("ai_gitgen.api_client.urlopen", return_value=response) as open_url:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = generate_text(**OPTIONS)
        self.assertEqual(result, '{"title":"docs: 안내 수정"}')
        open_url.assert_called_once()
        # 교체한 urlopen이 받은 Request를 꺼내 함수 인자가 REST 요청에 어떻게 반영됐는지 봅니다.
        request = open_url.call_args.args[0]
        self.assertEqual(open_url.call_args.kwargs, {"timeout": 30})
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            request.full_url,
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-3.1-flash-lite:generateContent",
        )
        headers = {name.lower(): value for name, value in request.header_items()}
        self.assertEqual(headers["x-goog-api-key"], FAKE_KEY)
        self.assertEqual(headers["content-type"], "application/json")
        # Key는 인증 헤더로만 보내고 URL·프롬프트·터미널 출력에는 나타나지 않아야 합니다.
        self.assertNotIn(FAKE_KEY, request.full_url)
        self.assertNotIn(FAKE_KEY, request.data.decode("utf-8"))
        self.assertEqual(json.loads(request.data), {
            "systemInstruction": {"parts": [{"text": OPTIONS["system_instruction"]}]},
            "contents": [{"role": "user", "parts": [{"text": OPTIONS["prompt"]}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 987,
                "responseMimeType": "application/json",
            },
        })
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_combines_text_parts_and_omits_thoughts(self):
        """여러 응답 조각 중 최종 텍스트만 합치고 thought와 서명 정보는 제외하는지 확인합니다."""
        body = completed_response([
            {"text": "분석 중인 내용", "thought": True},
            {"text": '{"title":'},
            {"thoughtSignature": "opaque-signature"},
            {"text": '"docs: 실행 안내 수정"}'},
        ])
        with patch("ai_gitgen.api_client.urlopen", return_value=io.BytesIO(json.dumps(body).encode())) as open_url:
            self.assertEqual(generate_text(**OPTIONS), '{"title":"docs: 실행 안내 수정"}')
            open_url.assert_called_once()

    def test_rejects_blocked_empty_and_malformed_response_data(self):
        """차단·빈 응답·잘못된 자료형을 정상 생성 결과로 받아들이지 않는지 확인합니다."""
        # 바깥 응답 객체부터 candidates, content, parts, text까지 잘못될 수 있는 위치를 나눕니다.
        cases = [
            None,
            [],
            {},
            {"promptFeedback": "invalid"},
            {"promptFeedback": {"blockReason": "SAFETY"}},
            {"candidates": []},
            {"candidates": "invalid"},
            {"candidates": [None]},
            {"candidates": [{"finishReason": "STOP"}]},
            {"candidates": [{"finishReason": "STOP", "content": []}]},
            {"candidates": [{"finishReason": "STOP", "content": {"parts": "invalid"}}]},
            completed_response([]),
            completed_response([None]),
            completed_response([{"text": 123}]),
            completed_response([{"text": " \n "}]),
            completed_response([{"text": "생각만 있음", "thought": True}]),
        ]
        # subTest는 어떤 입력이 실패했는지 구분하며 각 입력에 대해 요청 시도는 한 번이어야 합니다.
        for body in cases:
            with self.subTest(body=body):
                with patch("ai_gitgen.api_client.urlopen", return_value=io.BytesIO(json.dumps(body).encode())) as open_url:
                    with self.assertRaises(UserError):
                        generate_text(**OPTIONS)
                    open_url.assert_called_once()

    def test_rejects_truncated_and_other_finish_reasons(self):
        """정상 종료 STOP이 아닌 응답을 거절하고 토큰 부족이면 설정 안내도 제공하는지 확인합니다."""
        for reason in ("MAX_TOKENS", "SAFETY", "RECITATION", None):
            with self.subTest(reason=reason):
                body = completed_response()
                body["candidates"][0]["finishReason"] = reason
                with patch("ai_gitgen.api_client.urlopen", return_value=io.BytesIO(json.dumps(body).encode())) as open_url:
                    with self.assertRaises(UserError) as raised:
                        generate_text(**OPTIONS)
                    open_url.assert_called_once()
                message = str(raised.exception)
                if reason == "MAX_TOKENS":
                    self.assertIn("--max-tokens", message)
                    self.assertIn("잘렸습니다", message)
                else:
                    self.assertIn(reason or "종료 사유 없음", message)

    def test_http_errors_include_status_and_mask_key_without_retry(self):
        """HTTP 오류의 상태·원인을 안내하되 Key나 원문 HTML을 드러내거나 재시도하지 않는지 확인합니다."""
        # 서버의 JSON 오류를 읽을 수 있는 경우와 HTML·깨진 문자처럼 읽을 수 없는 경우를 준비합니다.
        cases = [
            (400, json.dumps({"error": {"message": f"API key not valid: {FAKE_KEY}"}}).encode(), "API key not valid: [REDACTED]"),
            (403, b'{"error":{"message":"Permission denied"}}', "Permission denied"),
            (429, b'{"error":{"message":"Quota exceeded"}}', "Quota exceeded"),
            (503, b"<html>Service unavailable</html>", "서버 오류"),
            (404, b"\xff", "모델 이름"),
            (400, b'{"error":[]}', "요청 내용"),
        ]
        for status, body, expected in cases:
            with self.subTest(status=status, body=body):
                error = HTTPError("https://example.invalid", status, "HTTP failure", {}, io.BytesIO(body))
                # side_effect로 통신 중 오류를 발생시켜 실제 서버 장애 없이 예외 처리를 확인합니다.
                with patch("ai_gitgen.api_client.urlopen", side_effect=error) as open_url:
                    with self.assertRaises(UserError) as raised:
                        generate_text(**OPTIONS)
                    open_url.assert_called_once()
                message = str(raised.exception)
                self.assertIn(f"HTTP {status}", message)
                self.assertIn(expected, message)
                self.assertNotIn(FAKE_KEY, message)
                self.assertNotIn("<html>", message)

    def test_network_errors_are_explained_without_key_or_retry(self):
        """연결 실패·타임아웃·읽기 오류를 구분하고 오류 문장의 Key를 가리는지 확인합니다."""
        cases = [
            (URLError(f"Connection failed: {FAKE_KEY}"), "연결 실패"),
            (URLError(TimeoutError("timed out")), "시간이 초과"),
            (TimeoutError("timed out"), "시간이 초과"),
            (OSError(f"Read failed: {FAKE_KEY}"), "통신 오류"),
        ]
        for error, expected in cases:
            with self.subTest(error=error):
                with patch("ai_gitgen.api_client.urlopen", side_effect=error) as open_url:
                    with self.assertRaises(UserError) as raised:
                        generate_text(**OPTIONS)
                    open_url.assert_called_once()
                self.assertIn(expected, str(raised.exception))
                self.assertNotIn(FAKE_KEY, str(raised.exception))

    def test_rejects_invalid_json_and_utf8(self):
        """응답이 깨진 JSON이거나 UTF-8이 아니면 해석 실패를 설명하는 오류가 나는지 확인합니다."""
        for body in (b"{broken", b"\xff"):
            with self.subTest(body=body):
                with patch("ai_gitgen.api_client.urlopen", return_value=io.BytesIO(body)) as open_url:
                    with self.assertRaisesRegex(UserError, "UTF-8 JSON"):
                        generate_text(**OPTIONS)
                    open_url.assert_called_once()


if __name__ == "__main__":
    unittest.main()
