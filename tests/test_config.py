"""환경변수를 임시로 교체하여 API Key 읽기·누락 처리·출력 금지를 검증합니다.

실제 Key나 Gemini 요청 없이 load_api_key()만 호출하는 단위 테스트입니다.
patch.dict는 테스트 동안의 환경을 지정하고 종료 후 원래 환경으로 복구합니다.
표준 출력과 오류 출력도 메모리로 받아, Key를 읽는 함수가 값을 노출하지 않는지 봅니다.
"""

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
    "README.md의 'API Key 입력' 안내에 따라 같은 터미널에서 설정해 주세요."
)


class ApiKeyConfigurationTests(unittest.TestCase):
    """AI_API_KEY 환경변수 하나만 읽는 규칙과 잘못된 설정의 처리를 확인합니다.

    각 경우의 환경을 명시적으로 준비하므로 실행한 컴퓨터의 실제 설정에 의존하지 않습니다.
    성공 시 반환값, 실패 시 UserError의 안내 문장, 환경과 출력의 보존 여부를 비교합니다.
    """

    def test_returns_current_value_trimmed_without_printing_or_changing_environment(self):
        """Key를 읽을 때 주변 공백만 제거하고 환경과 출력은 건드리지 않는지 확인합니다.

        가짜 Key 그대로인 경우와 앞뒤 공백·줄바꿈이 있는 경우를 각각 준비합니다.
        load_api_key()를 실행해 반환값은 같은 Key인지, 환경의 원래 값은 유지되는지 봅니다.
        두 출력이 비어 있는지도 검사하여 Key를 읽는 과정에서 비밀값이 표시되지 않게 합니다.
        """
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
        """사용할 수 없는 세 가지 환경변수 상태를 모두 Key 누락으로 처리하는지 확인합니다.

        변수가 없는 경우, 빈 문자열, 공백만 있는 값을 각각 설정하고 load_api_key()를 부릅니다.
        assertRaises로 UserError 발생을 확인한 뒤 안내 문장이 MISSING_KEY_MESSAGE와 같은지 봅니다.
        함수가 환경을 고치거나 직접 출력하지 않는지도 검사해 오류 전달과 화면 출력을 구분합니다.
        """
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
        """다른 이름의 Key를 AI_API_KEY 대신 몰래 사용하지 않는지 확인합니다.

        GEMINI_API_KEY 또는 GOOGLE_API_KEY만 있는 환경에서 load_api_key()를 실행합니다.
        값이 있더라도 지정한 이름의 변수가 없으므로 같은 누락 오류가 나야 합니다.
        문서에 안내한 설정 방법과 실제 코드가 읽는 이름을 일치시키기 위한 검사입니다.
        """
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            with self.subTest(name=name):
                with patch.dict(os.environ, {name: FAKE_KEY}, clear=True):
                    with self.assertRaises(UserError) as raised:
                        load_api_key()
                self.assertEqual(str(raised.exception), MISSING_KEY_MESSAGE)


if __name__ == "__main__":
    unittest.main()
