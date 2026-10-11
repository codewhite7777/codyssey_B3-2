"""git status·git diff로 변경 정보를 읽어 파일별 객체로 정리한다.

Git 수집만 담당하며, 스테이징 영역이나 작업 파일을 수정하지 않는다.
AI 요청과 민감정보 마스킹은 수집 결과를 받은 다른 모듈에서 처리한다.
"""

from dataclasses import dataclass, replace
import os
from pathlib import Path
import subprocess

from .errors import UserError


@dataclass(frozen=True)
class FileChange:
    """파일 하나의 Git 상태·경로와 staged/unstaged diff를 보관한다.

    status의 첫 칸은 스테이징 영역, 둘째 칸은 작업 폴더의 상태다.
    old_path는 이름 변경·복사 전 경로이며, 해당하지 않으면 None이다.
    frozen=True이므로 값을 바꿀 때는 replace()로 새 객체를 만든다.
    """

    status: str
    path: str
    old_path: str | None = None
    staged_diff: str = ""
    unstaged_diff: str = ""

    @property
    def tracked(self) -> bool:
        """미추적 파일을 뜻하는 '??' 상태가 아니면 True를 반환한다."""
        return self.status != "??"


@dataclass(frozen=True)
class GitChanges:
    """브랜치 상태 문자열과 파일별 변경 목록을 하나의 수집 결과로 묶는다.

    files는 FileChange 객체의 튜플이며, Git 원본을 수정하는 기능은 없다.
    """

    branch: str
    files: tuple[FileChange, ...]

    @property
    def tracked_files(self) -> tuple[FileChange, ...]:
        """전체 파일 목록에서 미추적 파일을 제외한 튜플을 반환한다."""
        return tuple(item for item in self.files if item.tracked)

    @property
    def diff_lines(self) -> int:
        """모든 파일의 staged·unstaged diff 줄 수를 합산해 반환한다.

        추가·삭제한 줄뿐 아니라 diff 헤더와 앞뒤 문맥 줄도 포함한다.
        """
        return sum(
            len(item.staged_diff.splitlines()) + len(item.unstaged_diff.splitlines())
            for item in self.files
        )


def project_root(directory: Path) -> Path:
    """입력 경로를 절대 경로로 정리하고 Git 프로젝트 루트이면 반환한다.

    상위 폴더에만 .git이 있거나 .git을 찾지 못하면 UserError로 안내한다.
    실제 저장소가 정상인지는 뒤이어 실행하는 Git 명령에서 확인한다.
    """
    root = directory.resolve()
    # 연결된 worktree의 .git은 파일일 수 있으므로 디렉터리 여부를 강제하지 않는다.
    if (root / ".git").exists():
        return root
    # 루트로 자동 이동하지 않고 실행 위치를 안내해, 분석 대상을 명확하게 한다.
    if any((parent / ".git").exists() for parent in root.parents):
        raise UserError("프로젝트 루트 디렉토리에서 실행해 주세요.")
    raise UserError("Git이 초기화된 프로젝트 루트 디렉토리에서 실행해 주세요.")


def _git(root: Path, *arguments: str) -> str:
    """root에서 전달받은 Git 명령을 실행하고 표준 출력을 UTF-8 문자열로 반환한다.

    호출부는 status·diff를 전달한다. 실행 파일 누락, 실행 실패, 20초 초과,
    UTF-8 해석 실패는 CLI가 출력할 수 있는 UserError로 바꾼다.
    """
    environment = os.environ.copy()
    # 부모 프로세스의 Git 설정이 다른 저장소·인덱스로 읽기 대상을 바꾸지 않게 한다.
    # 복사한 환경만 바꾸므로 사용자의 터미널 환경변수는 그대로 유지된다.
    for name in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        environment.pop(name, None)
    # 상태 확인에 불필요한 인덱스 갱신 등 선택적인 쓰기 작업을 막는다.
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        # 인자 목록으로 실행해 셸 해석을 거치지 않는다. 경로는 패턴 대신 문자 그대로
        # 취급하고, 파일 감시 기능 호출을 끈다. 출력은 터미널 대신 프로그램이 받는다.
        result = subprocess.run(
            ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *arguments],
            cwd=root, env=environment, capture_output=True, timeout=20,
            check=False,
        )
    except FileNotFoundError as error:
        raise UserError("Git 실행 파일을 찾을 수 없습니다. Git을 설치해 주세요.") from error
    except subprocess.TimeoutExpired as error:
        raise UserError("Git 명령 실행 시간이 20초를 초과했습니다.") from error
    except OSError as error:
        raise UserError("Git 명령을 실행할 수 없습니다. 경로와 권한을 확인해 주세요.") from error
    # check=False로 받았으므로 Git 자체가 보고한 실패도 직접 검사한다.
    if result.returncode:
        raise UserError("Git 명령이 실패했습니다. 저장소 상태와 접근 권한을 확인해 주세요.")
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise UserError("UTF-8로 읽을 수 없는 파일명 또는 diff입니다. 파일 인코딩을 확인해 주세요.") from error


def parse_status(raw: str) -> GitChanges:
    """porcelain v1·-z 형식의 status 문자열을 GitChanges로 변환한다.

    파일 상태 두 칸과 경로를 분리하고, 이름 변경·복사의 이전 경로도 읽는다.
    형식이 잘못되었거나 해결되지 않은 병합 충돌이 있으면 UserError를 낸다.
    이 단계는 상태·경로만 해석하며 diff 내용은 collect_changes()에서 채운다.
    """
    # NUL로 나누면 파일명에 공백이나 줄바꿈이 있어도 파일 경계를 구분할 수 있다.
    records = iter(raw.split("\0"))
    branch = "알 수 없음"
    files = []
    for record in records:
        if not record:
            continue
        if record.startswith("## "):
            # --branch 헤더의 내용을 보관한다. 원격 추적 상태 등이 함께 올 수 있다.
            branch = record[3:]
            continue
        if len(record) < 4 or record[2] != " ":
            raise UserError("Git status 결과 형식을 해석할 수 없습니다.")
        # 앞 두 칸은 인덱스/작업 폴더 상태이고, 세 번째 칸의 공백 뒤가 경로다.
        status, path = record[:2], record[3:]
        # 충돌이 남은 내용을 정상 변경처럼 요약하지 않도록 수집을 중단한다.
        if status in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}:
            raise UserError("해결되지 않은 병합 충돌이 있습니다. 충돌 해결 후 다시 실행해 주세요.")
        old_path = None
        if "R" in status or "C" in status:
            # -z의 이름 변경·복사 형식은 현재 경로 다음 NUL 항목에 이전 경로가 온다.
            old_path = next(records, "")
            if not old_path:
                raise UserError("이름이 변경된 파일의 원래 경로를 읽을 수 없습니다.")
        files.append(FileChange(status, path, old_path))
    return GitChanges(branch, tuple(files))


def collect_changes(directory: Path | None = None) -> GitChanges:
    """지정한 프로젝트 루트의 상태와 파일별 diff를 수집해 GitChanges로 반환한다.

    directory를 생략하면 현재 작업 디렉터리를 사용한다. 추적 파일은 staged와
    unstaged 변경을 따로 읽고, 미추적 파일은 상태·경로만 남긴다. 루트·Git 실행·
    status 해석 오류는 UserError로 전달하며, 파일을 추가하거나 수정하지 않는다.
    """
    root = project_root(directory or Path.cwd())
    # 사람이 읽는 안내 문장 대신 일정한 형식을 받고, 미추적 파일도 목록에 포함한다.
    changes = parse_status(_git(
        root, "status", "--porcelain=v1", "-z", "--branch",
        "--untracked-files=all", "--ignore-submodules=none",
    ))
    collected = []
    for item in changes.files:
        if not item.tracked:
            # 새 파일 내용을 직접 읽지 않는다. 필요하면 사용자가 git add한 뒤 실행한다.
            collected.append(item)
            continue
        # 이름 변경은 이전·현재 경로를 함께 지정해야 삭제/추가 변경을 모두 읽는다.
        paths = [item.path] if item.old_path is None else [item.old_path, item.path]
        # 외부 diff·변환 프로그램과 색상 출력을 끄고, 변경 앞뒤 문맥은 3줄로 받는다.
        options = (
            "--no-ext-diff", "--no-textconv", "--no-color", "--unified=3",
            "--ignore-submodules=none",
        )
        staged = ""
        unstaged = ""
        # 첫 칸의 변경은 git add로 선택된 내용이다. '--' 뒤 인자는 파일 경로다.
        if item.status[0] != " ":
            # HEAD를 명시하지 않아 최초 커밋이 없는 저장소에서도 --cached가 동작한다.
            staged = _git(root, "diff", "--cached", *options, "--", *paths)
        # 둘째 칸의 변경은 작업 폴더에 남은 내용이다. staged와 함께 수집될 수도 있다.
        if item.status[1] != " ":
            unstaged = _git(root, "diff", *options, "--", *paths)
        # 불변 데이터 객체는 원본 필드를 대입 수정하지 않고 새 객체로 확장한다.
        collected.append(replace(item, staged_diff=staged, unstaged_diff=unstaged))
    return replace(changes, files=tuple(collected))
