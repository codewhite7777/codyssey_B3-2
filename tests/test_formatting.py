import json
import unittest

from ai_gitgen.errors import UserError
from ai_gitgen.formatting import format_commit


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


if __name__ == "__main__":
    unittest.main()
