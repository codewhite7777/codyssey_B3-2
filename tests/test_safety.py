import unittest

from ai_gitgen.safety import redact


class RedactTests(unittest.TestCase):
    def test_masks_one_occurrence(self):
        text = "API Key: FAKE_KEY_FOR_TEST"

        result = redact(text, "FAKE_KEY_FOR_TEST")

        self.assertEqual(result, "API Key: [REDACTED]")

    def test_masks_both_occurrences_in_added_and_deleted_diff_lines(self):
        text = (
            "-api_key = 'FAKE_KEY_FOR_TEST'\n"
            "+api_key = 'FAKE_KEY_FOR_TEST'\n"
            " unchanged = True\n"
        )

        result = redact(text, "FAKE_KEY_FOR_TEST")

        self.assertEqual(
            result,
            "-api_key = '[REDACTED]'\n"
            "+api_key = '[REDACTED]'\n"
            " unchanged = True\n",
        )

    def test_preserves_text_without_the_secret(self):
        text = "+print('hello')\n"

        result = redact(text, "FAKE_KEY_FOR_TEST")

        self.assertEqual(result, text)

    def test_preserves_original_text_when_secret_is_empty(self):
        text = "API Key: FAKE_KEY_FOR_TEST"

        result = redact(text, "")

        self.assertEqual(result, text)


if __name__ == "__main__":
    unittest.main()
