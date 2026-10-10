from pathlib import Path
import tempfile
import unittest

from ai_gitgen.errors import UserError
from ai_gitgen.git_changes import collect_changes, parse_status
from tests.helpers import RepositoryTestCase


class GitCollectionTests(RepositoryTestCase):
    def test_clean_repository(self):
        self.baseline()
        self.assertEqual(collect_changes(self.root).files, ())

    def test_unstaged_and_staged_versions_are_both_read(self):
        self.baseline()
        source = self.root / "app.py"
        source.write_text("value = 2\n", encoding="utf-8")
        self.git("add", "app.py")
        source.write_text("value = 3\n", encoding="utf-8")
        change = collect_changes(self.root).files[0]
        self.assertEqual(change.status, "MM")
        self.assertIn("+value = 2", change.staged_diff)
        self.assertIn("+value = 3", change.unstaged_diff)
        self.assertIn("-value = 2", change.unstaged_diff)

    def test_staged_initial_commit(self):
        (self.root / "first.py").write_text("print('hello')\n", encoding="utf-8")
        self.git("add", "first.py")
        change = collect_changes(self.root).files[0]
        self.assertEqual(change.status, "A ")
        self.assertIn("+print('hello')", change.staged_diff)

    def test_untracked_is_a_change_without_invented_diff(self):
        (self.root / "new.py").write_text("new = True\n", encoding="utf-8")
        changes = collect_changes(self.root)
        self.assertEqual(len(changes.files), 1)
        self.assertEqual(changes.tracked_files, ())
        self.assertEqual(changes.diff_lines, 0)

    def test_rename_with_korean_spaces_and_newline(self):
        old = "기존 파일\n1.py"
        new = "새 파일\n2.py"
        self.baseline(old)
        self.git("mv", old, new)
        change = collect_changes(self.root).files[0]
        self.assertEqual(change.path, new)
        self.assertEqual(change.old_path, old)
        self.assertIn("rename from", change.staged_diff)

    def test_deleted_file(self):
        self.baseline()
        (self.root / "app.py").unlink()
        change = collect_changes(self.root).files[0]
        self.assertIn("-value = 1", change.unstaged_diff)

    def test_subdirectory_rejected(self):
        child = self.root / "src"
        child.mkdir()
        with self.assertRaisesRegex(UserError, "루트"):
            collect_changes(child)

    def test_reading_does_not_stage_or_edit(self):
        self.baseline()
        source = self.root / "app.py"
        source.write_text("value = 9\n", encoding="utf-8")
        before = self.git("status", "--porcelain=v1")
        index = self.git("diff", "--cached")
        collect_changes(self.root)
        self.assertEqual(self.git("status", "--porcelain=v1"), before)
        self.assertEqual(self.git("diff", "--cached"), index)
        self.assertEqual(source.read_text(encoding="utf-8"), "value = 9\n")


class GitParsingTests(unittest.TestCase):
    def test_outside_repository_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(UserError, "Git이 초기화"):
                collect_changes(Path(directory))

    def test_conflicts_rejected(self):
        with self.assertRaisesRegex(UserError, "병합 충돌"):
            parse_status("## main\0UU app.py\0")

    def test_rename_record_missing_original_path(self):
        with self.assertRaisesRegex(UserError, "원래 경로"):
            parse_status("## main\0R  renamed.py\0")

    def test_pathspec_magic_is_not_interpreted(self):
        changes = parse_status("## main\0 M :(glob)*.py\0")
        self.assertEqual(changes.files[0].path, ":(glob)*.py")
