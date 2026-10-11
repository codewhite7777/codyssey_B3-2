import os
from pathlib import Path
import subprocess
import sys
import unittest

from tests.helpers import RepositoryTestCase


MAIN = Path(__file__).resolve().parents[1] / "main.py"
FAKE_KEY = "FAKE_KEY_FOR_TEST"
CONFIRMED_MESSAGE = "[INFO] AI_API_KEY 환경변수 설정을 확인했습니다."
MASKING_MESSAGE = "[INFO] 현재 API Key 마스킹 적용 완료: diff·파일명·브랜치"
MISSING_KEY_MESSAGE = (
    "AI_API_KEY 환경변수가 설정되지 않았습니다. "
    "READ.md의 3.3절에 따라 같은 터미널에서 설정해 주세요."
)
NOT_IMPLEMENTED_MESSAGE = (
    "Gemini API 호출과 초안 생성은 아직 구현되지 않았습니다. "
    "현재 단계는 최소 안전 모드까지입니다."
)


class ApiKeyCliTests(RepositoryTestCase):
    def run_cli(self, command, key=None, *options):
        environment = os.environ.copy()
        # Never pass the runner's real provider keys to a CLI test process.
        for name in ("AI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            environment.pop(name, None)
        if key is not None:
            environment["AI_API_KEY"] = key
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, str(MAIN), command, *options],
            cwd=self.root, env=environment, capture_output=True,
            text=True, encoding="utf-8", timeout=30, check=False,
        )

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

    def test_configured_key_reaches_unimplemented_generation_without_exposing_it(self):
        self.baseline()
        (self.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        for command in ("commit", "pr"):
            for key in (FAKE_KEY, f" \t{FAKE_KEY} "):
                with self.subTest(command=command, key=key):
                    result = self.run_cli(command, key)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn(CONFIRMED_MESSAGE, result.stdout)
                    self.assertIn(MASKING_MESSAGE, result.stdout)
                    self.assertIn("[INFO] Gemini API 호출 횟수: 0회", result.stdout)
                    self.assertIn("[ERROR] " + NOT_IMPLEMENTED_MESSAGE, result.stderr)
                    self.assertNotIn(MISSING_KEY_MESSAGE, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertNotIn(FAKE_KEY, result.stdout + result.stderr)

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

                self.assertEqual(result.returncode, 1)
                self.assertIn(MASKING_MESSAGE, result.stdout)
                self.assertIn('"tracked-[REDACTED].py"', result.stdout)
                self.assertIn('"new-[REDACTED].py"', result.stdout)
                self.assertIn("[INFO] Gemini API 호출 횟수: 0회", result.stdout)
                self.assertIn("[ERROR] " + NOT_IMPLEMENTED_MESSAGE, result.stderr)
                self.assertNotIn(FAKE_KEY, result.stdout + result.stderr)

    def test_safe_mode_limits_generation_input_only_when_requested(self):
        tracked_name = f"app-{FAKE_KEY}.py"
        self.baseline(name=tracked_name)
        (self.root / tracked_name).write_text(
            "value = 1\n" + "".join(
                f"# added {number}: {FAKE_KEY}\n" for number in range(220)
            ),
            encoding="utf-8",
        )
        warning = "[WARN] 전송 제한으로 일부 변경만 AI 입력에 포함합니다."

        for command in ("commit", "pr"):
            with self.subTest(command=command):
                limited = self.run_cli(command, FAKE_KEY, "--safe-mode")
                normal = self.run_cli(command, FAKE_KEY)

                self.assertIn(
                    "[INFO] 안전 모드 적용: 1개 파일, 200줄 (최대 10개 파일·200줄)",
                    limited.stdout,
                )
                self.assertIn(warning, limited.stdout)
                self.assertNotIn("[INFO] 안전 모드 적용:", normal.stdout)
                self.assertNotIn(warning, normal.stdout)
                for result in (limited, normal):
                    self.assertEqual(result.returncode, 1)
                    self.assertIn(MASKING_MESSAGE, result.stdout)
                    self.assertIn('"app-[REDACTED].py"', result.stdout)
                    self.assertIn("[INFO] Gemini API 호출 횟수: 0회", result.stdout)
                    self.assertIn("[ERROR] " + NOT_IMPLEMENTED_MESSAGE, result.stderr)
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


if __name__ == "__main__":
    unittest.main()
