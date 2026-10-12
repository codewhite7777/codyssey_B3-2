"""AI가 반환했다고 가정한 JSON으로 제목 길이·불릿·필수 필드·출력 마스킹을 검증합니다.

API와 Git은 호출하지 않고 format_commit()/format_pr()에 준비한 JSON 문자열을 직접 전달합니다.
정상 출력의 문장 배치, 길이 경계값, 잘못된 입력 거절, JSON 해석 후 Key 마스킹을 확인합니다.
반환값은 화면에 쓸 문자열과 제목을 다듬었는지 알려 주는 불리언 값의 묶음입니다.
"""

import json
import unittest

from ai_gitgen.errors import UserError
from ai_gitgen.formatting import format_commit, format_pr


class CommitFormattingTests(unittest.TestCase):
    """커밋 결과의 요약·제목 구분, 최대 72자 후처리, 잘못된 응답 거절을 확인합니다.

    각 메서드가 summary와 title을 담은 입력을 만들고 format_commit()의 반환값을 검사합니다.
    AI가 규칙을 지켰다고 가정하지 않고 Python이 마지막 출력 조건을 적용하는지 확인하는 테스트입니다.
    """

    def test_korean_summary_and_title_are_printed_in_separate_sections(self):
        """변경 요약과 커밋 제목을 구분하고 요약 문장의 공백을 정리하는지 확인합니다.

        한글 요약에 줄바꿈·탭·연속 공백을 넣고 정상 제목과 함께 JSON으로 만듭니다.
        format_commit()의 전체 출력 문자열을 비교해 헤더·불릿·줄 간격을 확인합니다.
        제목 자체는 바뀌지 않았으므로 title_changed가 False인지도 검사합니다.
        """
        text = json.dumps({
            "summary": [" app.py의\n 기본값을    변경했습니다. ", "오류 안내를\t수정했습니다."],
            "title": "fix: 기본값과 오류 안내 수정",
        }, ensure_ascii=False)
        formatted, title_changed = format_commit(text)
        self.assertEqual(formatted,
            "--- Change Summary ---\n"
            "- app.py의 기본값을 변경했습니다.\n"
            "- 오류 안내를 수정했습니다.\n\n"
            "--- Commit Message ---\n"
            "fix: 기본값과 오류 안내 수정\n"
            "----------------------")
        self.assertFalse(title_changed)

    def test_title_at_the_72_character_limit_is_preserved(self):
        """최대 길이를 넘지 않은 제목은 불필요하게 줄이지 않는지 확인합니다.

        한글 71자와 72자 제목을 각각 준비하고 format_commit()을 실행합니다.
        출력에 원래 제목이 있고 title_changed가 False인지 검사합니다.
        최대 72자에는 72자도 포함된다는 경계 조건을 확인하는 테스트입니다.
        """
        for length in (71, 72):
            with self.subTest(length=length):
                title = "가" * length
                formatted, title_changed = format_commit(json.dumps({
                    "summary": ["변경 요약"], "title": title,
                }, ensure_ascii=False))
                self.assertIn(f"--- Commit Message ---\n{title}\n", formatted)
                self.assertFalse(title_changed)

    def test_multiline_and_long_titles_are_normalized_and_flagged(self):
        """여러 줄 또는 긴 제목을 정리하고 Key를 가린 뒤 길이를 제한하는지 확인합니다.

        공백·줄바꿈·길이 초과·잘림 위치의 공백을 가진 제목을 format_commit()에 전달합니다.
        예상 제목, 최대 72자, title_changed=True를 비교해 후처리와 조정 표시를 확인합니다.
        별도 경우에서는 JSON 이스케이프된 Key를 넣어 해석 → 마스킹 → 길이 제한 순서도 검사합니다.
        """
        # 공백 정리, 길이 초과, 잘라낸 경계의 공백 처리를 서로 다른 입력으로 검사합니다.
        cases = (
            ("  feat:\n  변경\t추가  ", "feat: 변경 추가"),
            ("가" * 80, "가" * 71 + "…"),
            ("가" * 70 + " " + "나" * 5, "가" * 70 + "…"),
        )
        for title, expected in cases:
            with self.subTest(title=title):
                formatted, title_changed = format_commit(json.dumps({
                    "summary": ["변경 요약"], "title": title,
                }, ensure_ascii=False))
                printed_title = formatted.split("--- Commit Message ---\n", 1)[1].splitlines()[0]
                self.assertEqual(printed_title, expected)
                self.assertLessEqual(len(printed_title), 72)
                self.assertTrue(title_changed)

        # JSON 이스케이프가 해석된 뒤 Key를 가리고, 그 결과를 기준으로 길이를 제한해야 합니다.
        with self.subTest(escaped_key=True):
            escaped_key = r"\u0046AKE_KEY_FOR_TEST"
            text = (
                '{"summary":["' + escaped_key + ' 확인"],"title":"fix: '
                + escaped_key + " " + "가" * 60 + '"}'
            )
            formatted, title_changed = format_commit(text, secret="FAKE_KEY_FOR_TEST")
            self.assertNotIn("FAKE_KEY_FOR_TEST", formatted)
            self.assertIn("- [REDACTED] 확인", formatted)
            printed_title = formatted.split("--- Commit Message ---\n", 1)[1].splitlines()[0]
            self.assertEqual(printed_title, "fix: [REDACTED] " + "가" * 55 + "…")
            self.assertLessEqual(len(printed_title), 72)
            self.assertTrue(title_changed)

    def test_invalid_json_or_required_fields_raise_without_echoing_generated_content(self):
        """필수 커밋 자료가 잘못되면 초안을 만들지 않고 원문을 숨긴 오류를 내는지 확인합니다.

        깨진 JSON, 객체가 아닌 JSON, 누락·빈 값·틀린 자료형의 summary/title을 준비합니다.
        format_commit()이 각 입력에서 UserError를 발생시키는지 검사합니다.
        입력에 넣은 원문 표식이 오류에 없는지도 비교해 검증 실패 중 생성 내용이 노출되지 않게 합니다.
        """
        raw_marker = "RAW_GENERATED_CONTENT_SHOULD_NOT_BE_PRINTED"
        # 원문 표식을 일부 입력에 넣어 오류 안내가 생성 내용을 되풀이하는지도 함께 검사합니다.
        invalid_texts = (
            raw_marker,
            "[",
            json.dumps([raw_marker]),
            "{}",
            json.dumps({"summary": raw_marker, "title": "fix: 변경"}),
            json.dumps({"summary": [], "title": "fix: 변경"}),
            json.dumps({"summary": [" \n\t "], "title": "fix: 변경"}),
            json.dumps({"summary": [None], "title": "fix: 변경"}),
            json.dumps({"summary": [raw_marker]}),
            json.dumps({"summary": [raw_marker], "title": " \n\t "}),
            json.dumps({"summary": [raw_marker], "title": 123}),
        )
        for text in invalid_texts:
            with self.subTest(text=text):
                with self.assertRaises(UserError) as caught:
                    format_commit(text)
                self.assertNotIn(raw_marker, str(caught.exception))


class PrFormattingTests(unittest.TestCase):
    """PR 제목 최대 80자와 Why/What/How to Test의 필수 구조를 확인합니다.

    setUp()이 정상 초안을 준비하면 각 메서드는 검사할 필드만 바꿔 format_pr()를 실행합니다.
    커밋과 다른 제목 제한, 세 본문 섹션의 불릿, 잘못된 응답 거절, 모든 항목의 마스킹을 봅니다.
    """

    def setUp(self):
        """각 PR 테스트의 기준이 되는 정상 초안 사전을 새로 준비합니다.

        unittest가 매 test_* 전에 호출하므로 별도 인자는 받지 않습니다.
        summary/title/why/what/how_to_test를 self.draft에 저장하며 반환값은 없습니다.
        매번 새 자료를 만들어 한 테스트에서 바꾼 값이 다음 테스트에 남지 않게 합니다.
        """
        self.draft = {
            "summary": [" app.py의\n 기본값을    변경했습니다. "],
            "title": "fix: 기본값 변경",
            "why": [" 기본값 개선\t요청 반영 "],
            "what": [" app.py의 기본값을\n2로 변경 "],
            "how_to_test": [" 변경된 기본값을 확인합니다. "],
        }

    def test_pr_summary_title_and_three_sections_have_normalized_bullets(self):
        """정상 PR 자료가 정해진 섹션과 정리된 불릿으로 출력되는지 확인합니다.

        setUp()의 초안을 JSON 문자열로 바꾸어 format_pr()에 전달합니다.
        전체 출력과 예상 문자열을 비교해 요약·제목·세 본문 헤더·불릿·공백 처리를 확인합니다.
        제목은 수정할 필요가 없으므로 조정 여부는 False여야 합니다.
        """
        formatted, title_changed = format_pr(json.dumps(self.draft, ensure_ascii=False))
        self.assertEqual(formatted,
            "--- Change Summary ---\n"
            "- app.py의 기본값을 변경했습니다.\n\n"
            "--- PR Title ---\n"
            "fix: 기본값 변경\n\n"
            "--- PR Body ---\n"
            "## Why\n"
            "- 기본값 개선 요청 반영\n\n"
            "## What\n"
            "- app.py의 기본값을 2로 변경\n\n"
            "## How to Test\n"
            "- 변경된 기본값을 확인합니다.\n"
            "----------------------")
        self.assertFalse(title_changed)

    def test_pr_title_79_80_and_over_limit_with_whitespace_normalization(self):
        """PR 제목의 최대 80자 조건과 한 줄 정리를 경계값으로 확인합니다.

        79·80·81자 제목 및 줄바꿈·탭이 있는 제목을 정상 초안에 하나씩 넣습니다.
        format_pr()의 제목을 추출해 예상 결과와 길이, title_changed 값을 비교합니다.
        허용 길이의 제목은 보존하고 초과·여러 줄 제목만 조정하는지 확인합니다.
        """
        cases = (
            ("가" * 79, "가" * 79, False),
            ("가" * 80, "가" * 80, False),
            ("가" * 81, "가" * 79 + "…", True),
            ("  fix:\n  기본값\t변경  ", "fix: 기본값 변경", True),
        )
        for title, expected, adjusted in cases:
            with self.subTest(title=title):
                draft = {**self.draft, "title": title}
                formatted, title_changed = format_pr(json.dumps(draft, ensure_ascii=False))
                printed_title = formatted.split("--- PR Title ---\n", 1)[1].splitlines()[0]
                self.assertEqual(printed_title, expected)
                self.assertLessEqual(len(printed_title), 80)
                self.assertEqual(title_changed, adjusted)

    def test_json_escaped_key_is_masked_in_all_pr_fields_before_title_truncation(self):
        """JSON 이스케이프로 표현된 Key도 모든 PR 항목에서 가리는지 확인합니다.

        요약·제목·세 본문 항목에 같은 가짜 Key를 넣고 첫 문자를 JSON 이스케이프로 바꿉니다.
        format_pr()에 secret을 전달해 원래 Key가 사라지고 마스킹 표식이 5곳인지 검사합니다.
        가려진 제목을 기준으로 80자 제한과 조정 여부도 확인해 마스킹 이전에 잘라 Key가 남지 않게 합니다.
        """
        fake_key = "FAKE_KEY_FOR_TEST"
        draft = {
            "summary": [f"변경 요약 {fake_key}"],
            "title": f"fix: {fake_key} " + "가" * 70,
            "why": [f"변경 이유 {fake_key}"],
            "what": [f"변경 내용 {fake_key}"],
            "how_to_test": [f"검증 방법 {fake_key}"],
        }
        # 같은 Key를 JSON의 다른 표기로 넣어 단순한 원문 치환만으로 놓치지 않는지 확인합니다.
        text = json.dumps(draft, ensure_ascii=False).replace(
            fake_key, r"\u0046AKE_KEY_FOR_TEST",
        )
        formatted, title_changed = format_pr(text, secret=fake_key)
        self.assertNotIn(fake_key, formatted)
        self.assertEqual(formatted.count("[REDACTED]"), 5)
        printed_title = formatted.split("--- PR Title ---\n", 1)[1].splitlines()[0]
        self.assertEqual(printed_title, "fix: [REDACTED] " + "가" * 63 + "…")
        self.assertLessEqual(len(printed_title), 80)
        self.assertTrue(title_changed)

    def test_invalid_pr_json_and_required_fields_fail_without_echoing_content(self):
        """PR 필수 자료의 누락·틀린 자료형·빈 내용을 원문 노출 없이 거절하는지 확인합니다.

        정상 초안의 각 필드를 하나씩 빼거나 잘못된 값으로 바꾸고, 깨진 JSON도 준비합니다.
        각 문자열로 format_pr()를 실행해 UserError 발생을 확인합니다.
        오류 문장에 입력의 원문 표식이 없는지도 검사하여 잘못된 생성 내용을 그대로 되풀이하지 않게 합니다.
        """
        raw_marker = "RAW_GENERATED_CONTENT_SHOULD_NOT_BE_PRINTED"
        valid = {**self.draft, "summary": [raw_marker]}
        invalid_texts = [raw_marker, "[]", "{}"]
        # 정상 초안에서 각 필드를 하나씩 빼서 모든 필수 항목을 실제로 검사하는지 확인합니다.
        for field in ("title", "summary", "why", "what", "how_to_test"):
            missing = dict(valid)
            del missing[field]
            invalid_texts.append(json.dumps(missing))
        # 항목이 있어도 자료형이 틀리거나 내용이 비어 있는 별도의 실패 경우를 추가합니다.
        invalid_values = (
            ("title", " \n\t "),
            ("title", 123),
            ("summary", []),
            ("why", "문자열 대신 목록이 필요합니다"),
            ("what", [None]),
            ("how_to_test", [" \n\t "]),
        )
        for field, value in invalid_values:
            invalid_texts.append(json.dumps({**valid, field: value}))
        for text in invalid_texts:
            with self.subTest(text=text):
                with self.assertRaises(UserError) as caught:
                    format_pr(text)
                self.assertNotIn(raw_marker, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
