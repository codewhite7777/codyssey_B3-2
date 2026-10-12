"""실제 임시 Git 저장소의 변경 수집과 status 문자열 해석을 검증합니다.

GitCollectionTests는 파일과 스테이징 상태를 실제로 만든 뒤 collect_changes()를 호출합니다.
GitParsingTests는 잘못된 위치나 status 기록처럼 작은 입력으로 확인할 조건을 다룹니다.
두 방식 모두 AI 호출과 무관하며, Git을 읽는 단계만 독립적으로 검증합니다.
"""

from pathlib import Path
import tempfile
import unittest

from ai_gitgen.errors import UserError
from ai_gitgen.git_changes import collect_changes, parse_status
from tests.helpers import RepositoryTestCase


class GitCollectionTests(RepositoryTestCase):
    """실제 임시 저장소에서 Git 수집 결과와 원본 보존 여부를 확인합니다.

    RepositoryTestCase가 테스트마다 새 저장소를 만들고 끝나면 삭제합니다.
    각 메서드는 필요한 파일 상태를 준비한 뒤 collect_changes(self.root)의 결과를 검사합니다.
    따라서 사용자 저장소를 바꾸지 않고 실제 git status와 git diff의 연결을 확인할 수 있습니다.
    """

    def test_clean_repository(self):
        """변경이 없는 저장소를 빈 파일 목록으로 표현하는지 확인합니다.

        baseline()으로 첫 커밋을 만든 뒤 추가 수정 없이 collect_changes()를 실행합니다.
        files가 빈 튜플인지 검사하여 CLI가 '변경 사항이 없습니다'로 종료할 근거를 확인합니다.
        """
        self.baseline()
        self.assertEqual(collect_changes(self.root).files, ())

    def test_unstaged_and_staged_versions_are_both_read(self):
        """같은 파일의 staged·unstaged 변경을 서로 구분해 수집하는지 확인합니다.

        기준값 1을 2로 바꿔 git add한 뒤 작업 파일을 다시 3으로 수정합니다.
        collect_changes() 결과의 상태가 MM이고 두 diff가 각각 1→2, 2→3을 담는지 봅니다.
        스테이징 뒤 추가로 수정한 내용을 빠뜨리거나 두 변경을 혼동하지 않기 위한 검사입니다.
        """
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
        """첫 커밋이 없는 저장소에서도 스테이징한 새 파일을 읽는지 확인합니다.

        baseline() 없이 파일 작성과 git add만 수행한 뒤 collect_changes()를 호출합니다.
        추가 상태 A와 staged_diff의 파일 내용을 검사해 초기 프로젝트에서도 수집 가능한지 봅니다.
        """
        (self.root / "first.py").write_text("print('hello')\n", encoding="utf-8")
        self.git("add", "first.py")
        change = collect_changes(self.root).files[0]
        self.assertEqual(change.status, "A ")
        self.assertIn("+print('hello')", change.staged_diff)

    def test_untracked_is_a_change_without_invented_diff(self):
        """미추적 파일의 존재와 AI에 보낼 diff의 유무를 구분하는지 확인합니다.

        새 파일만 만들고 git add 없이 collect_changes()를 실행합니다.
        전체 목록에는 한 파일이 있지만 tracked_files는 비고 diff_lines는 0이어야 합니다.
        Git이 제공하지 않은 diff를 만들지 않고 사용자에게 git add를 안내할 근거가 됩니다.
        """
        (self.root / "new.py").write_text("new = True\n", encoding="utf-8")
        changes = collect_changes(self.root)
        self.assertEqual(len(changes.files), 1)
        self.assertEqual(changes.tracked_files, ())
        self.assertEqual(changes.diff_lines, 0)

    def test_rename_with_korean_spaces_and_newline(self):
        """특수 문자가 있는 파일명도 이름 변경 전후의 경로를 정확히 수집하는지 확인합니다.

        한글·공백·줄바꿈을 포함한 파일을 커밋하고 git mv로 이름을 바꿉니다.
        collect_changes()가 새 path, 이전 old_path, 이름 변경 diff를 각각 보존하는지 봅니다.
        파일명을 일반적인 줄 단위 문자열처럼 잘못 나누는 문제를 확인하기 위한 사례입니다.
        """
        old = "기존 파일\n1.py"
        new = "새 파일\n2.py"
        self.baseline(old)
        self.git("mv", old, new)
        change = collect_changes(self.root).files[0]
        self.assertEqual(change.path, new)
        self.assertEqual(change.old_path, old)
        self.assertIn("rename from", change.staged_diff)

    def test_deleted_file(self):
        """삭제한 파일의 이전 내용도 변경 자료에 포함되는지 확인합니다.

        기준 파일을 커밋한 뒤 디스크에서 삭제하고 collect_changes()를 실행합니다.
        unstaged_diff에 기존 값의 삭제 줄이 있는지 검사하여 삭제 변경을 누락하지 않게 합니다.
        """
        self.baseline()
        (self.root / "app.py").unlink()
        change = collect_changes(self.root).files[0]
        self.assertIn("-value = 1", change.unstaged_diff)

    def test_subdirectory_rejected(self):
        """저장소 안이라도 프로젝트 루트가 아닌 위치에서의 실행을 거절하는지 확인합니다.

        임시 저장소 안에 src 폴더를 만든 뒤 그 경로로 collect_changes()를 호출합니다.
        UserError에 '루트' 안내가 포함되는지 검사해 과제의 실행 위치 조건을 확인합니다.
        """
        child = self.root / "src"
        child.mkdir()
        with self.assertRaisesRegex(UserError, "루트"):
            collect_changes(child)

    def test_reading_does_not_stage_or_edit(self):
        """변경 수집이 파일을 수정하거나 스테이징하지 않는 읽기 작업인지 확인합니다.

        기준 파일을 수정한 뒤 Git 상태와 cached diff를 수집 전 값으로 저장합니다.
        collect_changes() 실행 후 두 값과 파일 내용을 다시 읽어 같은지 비교합니다.
        사용자 변경을 분석하는 도구가 검토 대상 자체를 바꾸지 않도록 확인하는 테스트입니다.
        """
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
    """저장소 위치 오류와 status 문자열의 예외적인 기록을 작은 입력으로 검증합니다.

    복잡한 Git 작업을 만들지 않아도 확인할 수 있는 파싱 규칙은 parse_status()에 직접 전달합니다.
    각 메서드는 예상 오류의 종류·안내 문장 또는 반환된 경로를 검사합니다.
    """

    def test_outside_repository_rejected(self):
        """Git 저장소가 아닌 폴더를 명확한 오류로 거절하는지 확인합니다.

        Git을 초기화하지 않은 임시 폴더를 만들고 collect_changes()를 실행합니다.
        UserError와 'Git이 초기화' 안내를 확인하며, with가 끝나면 임시 폴더도 삭제됩니다.
        """
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(UserError, "Git이 초기화"):
                collect_changes(Path(directory))

    def test_conflicts_rejected(self):
        """미해결 병합 충돌을 정상 변경으로 받아들이지 않는지 확인합니다.

        양쪽에서 수정한 충돌 상태 UU가 담긴 status 문자열을 parse_status()에 전달합니다.
        '병합 충돌'을 포함한 UserError가 나야 하며, 불완전한 변경의 초안 생성을 막는 근거입니다.
        """
        with self.assertRaisesRegex(UserError, "병합 충돌"):
            parse_status("## main\0UU app.py\0")

    def test_rename_record_missing_original_path(self):
        """필수 경로가 빠진 이름 변경 기록을 오류로 처리하는지 확인합니다.

        R 상태와 새 이름만 있고 원래 경로는 없는 문자열로 parse_status()를 호출합니다.
        '원래 경로' 안내를 검사해 잘린 기록을 정상적인 이름 변경으로 오해하지 않게 합니다.
        """
        with self.assertRaisesRegex(UserError, "원래 경로"):
            parse_status("## main\0R  renamed.py\0")

    def test_pathspec_magic_is_not_interpreted(self):
        """파일명 파싱 과정에서 Git 경로 패턴 같은 문자를 그대로 보관하는지 확인합니다.

        :(glob)*.py라는 경로가 담긴 status 문자열을 parse_status()에 전달합니다.
        반환한 path가 원문과 같은지 비교하며, 실제 Git 명령의 패턴 확장까지 검사하는 것은 아닙니다.
        """
        changes = parse_status("## main\0 M :(glob)*.py\0")
        self.assertEqual(changes.files[0].path, ":(glob)*.py")
