"""사용자 저장소에 영향을 주지 않는 임시 Git 저장소를 테스트마다 준비합니다.

Git 수집·CLI 통합 테스트는 문자열을 흉내 내는 것만으로는 부족하므로 실제 Git을 씁니다.
이 모듈은 저장소 생성, Git 명령 실행, 기준 커밋 준비를 공통으로 제공하며,
각 테스트가 끝나면 임시 폴더를 지워 다음 테스트와 사용자의 작업을 보호합니다.
"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class RepositoryTestCase(unittest.TestCase):
    """실제 Git이 필요한 테스트 클래스가 상속하는 공통 준비 도구입니다.

    unittest.TestCase를 상속하므로 assertEqual 등의 검증 함수를 그대로 사용할 수 있습니다.
    자식 클래스의 각 test_* 실행 전에 setUp이 새 저장소를 만들고,
    self.root와 git()/baseline()을 제공해 테스트끼리 변경 내용이 섞이지 않게 합니다.
    """

    def setUp(self):
        """각 테스트가 사용할 빈 Git 저장소를 만들고 정리 작업을 등록합니다.

        unittest가 자동으로 호출하므로 별도의 입력 인자는 받지 않습니다.
        임시 폴더 경로를 self.root에 저장한 뒤 main 브랜치와 테스트 작성자를 설정합니다.
        반환값 대신 이 인스턴스 상태를 이후 도우미와 테스트가 함께 사용합니다.
        addCleanup은 테스트가 실패하더라도 임시 폴더를 삭제하도록 등록하는 장치입니다.
        """
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # 테스트용 커밋을 만들 수 있도록 이 임시 저장소 안에서만 작성자와 서명을 설정합니다.
        self.git("init", "-b", "main")
        self.git("config", "user.name", "B3-2 Tests")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *arguments):
        """전달한 Git 인자를 임시 저장소에서 실행하고 표준 출력을 문자열로 반환합니다.

        *arguments로 받은 명령과 옵션을 목록으로 전달하며, cwd를 self.root로 고정합니다.
        check=True이므로 Git이 실패하면 예외가 나고 테스트 준비 실패를 숨기지 않습니다.
        capture_output은 터미널 대신 메모리로 출력을 받고, UTF-8 문자열로 해석합니다.
        테스트 준비·검증에 필요한 add/commit도 여기서 실행합니다.
        실제 CLI 프로그램이 허용하는 Git 호출 범위와는 별개인 테스트 도우미입니다.
        """
        return subprocess.run(
            ["git", *arguments], cwd=self.root, check=True,
            capture_output=True, text=True, encoding="utf-8",
        ).stdout

    def baseline(self, name="app.py", text="value = 1\n"):
        """파일 이름과 초기 내용을 받아 변경 전 기준 커밋을 준비합니다.

        name/text를 생략하면 app.py에 value = 1인 파일을 만듭니다.
        파일 작성 → git add → git commit 순서로 저장해 이후 수정과 비교할 기준을 남깁니다.
        값을 반환하지 않으며, 만들어진 파일과 커밋은 해당 테스트의 임시 저장소에만 남습니다.
        """
        (self.root / name).write_text(text, encoding="utf-8")
        self.git("add", "--", name)
        self.git("commit", "-m", "test: baseline")
