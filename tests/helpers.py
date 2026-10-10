from pathlib import Path
import subprocess
import tempfile
import unittest


class RepositoryTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "B3-2 Tests")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *arguments):
        return subprocess.run(
            ["git", *arguments], cwd=self.root, check=True,
            capture_output=True, text=True, encoding="utf-8",
        ).stdout

    def baseline(self, name="app.py", text="value = 1\n"):
        (self.root / name).write_text(text, encoding="utf-8")
        self.git("add", "--", name)
        self.git("commit", "-m", "test: baseline")
