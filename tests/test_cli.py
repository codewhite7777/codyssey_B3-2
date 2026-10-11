from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import subprocess
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from ai_gitgen.cli import main
from tests.helpers import RepositoryTestCase


FAKE_KEY = "FAKE_KEY_FOR_TEST"
CONFIRMED_MESSAGE = "[INFO] AI_API_KEY 환경변수 설정을 확인했습니다."
MASKING_MESSAGE = "[INFO] 현재 API Key 마스킹 적용 완료: diff·파일명·브랜치"
MISSING_KEY_MESSAGE = (
    "AI_API_KEY 환경변수가 설정되지 않았습니다. "
    "READ.md의 3.3절에 따라 같은 터미널에서 설정해 주세요."
)
PR_PENDING_MESSAGE = (
    "PR 초안 생성은 다음 단계입니다. 현재는 commit 명령을 사용해 주세요."
)


class ApiKeyCliTests(RepositoryTestCase):
    def run_cli(self, command, key=None, *options, error=None, generated_text=None):
        environment = os.environ.copy()
        # Every invocation uses a fake key or no key, and HTTP is always mocked.
        for name in ("AI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            environment.pop(name, None)
        if key is not None:
            environment["AI_API_KEY"] = key
        if generated_text is None:
            generated_text = json.dumps(
                {"summary": ["app.py의 기본값 변경"], "title": "fix: 기본값 변경"},
                ensure_ascii=False,
            )
        response = json.dumps({
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": generated_text}]},
            }],
        }, ensure_ascii=False).encode("utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        arguments = [command, *options]
        previous_directory = os.getcwd()
        with (
            patch.dict(os.environ, environment, clear=True),
            patch(
                "ai_gitgen.api_client.urlopen",
                return_value=io.BytesIO(response), side_effect=error,
            ) as self.http_mock,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            try:
                os.chdir(self.root)
                try:
                    returncode = main(arguments)
                except SystemExit as exit_error:
                    returncode = exit_error.code
            finally:
                os.chdir(previous_directory)
        return subprocess.CompletedProcess(
            ["main.py", *arguments], returncode, stdout.getvalue(), stderr.getvalue(),
        )

    def request_data(self):
        request = self.http_mock.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        prompt = json.loads(payload["contents"][0]["parts"][0]["text"])
        return request, payload, prompt

    def test_generation_commands_report_missing_keys_without_a_traceback(self):
        self.baseline()
        (self.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        for command in ("commit", "pr"):
            for key in (None, "", " \t "):
                with self.subTest(command=command, key=key):
                    result = self.run_cli(command, key)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("[ERROR] " + MISSING_KEY_MESSAGE, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertNotIn(CONFIRMED_MESSAGE, result.stdout)
                    self.assertNotIn(MASKING_MESSAGE, result.stdout)
                    self.assertNotIn('"app.py"', result.stdout)
                    self.assertIn("[INFO] Gemini API 호출 횟수: 0회", result.stdout)
                    self.http_mock.assert_not_called()

    def test_configured_key_generates_commit_and_keeps_pr_pending(self):
        self.baseline()
        (self.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        for command in ("commit", "pr"):
            for key in (FAKE_KEY, f" \t{FAKE_KEY} "):
                with self.subTest(command=command, key=key):
                    result = self.run_cli(command, key)
                    self.assertIn(CONFIRMED_MESSAGE, result.stdout)
                    self.assertIn(MASKING_MESSAGE, result.stdout)
                    self.assertNotIn(MISSING_KEY_MESSAGE, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertNotIn(FAKE_KEY, result.stdout + result.stderr)
                    if command == "commit":
                        self.assertEqual(result.returncode, 0)
                        self.assertEqual(result.stderr, "")
                        self.assertIn("[DONE] 커밋 메시지 생성 완료", result.stdout)
                        self.assertIn("--- Change Summary ---\n- app.py의 기본값 변경", result.stdout)
                        self.assertIn("--- Commit Message ---\nfix: 기본값 변경", result.stdout)
                        self.assertIn("[INFO] Gemini API 호출 횟수: 1회", result.stdout)
                        self.http_mock.assert_called_once()
                        request, payload, prompt = self.request_data()
                        self.assertTrue(request.full_url.endswith(
                            "/models/gemini-3.1-flash-lite:generateContent"
                        ))
                        self.assertEqual(payload["generationConfig"]["temperature"], 1.0)
                        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 4096)
                        self.assertFalse(prompt["partial_diff"])
                    else:
                        self.assertEqual(result.returncode, 1)
                        self.assertIn("[ERROR] " + PR_PENDING_MESSAGE, result.stderr)
                        self.assertIn("[INFO] Gemini API 호출 횟수: 0회", result.stdout)
                        self.http_mock.assert_not_called()

    def test_generation_commands_mask_tracked_and_untracked_file_names(self):
        tracked_name = f"tracked-{FAKE_KEY}.py"
        untracked_name = f"new-{FAKE_KEY}.py"
        self.baseline(name=tracked_name)
        (self.root / tracked_name).write_text(
            "value = 'FAKE_KEY_FOR_TEST'\n", encoding="utf-8",
        )
        (self.root / untracked_name).write_text("value = 2\n", encoding="utf-8")

        for command in ("commit", "pr"):
            with self.subTest(command=command):
                result = self.run_cli(command, FAKE_KEY)
                self.assertEqual(result.returncode, 0 if command == "commit" else 1)
                self.assertIn(MASKING_MESSAGE, result.stdout)
                self.assertIn('"tracked-[REDACTED].py"', result.stdout)
                self.assertIn('"new-[REDACTED].py"', result.stdout)
                self.assertNotIn(FAKE_KEY, result.stdout + result.stderr)
                if command == "commit":
                    self.http_mock.assert_called_once()
                    self.assertNotIn(FAKE_KEY.encode(), self.http_mock.call_args.args[0].data)
                else:
                    self.http_mock.assert_not_called()

    def test_safe_mode_limits_combined_staged_and_unstaged_request_input(self):
        tracked_name = f"app-{FAKE_KEY}.py"
        self.baseline(name=tracked_name)
        staged_text = "value = 1\n" + "".join(
            f"# staged {number}: {FAKE_KEY}\n" for number in range(100)
        )
        (self.root / tracked_name).write_text(staged_text, encoding="utf-8")
        self.git("add", "--", tracked_name)
        (self.root / tracked_name).write_text(
            staged_text + "".join(
                f"# unstaged {number}: {FAKE_KEY}\n" for number in range(120)
            ), encoding="utf-8",
        )
        warning = "[WARN] 전송 제한으로 일부 변경만 AI 입력에 포함합니다."

        for command in ("commit", "pr"):
            with self.subTest(command=command):
                limited = self.run_cli(command, FAKE_KEY, "--safe-mode")
                if command == "commit":
                    self.http_mock.assert_called_once()
                    _, _, prompt = self.request_data()
                    self.assertTrue(prompt["partial_diff"])
                    self.assertEqual(len(prompt["files"]), 1)
                    file_input = prompt["files"][0]
                    self.assertTrue(file_input["staged_diff"])
                    self.assertTrue(file_input["unstaged_diff"])
                    self.assertEqual(sum(
                        len(item[field].splitlines())
                        for item in prompt["files"]
                        for field in ("staged_diff", "unstaged_diff")
                    ), 200)
                    self.assertNotIn(FAKE_KEY, json.dumps(prompt))
                else:
                    self.http_mock.assert_not_called()

                normal = self.run_cli(command, FAKE_KEY)
                if command == "commit":
                    self.http_mock.assert_called_once()
                    _, _, prompt = self.request_data()
                    self.assertFalse(prompt["partial_diff"])
                    self.assertGreater(sum(
                        len(item[field].splitlines())
                        for item in prompt["files"]
                        for field in ("staged_diff", "unstaged_diff")
                    ), 200)
                else:
                    self.http_mock.assert_not_called()

                self.assertIn(
                    "[INFO] 안전 모드 적용: 1개 파일, 200줄 (최대 10개 파일·200줄)",
                    limited.stdout,
                )
                self.assertIn(warning, limited.stdout)
                self.assertNotIn("[INFO] 안전 모드 적용:", normal.stdout)
                self.assertNotIn(warning, normal.stdout)
                for result in (limited, normal):
                    self.assertEqual(result.returncode, 0 if command == "commit" else 1)
                    self.assertIn(MASKING_MESSAGE, result.stdout)
                    self.assertIn('"app-[REDACTED].py"', result.stdout)
                    self.assertNotIn(FAKE_KEY, result.stdout + result.stderr)

    def test_inspect_with_tracked_changes_does_not_require_a_key(self):
        self.baseline()
        (self.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        result = self.run_cli("inspect")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Git status 수집 완료", result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertNotIn(CONFIRMED_MESSAGE, result.stdout)
        self.assertNotIn(MASKING_MESSAGE, result.stdout)
        self.http_mock.assert_not_called()

    def test_clean_repository_does_not_require_a_key(self):
        self.baseline()
        for command in ("inspect", "commit", "pr"):
            with self.subTest(command=command):
                result = self.run_cli(command)
                self.assertEqual(result.returncode, 0)
                self.assertIn("변경 사항이 없습니다", result.stdout)
                self.assertEqual(result.stderr, "")
                self.assertNotIn(CONFIRMED_MESSAGE, result.stdout)
                self.assertNotIn(MASKING_MESSAGE, result.stdout)
                self.http_mock.assert_not_called()
                if command != "inspect":
                    self.assertIn("[INFO] Gemini API 호출 횟수: 0회", result.stdout)

    def test_untracked_only_repository_does_not_require_a_key(self):
        (self.root / "new.py").write_text("value = 1\n", encoding="utf-8")
        for command in ("inspect", "commit", "pr"):
            with self.subTest(command=command):
                result = self.run_cli(command)
                self.assertEqual(result.returncode, 0)
                self.assertIn("추적되지 않은 새 파일만 있습니다", result.stdout)
                self.assertIn("git add", result.stdout)
                self.assertEqual(result.stderr, "")
                self.assertNotIn(CONFIRMED_MESSAGE, result.stdout)
                self.assertNotIn(MASKING_MESSAGE, result.stdout)
                self.http_mock.assert_not_called()
                if command != "inspect":
                    self.assertIn("[INFO] Gemini API 호출 횟수: 0회", result.stdout)

    def test_options_context_and_redacted_diff_reach_the_gemini_request(self):
        tracked_name = f"app-{FAKE_KEY}.py"
        self.baseline(name=tracked_name)
        self.git("branch", "-m", f"feature-{FAKE_KEY}")
        (self.root / tracked_name).write_text(
            f"value = '{FAKE_KEY}'\n", encoding="utf-8",
        )
        result = self.run_cli(
            "commit", f" {FAKE_KEY} ",
            "--model", "gemini-test-model", "--temperature", "0.2",
            "--max-tokens", "512", "--context", f"설정값 교체: {FAKE_KEY}",
        )
        self.assertEqual(result.returncode, 0)
        self.http_mock.assert_called_once()
        request, payload, prompt = self.request_data()
        self.assertEqual(request.full_url,
            "https://generativelanguage.googleapis.com/v1beta/"
            "models/gemini-test-model:generateContent")
        self.assertEqual(request.get_method(), "POST")
        headers = {name.lower(): value for name, value in request.header_items()}
        self.assertEqual(headers["x-goog-api-key"], FAKE_KEY)
        self.assertIn("application/json", headers["content-type"])
        self.assertEqual(self.http_mock.call_args.kwargs["timeout"], 30)
        self.assertEqual(payload["generationConfig"]["temperature"], 0.2)
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 512)
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertTrue(payload["systemInstruction"]["parts"][0]["text"])
        self.assertEqual(prompt["branch"], "feature-[REDACTED]")
        self.assertEqual(prompt["context"], "설정값 교체: [REDACTED]")
        self.assertEqual(prompt["files"][0]["path"], "app-[REDACTED].py")
        self.assertIn("+value = '[REDACTED]'", prompt["files"][0]["unstaged_diff"])
        self.assertNotIn(FAKE_KEY, request.full_url)
        self.assertNotIn(FAKE_KEY.encode(), request.data)
        self.assertNotIn(FAKE_KEY, result.stdout + result.stderr)

    def test_request_errors_report_the_cause_without_retrying_or_exposing_the_key(self):
        self.baseline()
        (self.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        errors = (
            (HTTPError(
                "https://generativelanguage.googleapis.com/", 403, "Forbidden", {},
                io.BytesIO(json.dumps({
                    "error": {"message": f"권한 오류: {FAKE_KEY}"},
                }, ensure_ascii=False).encode("utf-8")),
            ), "403", "권한 오류"),
            (URLError("테스트 연결 실패"), "연결", "테스트 연결 실패"),
        )
        for error, category, cause in errors:
            with self.subTest(error=type(error).__name__):
                result = self.run_cli("commit", FAKE_KEY, error=error)
                self.assertEqual(result.returncode, 1)
                self.http_mock.assert_called_once()
                self.assertIn("[INFO] Gemini API 호출 횟수: 1회", result.stdout)
                self.assertIn("[ERROR]", result.stderr)
                self.assertIn(category, result.stderr)
                self.assertIn(cause, result.stderr)
                self.assertNotIn("[DONE]", result.stdout)
                self.assertNotIn("Traceback", result.stderr)
                self.assertNotIn(FAKE_KEY, result.stdout + result.stderr)

    def test_invalid_options_stop_before_a_request(self):
        self.baseline()
        (self.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        invalid_options = (
            ("--model", "../invalid"),
            ("--temperature", "nan"),
            ("--temperature", "inf"),
            ("--temperature", "-0.1"),
            ("--temperature", "2.1"),
            ("--max-tokens", "0"),
            ("--max-tokens", "1.5"),
        )
        for options in invalid_options:
            with self.subTest(options=options):
                result = self.run_cli("commit", FAKE_KEY, *options)
                self.assertEqual(result.returncode, 2)
                self.http_mock.assert_not_called()
                self.assertNotEqual(result.stderr, "")
                self.assertNotIn("Traceback", result.stderr)
                self.assertNotIn("[DONE]", result.stdout)

    def test_invalid_generated_json_fails_after_one_request_without_echoing_it(self):
        self.baseline()
        (self.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        raw_marker = "RAW_GENERATED_CONTENT_SHOULD_NOT_BE_PRINTED"
        generated_text = json.dumps({"summary": [raw_marker], "title": ""})
        result = self.run_cli("commit", FAKE_KEY, generated_text=generated_text)
        self.assertEqual(result.returncode, 1)
        self.http_mock.assert_called_once()
        self.assertIn("[INFO] Gemini API 호출 횟수: 1회", result.stdout)
        self.assertIn("[ERROR]", result.stderr)
        self.assertNotIn("[DONE]", result.stdout)
        self.assertNotIn("--- Commit Message ---", result.stdout)
        self.assertNotIn(raw_marker, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
