"""HTTP 호출을 가짜 응답·오류로 교체해 Gemini 요청 구성과 응답 해석을 검증합니다.

generate_text() 안의 urlopen만 patch로 교체하고, 요청 구성과 응답 검사는 실제 함수를 실행합니다.
BytesIO는 서버 응답처럼 read할 수 있는 메모리 데이터이며, side_effect는 통신 예외를 흉내 냅니다.
실제 Key·네트워크·요금 없이 성공과 실패 처리를 검증하며, 실제 모델의 글쓰기 품질은 검증하지 않습니다.
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
    """Gemini의 정상 종료 응답을 사전으로 만들어 반환합니다.

    parts에는 테스트할 텍스트 조각 목록을 넣으며, 생략하면 커밋 제목 JSON 한 조각을 사용합니다.
    candidates → content → parts 구조와 정상 종료 값 STOP을 준비합니다.
    반환값은 각 테스트에서 JSON 바이트로 바꿔 모의 HTTP 응답에 사용하며, 네트워크는 호출하지 않습니다.
    """
    return {"candidates": [{
        "finishReason": "STOP",
        "content": {"parts": parts if parts is not None else [{"text": '{"title":"docs: 안내 수정"}'}]},
    }]}


class GeminiApiClientTests(unittest.TestCase):
    """generate_text()의 REST 요청 형식, 텍스트 추출, 실패 원인 안내를 검증합니다.

    OPTIONS에는 실제 Key 대신 가짜 값과 비교하기 쉬운 모델·숫자·프롬프트를 넣었습니다.
    테스트마다 urlopen의 반환값이나 예외를 지정하고, 호출 횟수와 최종 반환값·오류를 확인합니다.
    """

    def test_request_contract_and_single_call_without_printing(self):
        """입력 옵션이 한 번의 REST 요청으로 구성되고 정상 텍스트가 반환되는지 확인합니다.

        정상 응답을 BytesIO로 준비한 뒤 urlopen 대신 반환하도록 설정하고 generate_text()를 호출합니다.
        추출된 JSON 문자열, POST 주소·헤더·본문·30초 제한, 요청 1회를 각각 검사합니다.
        Key가 인증 헤더에만 있고 URL·프롬프트·터미널 출력에는 없는지도 확인합니다.
        """
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
        """응답이 여러 조각이어도 사용자에게 보낼 최종 텍스트만 합치는지 확인합니다.

        생각 텍스트, 나뉜 JSON 텍스트, 서명 정보가 섞인 parts를 모의 응답으로 준비합니다.
        generate_text()의 결과가 최종 JSON 조각만 이어진 문자열인지 비교합니다.
        thought나 서명 데이터를 커밋·PR 초안에 섞지 않고 요청도 한 번만 하는지 봅니다.
        """
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
        """정상 텍스트를 찾을 수 없는 응답을 성공으로 처리하지 않는지 확인합니다.

        차단 응답, 빈 candidates, 잘못된 content/parts/text 자료형 등 오류 위치별 자료를 준비합니다.
        각 응답으로 generate_text()를 실행해 UserError가 발생하고 호출은 한 번인지 검사합니다.
        subTest는 여러 입력 중 어느 구조에서 검사가 실패했는지 구분해 줍니다.
        """
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
        """정상 종료 STOP이 아니면 불완전한 텍스트를 결과로 사용하지 않는지 확인합니다.

        응답의 finishReason을 토큰 부족·안전 차단·기타 사유·누락으로 바꿔 generate_text()를 실행합니다.
        모든 경우에 UserError가 나고, MAX_TOKENS에는 잘림 설명과 --max-tokens 안내가 있어야 합니다.
        다른 사유도 오류에 표시되는지와 자동 재요청이 없는지를 함께 검사합니다.
        """
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
        """HTTP 실패 원인을 설명하면서 서버 원문이나 Key를 그대로 출력하지 않는지 확인합니다.

        400·403·429·503·404 오류에 JSON, HTML, 깨진 바이트 등을 넣은 HTTPError를 준비합니다.
        side_effect로 예외를 발생시켜 generate_text()가 상태 번호와 적절한 원인을 UserError로 전달하는지 봅니다.
        Key 마스킹·HTML 원문 제외·요청 1회도 검사해 오류 처리 중 정보 노출과 재시도를 막습니다.
        """
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
        """HTTP 통신 관련 예외를 이해할 수 있는 오류로 바꾸는지 확인합니다.

        URLError, 그 안에 담긴 TimeoutError, 직접 발생한 TimeoutError와 OSError를 준비합니다.
        generate_text() 실행 시 각 원인이 연결 실패·시간 초과·통신 오류로 안내되는지 검사합니다.
        오류 원문에 섞인 가짜 Key가 사라지고 요청은 한 번만 시도되는지도 확인합니다.
        """
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
        """응답의 문자 해석이나 JSON 파싱이 실패했을 때 안내 오류로 바꾸는지 확인합니다.

        닫히지 않은 JSON 바이트와 UTF-8로 읽을 수 없는 바이트를 각각 응답으로 준비합니다.
        generate_text()가 'UTF-8 JSON'을 포함한 UserError를 내는지와 요청 1회를 검사합니다.
        내부 디코딩 예외가 그대로 드러나거나 잘못된 응답을 성공으로 넘기지 않게 합니다.
        """
        for body in (b"{broken", b"\xff"):
            with self.subTest(body=body):
                with patch("ai_gitgen.api_client.urlopen", return_value=io.BytesIO(body)) as open_url:
                    with self.assertRaisesRegex(UserError, "UTF-8 JSON"):
                        generate_text(**OPTIONS)
                    open_url.assert_called_once()


if __name__ == "__main__":
    unittest.main()
