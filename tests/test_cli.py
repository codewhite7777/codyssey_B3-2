"""CLI의 Git 수집→설정→요청→출력 연결을 실제 임시 Git과 가짜 HTTP 응답으로 검증합니다.

main()은 같은 Python 프로세스에서 호출합니다. Git은 임시 저장소에서 실행하고
HTTP 요청은 모의 응답으로 교체하므로 실제 Gemini 요청이나 사용자 저장소 변경은 없습니다.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import subprocess
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from ai_gitgen.cli import main
from ai_gitgen.prompts import COMMIT_SYSTEM_INSTRUCTION, PR_SYSTEM_INSTRUCTION
from tests.helpers import RepositoryTestCase


FAKE_KEY = "FAKE_KEY_FOR_TEST"
CONFIRMED_MESSAGE = "[INFO] AI_API_KEY 환경변수 설정을 확인했습니다."
MASKING_MESSAGE = "[INFO] 현재 API Key 마스킹 적용 완료: diff·파일명·브랜치"
MISSING_KEY_MESSAGE = (
    "AI_API_KEY 환경변수가 설정되지 않았습니다. "
    "README.md의 'API Key 입력' 안내에 따라 같은 터미널에서 설정해 주세요."
)


class ApiKeyCliTests(RepositoryTestCase):
    """명령별 성공·조기 종료·오류에서 출력과 요청 내용이 요구사항에 맞는지 확인합니다."""

    def run_cli(self, command, key=None, *options, error=None, generated_text=None):
        """명령과 옵션을 실행해 종료 코드·표준 출력·오류 출력을 반환합니다.

        key에는 테스트용 가짜 값만 넣고, error 또는 generated_text로 HTTP 결과를 정합니다.
        실제 임시 저장소에서 Git은 실행하지만 별도 Python 프로세스는 띄우지 않습니다.
        """
        environment = os.environ.copy()
        # 사용자의 실제 Key가 섞이지 않도록 관련 변수를 제거하고 테스트용 값만 넣습니다.
        for name in ("AI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            environment.pop(name, None)
        if key is not None:
            environment["AI_API_KEY"] = key
        # 별도 응답이 지정되지 않았다면 명령에 필요한 필드를 가진 정상 초안을 준비합니다.
        if generated_text is None:
            draft = {"summary": ["app.py의 기본값 변경"], "title": "fix: 기본값 변경"}
            if command == "pr":
                draft.update({
                    "why": ["기본값 개선 요청 반영"],
                    "what": ["app.py의 기본값을 2로 변경"],
                    "how_to_test": ["변경된 기본값을 확인합니다."],
                })
            generated_text = json.dumps(draft, ensure_ascii=False)
        # 생성된 JSON 문자열을 Gemini 바깥 응답의 parts.text 안에 넣어 실제 응답 구조를 흉내 냅니다.
        response = json.dumps({
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": generated_text}]},
            }],
        }, ensure_ascii=False).encode("utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        arguments = [command, *options]
        previous_directory = os.getcwd()
        # urlopen만 가짜 응답/오류로 교체합니다. 환경변수와 출력 대상도 이 블록에서만 바꿉니다.
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
                    # argparse가 잘못된 옵션을 거절할 때의 종료 코드도 테스트 결과로 받습니다.
                    returncode = exit_error.code
            finally:
                # 성공·실패와 관계없이 작업 위치를 되돌려 다음 테스트에 영향을 주지 않습니다.
                os.chdir(previous_directory)
        # CompletedProcess는 결과를 묶는 용도로만 사용하며 여기서 새 프로세스를 실행하지 않습니다.
        return subprocess.CompletedProcess(
            ["main.py", *arguments], returncode, stdout.getvalue(), stderr.getvalue(),
        )

    def request_data(self):
        """가짜 HTTP 호출이 받은 Request와 요청 본문, 그 안의 Git 프롬프트를 꺼내 반환합니다."""
        request = self.http_mock.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        # HTTP 본문과 contents 안의 프롬프트 문자열은 서로 다른 JSON이므로 각각 해석합니다.
        prompt = json.loads(payload["contents"][0]["parts"][0]["text"])
        return request, payload, prompt

    def test_generation_commands_report_missing_keys_without_a_traceback(self):
        """추적 파일 변경이 있어도 Key가 없으면 안내 오류로 끝나고 HTTP 요청을 하지 않는지 확인합니다."""
        self.baseline()
        (self.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        # 두 생성 명령에서 미설정·빈 값·공백만 있는 값을 같은 누락 상태로 다뤄야 합니다.
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

    def test_configured_key_generates_commit_and_pr_with_their_own_instructions(self):
        """가짜 Key와 성공 응답으로 두 명령의 작성 규칙·기본 설정·최종 출력 연결을 확인합니다."""
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
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stderr, "")
                    self.assertIn("--- Change Summary ---\n- app.py의 기본값 변경", result.stdout)
                    self.assertIn("[INFO] Gemini API 호출 횟수: 1회", result.stdout)
                    self.http_mock.assert_called_once()
                    # 명령행에서 생략한 기본값도 실제 Request에 반영되는지 확인합니다.
                    request, payload, prompt = self.request_data()
                    self.assertTrue(request.full_url.endswith(
                        "/models/gemini-3.1-flash-lite:generateContent"
                    ))
                    self.assertEqual(payload["generationConfig"]["temperature"], 1.0)
                    self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 4096)
                    self.assertFalse(prompt["partial_diff"])
                    instruction = payload["systemInstruction"]["parts"][0]["text"]
                    # 공통 실행 흐름을 쓰더라도 커밋과 PR의 프롬프트·출력은 각각 달라야 합니다.
                    if command == "commit":
                        self.assertIn("[DONE] 커밋 메시지 생성 완료", result.stdout)
                        self.assertIn("--- Commit Message ---\nfix: 기본값 변경", result.stdout)
                        self.assertEqual(instruction, COMMIT_SYSTEM_INSTRUCTION)
                    else:
                        self.assertIn("[DONE] PR 초안 생성 완료", result.stdout)
                        self.assertIn("--- PR Title ---\nfix: 기본값 변경", result.stdout)
                        self.assertIn("--- PR Body ---\n## Why\n- 기본값 개선 요청 반영", result.stdout)
                        self.assertIn("## What\n- app.py의 기본값을 2로 변경", result.stdout)
                        self.assertIn("## How to Test\n- 변경된 기본값을 확인합니다.", result.stdout)
                        self.assertEqual(instruction, PR_SYSTEM_INSTRUCTION)
                        self.assertNotEqual(instruction, COMMIT_SYSTEM_INSTRUCTION)

    def test_generation_commands_mask_tracked_and_untracked_file_names(self):
        """Key가 파일 이름과 diff에 있어도 로그·요청 본문에 원문으로 남지 않는지 확인합니다."""
        # 추적 파일은 diff 수집 대상, 미추적 파일은 목록 표시 대상이므로 두 경로를 함께 검사합니다.
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
                self.assertEqual(result.returncode, 0)
                self.assertIn(MASKING_MESSAGE, result.stdout)
                self.assertIn('"tracked-[REDACTED].py"', result.stdout)
                self.assertIn('"new-[REDACTED].py"', result.stdout)
                self.assertNotIn(FAKE_KEY, result.stdout + result.stderr)
                self.http_mock.assert_called_once()
                self.assertNotIn(FAKE_KEY.encode(), self.http_mock.call_args.args[0].data)

    def test_safe_mode_limits_combined_staged_and_unstaged_request_input(self):
        """동일 변경에서 안전 모드 ON/OFF의 전송 줄 수·부분 입력 표시·마스킹을 비교합니다."""
        tracked_name = f"app-{FAKE_KEY}.py"
        self.baseline(name=tracked_name)
        # 스테이징한 100줄 뒤에 120줄을 더 수정하여 두 diff의 합이 200줄을 넘게 만듭니다.
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
                # 안전 모드는 두 diff를 합계 200줄로 제한하고 일부 입력임을 모델에 알려야 합니다.
                limited = self.run_cli(command, FAKE_KEY, "--safe-mode")
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

                # 같은 변경을 일반 모드로 실행하면 줄 제한과 부분 입력 경고가 없어야 합니다.
                normal = self.run_cli(command, FAKE_KEY)
                self.http_mock.assert_called_once()
                _, _, prompt = self.request_data()
                self.assertFalse(prompt["partial_diff"])
                self.assertGreater(sum(
                    len(item[field].splitlines())
                    for item in prompt["files"]
                    for field in ("staged_diff", "unstaged_diff")
                ), 200)

                self.assertIn(
                    "[INFO] 안전 모드 적용: 1개 파일, 200줄 (최대 10개 파일·200줄)",
                    limited.stdout,
                )
                self.assertIn(warning, limited.stdout)
                self.assertNotIn("[INFO] 안전 모드 적용:", normal.stdout)
                self.assertNotIn(warning, normal.stdout)
                # 현재 Key를 가리는 처리는 안전 모드 여부와 관계없이 적용돼야 합니다.
                for result in (limited, normal):
                    self.assertEqual(result.returncode, 0)
                    self.assertIn(MASKING_MESSAGE, result.stdout)
                    self.assertIn('"app-[REDACTED].py"', result.stdout)
                    self.assertNotIn(FAKE_KEY, result.stdout + result.stderr)

    def test_inspect_with_tracked_changes_does_not_require_a_key(self):
        """inspect는 변경을 수집해 안내하지만 Key를 요구하거나 API를 호출하지 않는지 확인합니다."""
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
        """수정이 없으면 모든 명령이 Key 검사·HTTP 요청 없이 변경 없음 안내로 끝나는지 확인합니다."""
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
        """미추적 파일만 있으면 git add를 안내하고 Key 검사·HTTP 요청 없이 종료하는지 확인합니다."""
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
        """CLI 옵션은 API 설정으로, 마스킹한 브랜치·경로·맥락·diff는 프롬프트로 전달되는지 확인합니다."""
        # 서로 다른 입력 위치에 같은 가짜 Key를 넣어 수집 이후 전송 전 마스킹을 확인합니다.
        tracked_name = f"app-{FAKE_KEY}.py"
        self.baseline(name=tracked_name)
        self.git("branch", "-m", f"feature-{FAKE_KEY}")
        (self.root / tracked_name).write_text(
            f"value = '{FAKE_KEY}'\n", encoding="utf-8",
        )
        for command in ("commit", "pr"):
            with self.subTest(command=command):
                result = self.run_cli(
                    command, f" {FAKE_KEY} ",
                    "--model", "gemini-test-model", "--temperature", "0.2",
                    "--max-tokens", "512", "--context", f"설정값 교체: {FAKE_KEY}",
                )
                self.assertEqual(result.returncode, 0)
                self.http_mock.assert_called_once()
                request, payload, prompt = self.request_data()
                # 인증 Key는 헤더에 유지하고 모델·temperature·토큰 옵션은 각각 맞는 필드에 넣어야 합니다.
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
                # AI가 읽는 입력과 터미널 출력에는 인증에 사용한 Key가 포함되면 안 됩니다.
                self.assertEqual(prompt["branch"], "feature-[REDACTED]")
                self.assertEqual(prompt["context"], "설정값 교체: [REDACTED]")
                self.assertEqual(prompt["files"][0]["path"], "app-[REDACTED].py")
                self.assertIn("+value = '[REDACTED]'", prompt["files"][0]["unstaged_diff"])
                self.assertNotIn(FAKE_KEY, request.full_url)
                self.assertNotIn(FAKE_KEY.encode(), request.data)
                self.assertNotIn(FAKE_KEY, result.stdout + result.stderr)

    def test_request_errors_report_the_cause_without_retrying_or_exposing_the_key(self):
        """권한 오류·연결 실패가 발생하면 원인과 시도 횟수를 출력하되 재시도·Key 노출은 없는지 확인합니다."""
        self.baseline()
        (self.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        for command in ("commit", "pr"):
            # HTTP 응답 오류와 응답을 받기 전 연결 오류를 각각 만들어 CLI까지 전달합니다.
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
                with self.subTest(command=command, error=type(error).__name__):
                    result = self.run_cli(command, FAKE_KEY, error=error)
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
        """잘못된 모델 이름·숫자 범위·정수 형식은 종료 코드 2로 거절하고 API를 호출하지 않는지 확인합니다."""
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
        """요청은 성공해도 생성 필수 항목이 잘못되면 초안과 원문을 출력하지 않는지 확인합니다."""
        self.baseline()
        (self.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        raw_marker = "RAW_GENERATED_CONTENT_SHOULD_NOT_BE_PRINTED"
        for command in ("commit", "pr"):
            with self.subTest(command=command):
                # 커밋은 제목이 비어 있고, PR은 제목은 있지만 필수 본문 항목이 빠진 응답입니다.
                generated_text = json.dumps({
                    "summary": [raw_marker],
                    "title": "" if command == "commit" else "fix: 기본값 변경",
                })
                result = self.run_cli(command, FAKE_KEY, generated_text=generated_text)
                self.assertEqual(result.returncode, 1)
                self.http_mock.assert_called_once()
                self.assertIn("[INFO] Gemini API 호출 횟수: 1회", result.stdout)
                self.assertIn("[ERROR]", result.stderr)
                self.assertNotIn("[DONE]", result.stdout)
                self.assertNotIn("--- Commit Message ---", result.stdout)
                self.assertNotIn("--- PR Title ---", result.stdout)
                self.assertNotIn(raw_marker, result.stdout + result.stderr)

    def test_pr_warns_when_normalizing_its_title_and_masks_generated_fields(self):
        """PR 제목 후처리 경고와 모든 항목의 마스킹이 CLI 최종 출력까지 반영되는지 확인합니다."""
        self.baseline()
        (self.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        draft = {
            "summary": [f"변경 요약 {FAKE_KEY}"],
            "title": f"  fix:\n {FAKE_KEY} " + "가" * 70,
            "why": [f"변경 이유 {FAKE_KEY}"],
            "what": [f"변경 내용 {FAKE_KEY}"],
            "how_to_test": [f"검증 방법 {FAKE_KEY}"],
        }
        # 줄바꿈·길이 초과 제목과 JSON 이스케이프된 Key를 한 응답에 넣어 처리 순서를 확인합니다.
        generated_text = json.dumps(draft, ensure_ascii=False).replace(
            FAKE_KEY, r"\u0046AKE_KEY_FOR_TEST",
        )
        result = self.run_cli("pr", FAKE_KEY, generated_text=generated_text)
        self.assertEqual(result.returncode, 0)
        self.http_mock.assert_called_once()
        self.assertIn("[WARN] PR 제목", result.stdout)
        self.assertIn("[DONE] PR 초안 생성 완료", result.stdout)
        self.assertIn("[INFO] Gemini API 호출 횟수: 1회", result.stdout)
        self.assertNotIn(FAKE_KEY, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("[REDACTED]"), 5)
        printed_title = result.stdout.split("--- PR Title ---\n", 1)[1].splitlines()[0]
        self.assertEqual(printed_title, "fix: [REDACTED] " + "가" * 63 + "…")
        self.assertLessEqual(len(printed_title), 80)


if __name__ == "__main__":
    unittest.main()
