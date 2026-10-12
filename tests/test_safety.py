"""현재 Key의 문자열 마스킹과 안전 모드의 10개 파일·합계 200줄 제한을 검증합니다.

문자열 하나, GitChanges 전체, 실제 Git에서 수집한 결과를 나누어 마스킹을 확인합니다.
안전 모드는 파일 수와 모든 diff를 합친 줄 수의 경계값을 검사합니다.
모든 Key는 가짜 값이며, 이 테스트는 다른 종류의 민감정보 자동 탐지를 검증하지 않습니다.
"""

from dataclasses import asdict
import unittest

from ai_gitgen.git_changes import FileChange, GitChanges, collect_changes
from ai_gitgen.safety import limit_changes, redact, redact_changes
from tests.helpers import RepositoryTestCase


FAKE_KEY = "FAKE_KEY_FOR_TEST"


class RedactTests(unittest.TestCase):
    """문자열을 받아 현재 Key와 같은 부분만 바꾸는 redact()의 기본 동작을 확인합니다.

    단일 등장·여러 등장·등장하지 않는 경우·빈 Key를 각각 입력합니다.
    반환 문자열 전체를 비교하여 가릴 부분은 바꾸고 나머지 문자는 보존하는지 검사합니다.
    """

    def test_masks_one_occurrence(self):
        """문장 안의 현재 Key 한 곳을 정해진 마스킹 표기로 바꾸는지 확인합니다.

        가짜 Key가 포함된 문장과 같은 Key를 redact()의 두 인자로 전달합니다.
        결과가 'API Key: [REDACTED]'인지 비교해 핵심 치환 동작을 확인합니다.
        """
        text = "API Key: FAKE_KEY_FOR_TEST"

        result = redact(text, "FAKE_KEY_FOR_TEST")

        self.assertEqual(result, "API Key: [REDACTED]")

    def test_masks_both_occurrences_in_added_and_deleted_diff_lines(self):
        """추가 줄과 삭제 줄 모두에서 현재 Key를 가리는지 확인합니다.

        같은 Key가 있는 -줄·+줄과 Key가 없는 문맥 줄을 한 문자열로 준비합니다.
        redact() 실행 후 두 Key는 바뀌고 줄 기호·문맥·줄바꿈은 그대로인지 비교합니다.
        파일에서 지운 비밀값도 diff에는 남을 수 있으므로 삭제 줄까지 검사합니다.
        """
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
        """마스킹 대상이 없는 일반 문장을 바꾸지 않는지 확인합니다.

        지정한 가짜 Key가 들어 있지 않은 코드 한 줄을 redact()에 전달합니다.
        반환값을 입력과 비교해 관계없는 변경 내용까지 훼손하지 않는지 봅니다.
        """
        text = "+print('hello')\n"

        result = redact(text, "FAKE_KEY_FOR_TEST")

        self.assertEqual(result, text)

    def test_preserves_original_text_when_secret_is_empty(self):
        """빈 Key를 전달했을 때 문자열 전체가 잘못 치환되지 않는지 확인합니다.

        문장에는 가짜 Key를 넣되 redact()의 secret 인자는 빈 문자열로 전달합니다.
        원문이 유지되어야 하며, 빈 문자열을 모든 문자 사이에서 치환하는 실수를 막는 검사입니다.
        """
        text = "API Key: FAKE_KEY_FOR_TEST"

        result = redact(text, "")

        self.assertEqual(result, text)


class RedactChangesTests(unittest.TestCase):
    """GitChanges 전체에서 Key를 가리면서 원본 데이터는 보존하는지 확인합니다.

    FileChange와 GitChanges를 직접 만들어 diff뿐 아니라 브랜치·경로에도 Key를 넣습니다.
    redact_changes()가 새 객체를 반환하고 상태·순서·없음(None) 표시는 유지하는지 비교합니다.
    asdict()는 중첩된 데이터도 사전으로 풀어 원본의 값이 바뀌지 않았는지 확인할 때 사용합니다.
    """

    def test_masks_added_deleted_and_context_lines_in_both_diffs(self):
        """staged·unstaged의 모든 종류의 줄에 같은 마스킹을 적용하는지 확인합니다.

        한 파일의 두 diff에 추가·삭제·문맥 줄을 만들고 각 줄에 가짜 Key를 넣습니다.
        redact_changes() 결과의 두 문자열 전체를 비교해 빠진 위치가 없는지 확인합니다.
        전송 자료에는 변경 줄 이외의 주변 내용도 포함되므로 문맥 줄을 함께 검사합니다.
        """
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
        """파일 내용 밖의 Key도 가리면서 변경 목록의 구조와 원본은 보존하는지 확인합니다.

        브랜치, 이름 변경 전후 경로, 미추적 파일 이름에 가짜 Key를 넣어 자료를 준비합니다.
        redact_changes() 결과에서 이름만 바뀌고 상태·순서·old_path의 None은 유지되는지 봅니다.
        assertIsNot은 복사본인지, asdict 비교는 입력 자료의 값이 그대로인지 각각 검사합니다.
        """
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
        """치환할 내용이 없는 경우에도 원본을 바꾸지 않고 같은 내용의 복사본을 반환하는지 봅니다.

        자료에 Key가 없는 경우와 secret이 빈 문자열인 경우를 각각 준비합니다.
        redact_changes() 결과가 입력과 같은 값이지만 별도 객체인지 검사합니다.
        subTest로 실패한 입력을 구분하고, 원본을 사전으로 비교해 의도하지 않은 수정을 찾습니다.
        """
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
    """실제 Git에서 얻은 변경을 마스킹하는 과정과 원본 보존을 함께 확인합니다.

    RepositoryTestCase의 임시 저장소를 사용하므로 파일 내용과 Git index까지 직접 비교합니다.
    모델에 보낼 수집 자료만 가려야 하고, 사용자가 작성한 파일이나 스테이징 결과는 남아야 합니다.
    """

    def test_masks_collected_diffs_without_changing_files_index_or_source(self):
        """실제 diff를 가린 뒤에도 파일·스테이징·수집 원본이 그대로인지 확인합니다.

        가짜 Key가 있는 파일을 기준 커밋 → staged 수정 → unstaged 수정 순서로 준비합니다.
        collect_changes() 결과를 redact_changes()에 전달해 두 diff의 추가·삭제·문맥을 검사합니다.
        저장해 둔 파일과 Git index의 바이트, 원본 객체를 다시 비교해 디스크를 바꾸지 않았는지 봅니다.
        """
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
    """안전 모드의 파일 수·전체 줄 수 제한과 원본 보존을 확인합니다.

    GitChanges를 직접 만들고 limit_changes()가 돌려준 전송용 복사본을 검사합니다.
    제한 경계에 딱 맞는 경우와 초과한 경우를 비교하여 최대 10개 파일·합계 200줄 규칙을 확인합니다.
    """

    def test_keeps_first_ten_files_with_tracked_diffs_and_skips_empty_files(self):
        """전송할 내용이 있는 추적 파일에 대해서만 최대 10개 제한을 적용하는지 확인합니다.

        빈 diff·미추적 파일을 먼저 두고, 뒤에 유효한 파일 10개 또는 11개를 붙여 준비합니다.
        limit_changes() 결과가 처음 10개 유효 파일과 같은지 비교합니다.
        전송 대상이 아닌 파일이 개수를 차지하지 않는지와 원본이 보존되는지도 함께 봅니다.
        """
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
        """200줄 제한을 각 diff가 따로 받는 것이 아니라 전체가 함께 쓰는지 확인합니다.

        첫 파일 120줄과 두 번째 파일의 staged 60줄·unstaged 20줄을 기준으로 준비합니다.
        limit_changes()가 초과 줄과 후속 파일을 제외하고 합계 200줄만 남기는지 비교합니다.
        정확히 200줄인 경우도 검사하며, 남긴 내용의 CRLF 줄바꿈과 입력 원본은 유지되어야 합니다.
        """
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
        """제한을 넘지 않는 자료는 내용을 잃지 않고 복사본으로 반환되는지 확인합니다.

        짧은 이름 변경 diff와 파일이 없는 GitChanges를 각각 limit_changes()에 전달합니다.
        결과의 diff·상태·경로·브랜치가 입력과 같고, 반환 객체는 새 객체인지 비교합니다.
        안전 모드를 켰다는 이유만으로 작은 변경의 내용이 바뀌지 않도록 확인합니다.
        """
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
