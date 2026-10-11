"""실제 임시 Git 저장소의 변경 수집과 status 문자열 해석을 검증합니다."""

from pathlib import Path
import tempfile
import unittest

from ai_gitgen.errors import UserError
from ai_gitgen.git_changes import collect_changes, parse_status
from tests.helpers import RepositoryTestCase


class GitCollectionTests(RepositoryTestCase):
    """파일·스테이징 상태를 직접 만든 뒤 수집 결과와 원본 보존 여부를 확인합니다."""

    def test_clean_repository(self):
        """첫 커밋 이후 수정이 없으면 변경 파일 목록이 비어 있는지 확인합니다."""
        self.baseline()
        self.assertEqual(collect_changes(self.root).files, ())

    def test_unstaged_and_staged_versions_are_both_read(self):
        """같은 파일을 스테이징한 뒤 다시 수정해 두 diff가 각각 수집되는지 확인합니다."""
        self.baseline()
        source = self.root / "app.py"
        # 기준값 1에서 2로 바꿔 스테이징하고, 작업 폴더에서는 다시 3으로 바꿉니다.
        source.write_text("value = 2\n", encoding="utf-8")
        self.git("add", "app.py")
        source.write_text("value = 3\n", encoding="utf-8")
        change = collect_changes(self.root).files[0]
        # MM 상태에서 staged는 1→2, unstaged는 2→3의 차이를 담아야 합니다.
        self.assertEqual(change.status, "MM")
        self.assertIn("+value = 2", change.staged_diff)
        self.assertIn("+value = 3", change.unstaged_diff)
        self.assertIn("-value = 2", change.unstaged_diff)

    def test_staged_initial_commit(self):
        """아직 커밋이 없는 저장소에서도 git add한 새 파일의 diff를 읽는지 확인합니다."""
        (self.root / "first.py").write_text("print('hello')\n", encoding="utf-8")
        self.git("add", "first.py")
        change = collect_changes(self.root).files[0]
        self.assertEqual(change.status, "A ")
        self.assertIn("+print('hello')", change.staged_diff)

    def test_untracked_is_a_change_without_invented_diff(self):
        """추적되지 않은 새 파일은 목록에 표시하되 diff는 임의로 만들지 않는지 확인합니다."""
        (self.root / "new.py").write_text("new = True\n", encoding="utf-8")
        changes = collect_changes(self.root)
        self.assertEqual(len(changes.files), 1)
        self.assertEqual(changes.tracked_files, ())
        self.assertEqual(changes.diff_lines, 0)

    def test_rename_with_korean_spaces_and_newline(self):
        """한글·공백·줄바꿈이 있는 이름을 변경해 이전 경로와 새 경로를 구분하는지 확인합니다."""
        old = "기존 파일\n1.py"
        new = "새 파일\n2.py"
        self.baseline(old)
        self.git("mv", old, new)
        change = collect_changes(self.root).files[0]
        self.assertEqual(change.path, new)
        self.assertEqual(change.old_path, old)
        self.assertIn("rename from", change.staged_diff)

    def test_deleted_file(self):
        """추적 중인 파일을 삭제하면 삭제된 내용이 unstaged diff에 나타나는지 확인합니다."""
        self.baseline()
        (self.root / "app.py").unlink()
        change = collect_changes(self.root).files[0]
        self.assertIn("-value = 1", change.unstaged_diff)

    def test_subdirectory_rejected(self):
        """저장소 하위 폴더에서 수집을 요청하면 루트에서 실행하라는 오류가 나는지 확인합니다."""
        child = self.root / "src"
        child.mkdir()
        with self.assertRaisesRegex(UserError, "루트"):
            collect_changes(child)

    def test_reading_does_not_stage_or_edit(self):
        """수집 전후의 Git 상태·스테이징 내용·파일 내용을 비교해 읽기 동작인지 확인합니다."""
        self.baseline()
        source = self.root / "app.py"
        source.write_text("value = 9\n", encoding="utf-8")
        # 변경을 수집하기 직전 상태를 보관한 뒤 같은 항목을 다시 읽어 비교합니다.
        before = self.git("status", "--porcelain=v1")
        index = self.git("diff", "--cached")
        collect_changes(self.root)
        self.assertEqual(self.git("status", "--porcelain=v1"), before)
        self.assertEqual(self.git("diff", "--cached"), index)
        self.assertEqual(source.read_text(encoding="utf-8"), "value = 9\n")


class GitParsingTests(unittest.TestCase):
    """저장소 위치 오류와 status의 특수 기록을 작은 입력으로 검증합니다."""

    def test_outside_repository_rejected(self):
        """Git을 초기화하지 않은 임시 폴더에서는 수집이 거절되는지 확인합니다."""
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(UserError, "Git이 초기화"):
                collect_changes(Path(directory))

    def test_conflicts_rejected(self):
        """UU 상태를 전달하면 미해결 병합 충돌을 설명하는 오류가 발생하는지 확인합니다."""
        with self.assertRaisesRegex(UserError, "병합 충돌"):
            parse_status("## main\0UU app.py\0")

    def test_rename_record_missing_original_path(self):
        """이름 변경 기록에 이전 경로가 빠졌을 때 불완전한 status를 거절하는지 확인합니다."""
        with self.assertRaisesRegex(UserError, "원래 경로"):
            parse_status("## main\0R  renamed.py\0")

    def test_pathspec_magic_is_not_interpreted(self):
        """Git 경로 패턴처럼 생긴 파일명도 파싱 단계에서는 원문 그대로 보관하는지 확인합니다."""
        changes = parse_status("## main\0 M :(glob)*.py\0")
        self.assertEqual(changes.files[0].path, ":(glob)*.py")
