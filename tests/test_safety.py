"""현재 Key의 문자열 마스킹과 안전 모드의 10개 파일·합계 200줄 제한을 검증합니다."""

from dataclasses import asdict
import unittest

from ai_gitgen.git_changes import FileChange, GitChanges, collect_changes
from ai_gitgen.safety import limit_changes, redact, redact_changes
from tests.helpers import RepositoryTestCase


FAKE_KEY = "FAKE_KEY_FOR_TEST"


class RedactTests(unittest.TestCase):
    """문자열 하나에 적용하는 마스킹 함수의 기본 동작을 확인합니다."""

    def test_masks_one_occurrence(self):
        """입력에 현재 Key가 한 번 나타나면 해당 부분을 [REDACTED]로 바꾸는지 확인합니다."""
        text = "API Key: FAKE_KEY_FOR_TEST"

        result = redact(text, "FAKE_KEY_FOR_TEST")

        self.assertEqual(result, "API Key: [REDACTED]")

    def test_masks_both_occurrences_in_added_and_deleted_diff_lines(self):
        """diff의 추가 줄과 삭제 줄 모두에 있는 Key를 가리고 나머지는 유지하는지 확인합니다."""
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
        """지정한 Key가 들어 있지 않은 일반 문자열은 그대로 반환하는지 확인합니다."""
        text = "+print('hello')\n"

        result = redact(text, "FAKE_KEY_FOR_TEST")

        self.assertEqual(result, text)

    def test_preserves_original_text_when_secret_is_empty(self):
        """마스킹할 Key가 빈 값이면 문자열 전체를 잘못 치환하지 않는지 확인합니다."""
        text = "API Key: FAKE_KEY_FOR_TEST"

        result = redact(text, "")

        self.assertEqual(result, text)


class RedactChangesTests(unittest.TestCase):
    """GitChanges 전체를 마스킹하면서 경로·상태·원본 객체를 올바르게 다루는지 확인합니다."""

    def test_masks_added_deleted_and_context_lines_in_both_diffs(self):
        """두 diff의 추가·삭제·문맥 줄에 있는 Key가 빠짐없이 치환되는지 확인합니다."""
        # 한 파일에 staged/unstaged diff를 모두 넣어 같은 마스킹 규칙이 적용되는지 봅니다.
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
        """브랜치·현재/이전 경로의 Key를 가리되 상태·파일 순서·원본은 보존하는지 확인합니다."""
        changes = GitChanges("feature/FAKE_KEY_FOR_TEST", (
            FileChange(
                "R ", "new-FAKE_KEY_FOR_TEST.py", "old-FAKE_KEY_FOR_TEST.py",
            ),
            FileChange(" M", "app.py"),
            FileChange("??", "notes-FAKE_KEY_FOR_TEST.txt"),
        ))
        original = asdict(changes)

        result = redact_changes(changes, FAKE_KEY)

        # 값이 바뀐 새 객체를 반환해야 하며, 원본 객체와 이전 경로가 없는 None은 유지해야 합니다.
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
        """Key가 본문에 없거나 마스킹할 Key가 빈 값이면 데이터 내용이 유지되는지 확인합니다."""
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
    """실제 Git에서 수집한 데이터를 마스킹해도 파일과 스테이징 영역은 보존되는지 확인합니다."""

    def test_masks_collected_diffs_without_changing_files_index_or_source(self):
        """Key가 있는 파일을 단계별로 수정한 뒤 수집 결과만 마스킹되고 원본은 그대로인지 확인합니다."""
        # 커밋 기준 → 스테이징한 변경 → 추가 작업 순서로 서로 다른 두 diff를 만듭니다.
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
        # 파일과 Git index의 바이트, 수집 객체의 값을 저장해 의도하지 않은 변경을 찾습니다.
        original_file = app.read_bytes()
        index = self.root / ".git" / "index"
        original_index = index.read_bytes()
        changes = collect_changes(self.root)
        original_changes = asdict(changes)
        self.assertEqual(changes.files[0].status, "MM")
        self.assertIn(FAKE_KEY, changes.files[0].staged_diff)
        self.assertIn(FAKE_KEY, changes.files[0].unstaged_diff)

        result = redact_changes(changes, FAKE_KEY)

        # 두 diff의 마스킹을 확인한 뒤 디스크와 입력 객체를 저장한 값과 비교합니다.
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
    """제한 전후 데이터를 비교해 파일 수·공유 줄 예산·원본 보존을 확인합니다."""

    def test_keeps_first_ten_files_with_tracked_diffs_and_skips_empty_files(self):
        """빈 diff와 미추적 파일을 건너뛰고, diff가 있는 추적 파일을 최대 10개만 남기는지 확인합니다."""
        tracked = tuple(
            FileChange(" M", f"file-{number}.py", unstaged_diff=f"+value = {number}\n")
            for number in range(11)
        )
        skipped = (
            FileChange(" M", "empty.py"),
            FileChange("??", "untracked.py", unstaged_diff="+not tracked\n"),
        )
        # 정확히 10개일 때와 11개로 초과했을 때를 비교해 제한 경계를 확인합니다.
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
        """여러 파일의 staged/unstaged diff가 합계 200줄 예산을 함께 사용하는지 확인합니다."""
        # 첫 파일 120줄을 남긴 뒤 두 번째 파일에는 80줄만 남을 수 있게 구성합니다.
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
        # 총 200줄인 경우와 초과 줄·후속 파일이 있는 경우의 결과가 같아야 합니다.
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

                # 원래 줄바꿈(CRLF 포함)은 유지하고 제한 이후의 내용만 제외해야 합니다.
                self.assertEqual(result, GitChanges("main", (first, expected_second)))
                self.assertEqual(result.diff_lines, 200)
                self.assertEqual(asdict(changes), original)

    def test_preserves_below_limit_text_metadata_and_empty_input(self):
        """제한 미만의 이름 변경 기록과 빈 입력은 내용·메타데이터를 유지하는지 확인합니다."""
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
