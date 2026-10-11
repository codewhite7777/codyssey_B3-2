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
    return {"candidates": [{
        "finishReason": "STOP",
        "content": {"parts": parts if parts is not None else [{"text": '{"title":"docs: 안내 수정"}'}]},
    }]}


class GeminiApiClientTests(unittest.TestCase):
    def test_request_contract_and_single_call_without_printing(self):
        response = io.BytesIO(json.dumps(completed_response()).encode("utf-8"))
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("ai_gitgen.api_client.urlopen", return_value=response) as open_url:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = generate_text(**OPTIONS)
        self.assertEqual(result, '{"title":"docs: 안내 수정"}')
        open_url.assert_called_once()
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
        for body in cases:
            with self.subTest(body=body):
                with patch("ai_gitgen.api_client.urlopen", return_value=io.BytesIO(json.dumps(body).encode())) as open_url:
                    with self.assertRaises(UserError):
                        generate_text(**OPTIONS)
                    open_url.assert_called_once()

    def test_rejects_truncated_and_other_finish_reasons(self):
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
        for body in (b"{broken", b"\xff"):
            with self.subTest(body=body):
                with patch("ai_gitgen.api_client.urlopen", return_value=io.BytesIO(body)) as open_url:
                    with self.assertRaisesRegex(UserError, "UTF-8 JSON"):
                        generate_text(**OPTIONS)
                    open_url.assert_called_once()


if __name__ == "__main__":
    unittest.main()
