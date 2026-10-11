"""환경변수를 임시로 교체하여 API Key 읽기·누락 처리·출력 금지를 검증합니다."""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
import unittest
from unittest.mock import patch

from ai_gitgen.config import load_api_key
from ai_gitgen.errors import UserError


FAKE_KEY = "FAKE_KEY_FOR_TEST"
MISSING_KEY_MESSAGE = (
    "AI_API_KEY 환경변수가 설정되지 않았습니다. "
    "READ.md의 3.3절에 따라 같은 터미널에서 설정해 주세요."
)


class ApiKeyConfigurationTests(unittest.TestCase):
    """실제 Key 대신 가짜 값으로 환경변수 설정 규칙을 확인합니다."""

    def test_returns_current_value_trimmed_without_printing_or_changing_environment(self):
        """가짜 Key의 주변 공백을 제거해 읽되 환경변수를 바꾸거나 값을 출력하지 않는지 확인합니다."""
        for value in (FAKE_KEY, f" \t{FAKE_KEY}\n "):
            with self.subTest(value=value):
                environment = {"AI_API_KEY": value}
                stdout = io.StringIO()
                stderr = io.StringIO()
                # 환경을 이 경우의 값으로 교체하고 출력도 메모리로 받아 유출 여부를 검사합니다.
                # with 블록이 끝나면 원래 환경변수와 출력 대상은 자동 복구됩니다.
                with patch.dict(os.environ, environment, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
                    self.assertEqual(load_api_key(), FAKE_KEY)
                    self.assertEqual(dict(os.environ), environment)
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(stderr.getvalue(), "")

    def test_missing_empty_and_whitespace_values_raise_a_clear_error(self):
        """미설정·빈 문자열·공백만 있는 값을 모두 같은 Key 누락 오류로 처리하는지 확인합니다."""
        for environment in ({}, {"AI_API_KEY": ""}, {"AI_API_KEY": " \t\n "}):
            with self.subTest(environment=environment):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with patch.dict(os.environ, environment, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
                    with self.assertRaises(UserError) as raised:
                        load_api_key()
                    self.assertEqual(dict(os.environ), environment)
                self.assertEqual(str(raised.exception), MISSING_KEY_MESSAGE)
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(stderr.getvalue(), "")

    def test_other_environment_variable_names_are_not_used_as_fallbacks(self):
        """다른 이름의 Key가 있어도 AI_API_KEY를 대신해 사용하지 않는지 확인합니다."""
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            with self.subTest(name=name):
                with patch.dict(os.environ, {name: FAKE_KEY}, clear=True):
                    with self.assertRaises(UserError) as raised:
                        load_api_key()
                self.assertEqual(str(raised.exception), MISSING_KEY_MESSAGE)


if __name__ == "__main__":
    unittest.main()
