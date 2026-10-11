"""사용자 저장소에 영향을 주지 않는 임시 Git 저장소를 테스트마다 준비합니다."""

from pathlib import Path
import subprocess
import tempfile
import unittest


class RepositoryTestCase(unittest.TestCase):
    """실제 Git 수집을 검증하는 테스트들이 공통으로 상속하는 준비 도구입니다."""

    def setUp(self):
        """각 테스트 전 빈 저장소를 만들고, 테스트가 끝나면 삭제하도록 등록합니다."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # 테스트용 커밋을 만들 수 있도록 이 임시 저장소 안에서만 작성자와 서명을 설정합니다.
        self.git("init", "-b", "main")
        self.git("config", "user.name", "B3-2 Tests")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *arguments):
        """임시 저장소에서 Git을 실행하고 표준 출력을 문자열로 반환합니다.

        테스트 준비·검증에 필요한 add/commit도 여기서 실행합니다.
        실제 CLI 프로그램이 허용하는 Git 호출 범위와는 별개인 테스트 도우미입니다.
        """
        return subprocess.run(
            ["git", *arguments], cwd=self.root, check=True,
            capture_output=True, text=True, encoding="utf-8",
        ).stdout

    def baseline(self, name="app.py", text="value = 1\n"):
        """비교 기준 파일을 작성하고 첫 커밋을 만들어 이후 diff의 기준점을 마련합니다."""
        (self.root / name).write_text(text, encoding="utf-8")
        self.git("add", "--", name)
        self.git("commit", "-m", "test: baseline")
