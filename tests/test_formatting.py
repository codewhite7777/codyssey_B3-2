import json
import unittest

from ai_gitgen.errors import UserError
from ai_gitgen.formatting import format_commit, format_pr


class CommitFormattingTests(unittest.TestCase):
    def test_korean_summary_and_title_are_printed_in_separate_sections(self):
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
        for length in (71, 72):
            with self.subTest(length=length):
                title = "가" * length
                formatted, title_changed = format_commit(json.dumps({
                    "summary": ["변경 요약"], "title": title,
                }, ensure_ascii=False))
                self.assertIn(f"--- Commit Message ---\n{title}\n", formatted)
                self.assertFalse(title_changed)

    def test_multiline_and_long_titles_are_normalized_and_flagged(self):
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
        raw_marker = "RAW_GENERATED_CONTENT_SHOULD_NOT_BE_PRINTED"
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
    def setUp(self):
        self.draft = {
            "summary": [" app.py의\n 기본값을    변경했습니다. "],
            "title": "fix: 기본값 변경",
            "why": [" 기본값 개선\t요청 반영 "],
            "what": [" app.py의 기본값을\n2로 변경 "],
            "how_to_test": [" 변경된 기본값을 확인합니다. "],
        }

    def test_pr_summary_title_and_three_sections_have_normalized_bullets(self):
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
        fake_key = "FAKE_KEY_FOR_TEST"
        draft = {
            "summary": [f"변경 요약 {fake_key}"],
            "title": f"fix: {fake_key} " + "가" * 70,
            "why": [f"변경 이유 {fake_key}"],
            "what": [f"변경 내용 {fake_key}"],
            "how_to_test": [f"검증 방법 {fake_key}"],
        }
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
        raw_marker = "RAW_GENERATED_CONTENT_SHOULD_NOT_BE_PRINTED"
        valid = {**self.draft, "summary": [raw_marker]}
        invalid_texts = [raw_marker, "[]", "{}"]
        for field in ("title", "summary", "why", "what", "how_to_test"):
            missing = dict(valid)
            del missing[field]
            invalid_texts.append(json.dumps(missing))
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
