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
    def test_returns_current_value_trimmed_without_printing_or_changing_environment(self):
        for value in (FAKE_KEY, f" \t{FAKE_KEY}\n "):
            with self.subTest(value=value):
                environment = {"AI_API_KEY": value}
                stdout = io.StringIO()
                stderr = io.StringIO()
                with patch.dict(os.environ, environment, clear=True), redirect_stdout(stdout), redirect_stderr(stderr):
                    self.assertEqual(load_api_key(), FAKE_KEY)
                    self.assertEqual(dict(os.environ), environment)
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(stderr.getvalue(), "")

    def test_missing_empty_and_whitespace_values_raise_a_clear_error(self):
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
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            with self.subTest(name=name):
                with patch.dict(os.environ, {name: FAKE_KEY}, clear=True):
                    with self.assertRaises(UserError) as raised:
                        load_api_key()
                self.assertEqual(str(raised.exception), MISSING_KEY_MESSAGE)


if __name__ == "__main__":
    unittest.main()
