from dataclasses import asdict
import unittest

from ai_gitgen.git_changes import FileChange, GitChanges, collect_changes
from ai_gitgen.safety import limit_changes, redact, redact_changes
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


class LimitChangesTests(unittest.TestCase):
    def test_keeps_first_ten_files_with_tracked_diffs_and_skips_empty_files(self):
        tracked = tuple(
            FileChange(" M", f"file-{number}.py", unstaged_diff=f"+value = {number}\n")
            for number in range(11)
        )
        skipped = (
            FileChange(" M", "empty.py"),
            FileChange("??", "untracked.py", unstaged_diff="+not tracked\n"),
        )
        for count in (10, 11):
            with self.subTest(tracked_files=count):
                changes = GitChanges("feature/limited", skipped + tracked[:count])
                original = asdict(changes)

                result = limit_changes(changes)

                self.assertEqual(result, GitChanges("feature/limited", tracked[:10]))
                self.assertEqual(len(result.files), 10)
                self.assertIsNot(result, changes)
                self.assertEqual(asdict(changes), original)

    def test_shares_two_hundred_lines_across_files_and_both_diffs(self):
        first = FileChange(
            "MM", "first.py",
            staged_diff="-first staged\n" * 70,
            unstaged_diff="+first unstaged\n" * 50,
        )
        second_staged = "-second staged\r\n" * 60
        kept_unstaged = "+second unstaged\n" * 20
        expected_second = FileChange(
            "MM", "second.py",
            staged_diff=second_staged,
            unstaged_diff=kept_unstaged,
        )
        cases = (
            (first, expected_second),
            (
                first,
                FileChange(
                    "MM", "second.py",
                    staged_diff=second_staged,
                    unstaged_diff=kept_unstaged + "+excluded line\n",
                ),
                FileChange(" M", "later.py", unstaged_diff="+excluded file\n"),
            ),
        )
        for files in cases:
            with self.subTest(input_lines=sum(
                len(item.staged_diff.splitlines()) + len(item.unstaged_diff.splitlines())
                for item in files
            )):
                changes = GitChanges("main", files)
                original = asdict(changes)

                result = limit_changes(changes)

                self.assertEqual(result, GitChanges("main", (first, expected_second)))
                self.assertEqual(result.diff_lines, 200)
                self.assertEqual(asdict(changes), original)

    def test_preserves_below_limit_text_metadata_and_empty_input(self):
        cases = (
            GitChanges("feature/rename", (
                FileChange(
                    "RM", "new.py", "old.py",
                    staged_diff="-이전 값\r\n+새 값",
                    unstaged_diff=" context\n+추가 값\n",
                ),
            )),
            GitChanges("main", ()),
        )
        for changes in cases:
            with self.subTest(branch=changes.branch):
                original = asdict(changes)

                result = limit_changes(changes)

                self.assertEqual(result, changes)
                self.assertIsNot(result, changes)
                self.assertEqual(asdict(changes), original)


if __name__ == "__main__":
    unittest.main()
