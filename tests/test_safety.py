from dataclasses import asdict
import unittest

from ai_gitgen.git_changes import FileChange, GitChanges, collect_changes
from ai_gitgen.safety import redact, redact_changes
from tests.helpers import RepositoryTestCase


FAKE_KEY = "FAKE_KEY_FOR_TEST"


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


class RedactChangesTests(unittest.TestCase):
    def test_masks_added_deleted_and_context_lines_in_both_diffs(self):
        changes = GitChanges("main", (
            FileChange(
                "MM", "app.py",
                staged_diff=(
                    "-value = 'old:FAKE_KEY_FOR_TEST'\n"
                    "+value = 'staged:FAKE_KEY_FOR_TEST'\n"
                    " token = 'FAKE_KEY_FOR_TEST'\n"
                ),
                unstaged_diff=(
                    "-value = 'staged:FAKE_KEY_FOR_TEST'\n"
                    "+value = 'worktree:FAKE_KEY_FOR_TEST'\n"
                    " token = 'FAKE_KEY_FOR_TEST'\n"
                ),
            ),
        ))

        result = redact_changes(changes, FAKE_KEY)

        self.assertEqual(
            result.files[0].staged_diff,
            "-value = 'old:[REDACTED]'\n"
            "+value = 'staged:[REDACTED]'\n"
            " token = '[REDACTED]'\n",
        )
        self.assertEqual(
            result.files[0].unstaged_diff,
            "-value = 'staged:[REDACTED]'\n"
            "+value = 'worktree:[REDACTED]'\n"
            " token = '[REDACTED]'\n",
        )

    def test_masks_metadata_and_preserves_original_status_order_and_none(self):
        changes = GitChanges("feature/FAKE_KEY_FOR_TEST", (
            FileChange(
                "R ", "new-FAKE_KEY_FOR_TEST.py", "old-FAKE_KEY_FOR_TEST.py",
            ),
            FileChange(" M", "app.py"),
            FileChange("??", "notes-FAKE_KEY_FOR_TEST.txt"),
        ))
        original = asdict(changes)

        result = redact_changes(changes, FAKE_KEY)

        self.assertEqual(result, GitChanges("feature/[REDACTED]", (
            FileChange("R ", "new-[REDACTED].py", "old-[REDACTED].py"),
            FileChange(" M", "app.py"),
            FileChange("??", "notes-[REDACTED].txt"),
        )))
        self.assertIsNone(result.files[1].old_path)
        self.assertEqual(len(result.tracked_files), 2)
        self.assertIsNot(result, changes)
        self.assertIsNot(result.files[0], changes.files[0])
        self.assertEqual(asdict(changes), original)

    def test_preserves_contents_when_secret_is_absent_or_empty(self):
        cases = (
            (GitChanges("main", (
                FileChange(" M", "app.py", unstaged_diff="+value = 2\n"),
            )), FAKE_KEY),
            (GitChanges("FAKE_KEY_FOR_TEST", (
                FileChange(
                    " M", "FAKE_KEY_FOR_TEST.py",
                    unstaged_diff="+FAKE_KEY_FOR_TEST\n",
                ),
            )), ""),
        )
        for changes, secret in cases:
            with self.subTest(secret=secret):
                original = asdict(changes)

                result = redact_changes(changes, secret)

                self.assertEqual(result, changes)
                self.assertIsNot(result, changes)
                self.assertEqual(asdict(changes), original)


class RedactCollectedChangesTests(RepositoryTestCase):
    def test_masks_collected_diffs_without_changing_files_index_or_source(self):
        self.baseline(text=(
            "token = 'FAKE_KEY_FOR_TEST'\n"
            "value = 'old:FAKE_KEY_FOR_TEST'\n"
        ))
        app = self.root / "app.py"
        app.write_text(
            "token = 'FAKE_KEY_FOR_TEST'\n"
            "value = 'staged:FAKE_KEY_FOR_TEST'\n",
            encoding="utf-8",
        )
        self.git("add", "--", "app.py")
        app.write_text(
            "token = 'FAKE_KEY_FOR_TEST'\n"
            "value = 'worktree:FAKE_KEY_FOR_TEST'\n",
            encoding="utf-8",
        )
        original_file = app.read_bytes()
        index = self.root / ".git" / "index"
        original_index = index.read_bytes()
        changes = collect_changes(self.root)
        original_changes = asdict(changes)
        self.assertEqual(changes.files[0].status, "MM")
        self.assertIn(FAKE_KEY, changes.files[0].staged_diff)
        self.assertIn(FAKE_KEY, changes.files[0].unstaged_diff)

        result = redact_changes(changes, FAKE_KEY)

        staged = result.files[0].staged_diff
        unstaged = result.files[0].unstaged_diff
        self.assertNotIn(FAKE_KEY, staged + unstaged)
        self.assertIn("-value = 'old:[REDACTED]'", staged)
        self.assertIn("+value = 'staged:[REDACTED]'", staged)
        self.assertIn("-value = 'staged:[REDACTED]'", unstaged)
        self.assertIn("+value = 'worktree:[REDACTED]'", unstaged)
        self.assertIn(" token = '[REDACTED]'", staged)
        self.assertIn(" token = '[REDACTED]'", unstaged)
        self.assertEqual(app.read_bytes(), original_file)
        self.assertEqual(index.read_bytes(), original_index)
        self.assertEqual(asdict(changes), original_changes)


if __name__ == "__main__":
    unittest.main()
