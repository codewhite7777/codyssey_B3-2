"""Git이 알고 있는 파일 상태와 현재 변경 내용을 읽어 Python 객체로 정리한다.

CLI는 collect_changes()를 호출해 브랜치 상태·파일 목록·diff를 한 번에 받는다.
내부에서는 실행 위치 확인 → git status 해석 → 파일별 git diff 수집 순서로
처리한다. FileChange는 파일 하나를, GitChanges는 전체 수집 결과를 담는다.

이 모듈은 git status·git diff만 호출하며 git add나 commit을 실행하지 않는다.
이미 커밋한 브랜치 이력이 아니라 현재 staged·unstaged 변경을 수집한다.
AI 요청과 현재 API Key 마스킹은 수집 결과를 받은 다른 모듈에서 처리한다.
"""

from dataclasses import dataclass, replace
import os
from pathlib import Path
import subprocess

from .errors import UserError


@dataclass(frozen=True)
class FileChange:
    """파일 하나의 상태·경로·변경 내용을 함께 전달하기 위한 자료 클래스다.

    status는 Git 상태 두 칸으로, 첫 칸은 git add로 선택한 스테이징 영역의
    변경이고 둘째 칸은 작업 폴더에 남은 변경이다. 예를 들어 'M '은 등록된
    수정, ' M'은 미등록 수정, '??'는 Git이 아직 추적하지 않는 새 파일이다.
    path는 현재 경로, old_path는 이름 변경·복사 전 경로이며 없으면 None이다.

    staged_diff에는 git diff --cached, unstaged_diff에는 git diff의 결과를
    담는다. status를 처음 해석할 때는 두 값이 비어 있고, 수집 단계에서 채운다.
    이 객체 자체는 Git을 실행하지 않는다. frozen=True로 필드 재대입을 막아
    수집·마스킹·제한 단계가 원본을 바꾸지 않고 replace()로 복사하도록 한다.
    """

    status: str
    path: str
    old_path: str | None = None
    staged_diff: str = ""
    unstaged_diff: str = ""

    @property
    def tracked(self) -> bool:
        """현재 파일을 diff 수집 대상으로 볼 수 있는지 bool로 반환한다.

        별도 인자 없이 이 객체의 status를 읽고, 미추적 상태 '??'만 제외한다.
        새 파일도 사용자가 git add하여 'A ' 상태가 되면 True다. 이 구분으로
        미추적 파일의 내용을 임의로 읽지 않고, 상태·경로만 안내할 수 있다.
        @property이므로 호출부에서는 item.tracked처럼 괄호 없이 읽는다.
        """
        return self.status != "??"


@dataclass(frozen=True)
class GitChanges:
    """전체 Git 수집 결과를 CLI·안전 처리·프롬프트 구성에 전달하는 자료다.

    branch에는 git status의 브랜치 헤더 내용을 넣는다. 단순 브랜치 이름 외에
    원격 추적 상태 등이 함께 들어갈 수 있다. files는 수집 순서를 유지하는
    FileChange 튜플이며, 변경 파일이 없으면 빈 튜플이다.

    아래 프로퍼티는 보관한 데이터에서 필요한 목록·개수만 계산한다. Git을
    다시 실행하지 않으며, 이 객체도 frozen=True로 필드 재대입을 막는다.
    """

    branch: str
    files: tuple[FileChange, ...]

    @property
    def tracked_files(self) -> tuple[FileChange, ...]:
        """수집 결과에서 미추적 파일을 제외한 목록을 튜플로 반환한다.

        self.files의 각 객체에서 tracked 값을 확인하고 True인 항목만 남긴다.
        원래 순서와 객체를 유지하며, 해당 파일이 없으면 빈 튜플을 반환한다.
        CLI의 분석 대상 확인과 안전 모드의 파일 선택에 사용한다.
        """
        return tuple(item for item in self.files if item.tracked)

    @property
    def diff_lines(self) -> int:
        """현재 객체에 담긴 모든 diff의 줄 수를 합산해 정수로 반환한다.

        각 파일의 staged_diff와 unstaged_diff를 각각 줄 단위로 나눈 뒤
        길이를 더한다. 빈 diff는 0줄이다. 실제 수정한 줄만 세는 것이 아니라
        diff 헤더·추가·삭제·앞뒤 문맥 줄을 모두 포함한다.
        CLI가 수집량과 안전 모드 적용 후 남은 양을 안내할 때 사용한다.
        """
        return sum(
            len(item.staged_diff.splitlines()) + len(item.unstaged_diff.splitlines())
            for item in self.files
        )


def project_root(directory: Path) -> Path:
    """Git 변경을 읽을 실행 위치를 확인하고 절대 경로 Path를 반환한다.

    입력 directory를 정리한 위치에 .git이 있으면 루트로 받아들인다. 이 위치가
    저장소 하위 폴더이면 루트에서 실행하라는 UserError를, 상위에도 .git이
    없으면 Git이 초기화된 프로젝트가 필요하다는 UserError를 발생시킨다.

    collect_changes()가 가장 먼저 호출한다. .git의 존재를 기준으로 실행
    위치를 구분하며, 저장소 내부의 유효성은 뒤이어 실행하는 Git이 확인한다.
    이 함수가 폴더를 이동하거나 저장소를 초기화하지는 않는다.
    """
    # 상대 경로와 '..'를 정리해야 현재 위치와 상위 폴더를 일관되게 확인할 수 있다.
    root = directory.resolve()
    # 연결된 worktree의 .git은 파일일 수 있으므로 디렉터리 여부를 강제하지 않는다.
    if (root / ".git").exists():
        return root
    # 루트로 자동 이동하지 않고 실행 위치를 안내해, 분석 대상을 명확하게 한다.
    if any((parent / ".git").exists() for parent in root.parents):
        raise UserError("프로젝트 루트 디렉토리에서 실행해 주세요.")
    # 현재 위치와 상위 어디에도 .git이 없으면, 저장소 바깥에서 실행한 경우로 안내한다.
    raise UserError("Git이 초기화된 프로젝트 루트 디렉토리에서 실행해 주세요.")


def _git(root: Path, *arguments: str) -> str:
    """Git 실행·결과 읽기·오류 변환을 모아 둔 내부 보조 함수다.

    root는 실행할 프로젝트 위치, arguments는 'status', 'diff'와 그 옵션들이다.
    collect_changes()가 필요한 명령을 전달하면 환경 복사본을 정리하고 해당
    위치에서 실행한 뒤, 성공한 표준 출력을 UTF-8 문자열로 반환한다.

    Git 실행 파일 누락, 실행 중 OS 오류, 명령 하나의 실행 시간 20초 초과,
    Git의 실패 종료 코드, UTF-8 해석 실패를 UserError로 바꾼다. 여기서 직접
    출력하지 않고 CLI가 오류를 한곳에서 안내하도록 전달한다. 공통 처리를
    모아 status와 여러 diff 호출이 같은 실행·오류 처리 방식을 사용하게 한다.
    """
    # Git 프로세스에 줄 환경만 복사한다. 아래 정리가 Python의 원본 환경을 바꾸지 않는다.
    environment = os.environ.copy()
    # 부모 프로세스의 Git 설정이 다른 저장소·인덱스로 읽기 대상을 바꾸지 않게 한다.
    # 복사한 환경만 바꾸므로 사용자의 터미널 환경변수는 그대로 유지된다.
    for name in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        # 설정되어 있지 않은 이름은 그대로 넘어가도록 기본값 None을 사용한다.
        environment.pop(name, None)
    # 상태 확인에 불필요한 인덱스 갱신 등 선택적인 쓰기 작업을 막는다.
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        # 셸 문자열이 아닌 인자 목록을 넘겨 파일명의 공백·특수 문자가 명령이 되지 않게 한다.
        # --literal-pathspecs는 경로를 Git 패턴 대신 문자 그대로 다루도록 한다.
        # core.fsmonitor=false로 파일 감시 기능 호출을 끄고, cwd로 실행 위치를 고정한다.
        # capture_output은 결과를 Python이 받게 하고, check=False는 실패 코드도 직접
        # 검사하게 한다. timeout은 전체 수집이 아니라 이번 Git 명령 하나에 적용된다.
        result = subprocess.run(
            ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *arguments],
            cwd=root, env=environment, capture_output=True, timeout=20,
            check=False,
        )
    except FileNotFoundError as error:
        # 운영체제의 예외를 실행자가 이해할 수 있는 설치 안내로 바꾼다.
        raise UserError("Git 실행 파일을 찾을 수 없습니다. Git을 설치해 주세요.") from error
    except subprocess.TimeoutExpired as error:
        # 응답이 없는 명령을 무한히 기다리지 않도록 정한 제한 시간 초과다.
        raise UserError("Git 명령 실행 시간이 20초를 초과했습니다.") from error
    except OSError as error:
        # 위 두 경우 외의 경로·권한 등 실행 단계 실패도 CLI의 공통 오류 형식에 맞춘다.
        raise UserError("Git 명령을 실행할 수 없습니다. 경로와 권한을 확인해 주세요.") from error
    # check=False로 받았으므로 Git 자체가 보고한 실패도 직접 검사한다.
    if result.returncode:
        raise UserError("Git 명령이 실패했습니다. 저장소 상태와 접근 권한을 확인해 주세요.")
    try:
        # bytes를 문자열로 바꿔야 parse_status와 후속 프롬프트 구성이 텍스트를 다룰 수 있다.
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        # 읽지 못한 문자를 임의로 지우면 파일명·변경 내용이 달라지므로 오류로 중단한다.
        raise UserError("UTF-8로 읽을 수 없는 파일명 또는 diff입니다. 파일 인코딩을 확인해 주세요.") from error


def parse_status(raw: str) -> GitChanges:
    """git status의 일정한 출력 형식을 파일별 데이터로 바꾸는 해석 함수다.

    입력 raw는 --porcelain=v1 -z --branch로 받은 문자열이다. NUL 구분 항목을
    순서대로 읽어 브랜치 헤더, 상태 두 칸, 경로를 구분하고, 이름 변경·복사는
    바로 다음 항목의 이전 경로까지 읽는다. 결과는 GitChanges로 반환한다.

    항목 구조가 맞지 않거나 이전 경로가 빠졌거나 병합 충돌이 남아 있으면
    UserError를 발생시킨다. 이 단계의 FileChange에는 아직 diff가 없으며,
    collect_changes()가 이 상태 정보를 보고 필요한 diff 명령을 선택한다.
    문자열만 입력받으므로 Git을 실제 실행하지 않고 해석 로직을 시험할 수 있다.
    """
    # NUL로 나누면 파일명에 공백이나 줄바꿈이 있어도 파일 경계를 구분할 수 있다.
    records = iter(raw.split("\0"))
    # 브랜치 헤더를 만나면 덮어쓰고, 파일 항목은 출력된 순서대로 모은다.
    branch = "알 수 없음"
    files = []
    for record in records:
        if not record:
            # 마지막 NUL 뒤에 생기는 빈 항목 등은 파일 정보가 아니므로 건너뛴다.
            continue
        if record.startswith("## "):
            # --branch 헤더의 내용을 보관한다. 원격 추적 상태 등이 함께 올 수 있다.
            branch = record[3:]
            # 브랜치 헤더를 아래의 일반 파일 항목으로 다시 해석하지 않는다.
            continue
        # 파일 항목은 '상태 두 칸 + 공백 + 경로'여야 잘못된 위치에서 자르지 않는다.
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
            # next()로 이전 경로를 여기서 소비하여 다음 반복에서 새 파일로 오해하지 않는다.
            old_path = next(records, "")
            if not old_path:
                # 원래 경로가 없으면 이름 변경의 양쪽 변경을 올바르게 수집할 수 없다.
                raise UserError("이름이 변경된 파일의 원래 경로를 읽을 수 없습니다.")
        # 현재는 상태·경로만 저장하고 diff 필드는 기본값인 빈 문자열로 남긴다.
        files.append(FileChange(status, path, old_path))
    # 바깥으로 전달할 목록은 튜플로 만들어 후속 단계가 원본 목록을 늘리거나 줄이지 않게 한다.
    return GitChanges(branch, tuple(files))


def collect_changes(directory: Path | None = None) -> GitChanges:
    """CLI가 필요한 Git 변경 정보를 받기 위해 호출하는 수집의 시작점이다.

    directory는 프로젝트 루트 Path이며 생략하면 현재 작업 폴더를 사용한다.
    위치 확인 후 git status를 해석하고, 추적 파일마다 상태 두 칸을 기준으로
    staged(git diff --cached)와 unstaged(git diff)를 따로 읽는다. 같은 파일에
    두 종류의 변경이 모두 있으면 둘 다 보관하며 하나의 diff로 합치지 않는다.

    반환값은 브랜치 상태·파일 목록·diff가 담긴 GitChanges다. 미추적 파일은
    내용 없이 상태·경로만 남겨 사용자가 git add 여부를 결정하도록 한다.
    변경이 없으면 files가 빈 결과를 반환하며, 안내·종료는 CLI에서 처리한다.
    루트 확인·Git 실행·status 해석의 UserError는 호출부로 전달한다.
    """
    # 호출자가 경로를 지정하지 않았을 때만 이 프로그램을 실행한 폴더를 기준으로 삼는다.
    root = project_root(directory or Path.cwd())
    # porcelain은 파싱하기 일정한 형식, -z는 NUL 경계, --branch는 브랜치 헤더를 요청한다.
    # 새 파일은 폴더 하나로 뭉뚱그리지 않고 개별 목록으로 받고, 서브모듈 변경도 숨기지 않는다.
    changes = parse_status(_git(
        root, "status", "--porcelain=v1", "-z", "--branch",
        "--untracked-files=all", "--ignore-submodules=none",
    ))
    collected = []
    for item in changes.files:
        if not item.tracked:
            # 새 파일 내용을 직접 읽지 않는다. 필요하면 사용자가 git add한 뒤 실행한다.
            collected.append(item)
            # 이 항목은 diff 없이 보관했으므로 아래의 추적 파일용 명령을 실행하지 않는다.
            continue
        # 이름 변경은 이전·현재 경로를 함께 지정해야 삭제/추가 변경을 모두 읽는다.
        paths = [item.path] if item.old_path is None else [item.old_path, item.path]
        # 저장소 설정의 외부 diff·변환 프로그램은 실행하지 않고, 색상 제어 문자도 제외한다.
        # 변경 앞뒤 문맥 3줄은 AI가 어느 부분의 수정인지 이해하도록 함께 받는다.
        options = (
            "--no-ext-diff", "--no-textconv", "--no-color", "--unified=3",
            "--ignore-submodules=none",
        )
        # 상태상 변경이 없는 쪽은 Git 명령을 생략하되, 반환 객체의 diff 필드는 유지한다.
        staged = ""
        unstaged = ""
        # 첫 칸이 공백이 아니면 git add로 선택된 내용이다. '--'는 옵션과 파일 경로를 나눈다.
        if item.status[0] != " ":
            # HEAD를 명시하지 않아 최초 커밋이 없는 저장소에서도 --cached가 동작한다.
            staged = _git(root, "diff", "--cached", *options, "--", *paths)
        # 둘째 칸의 변경은 작업 폴더에 남은 내용이다. staged와 함께 수집될 수도 있다.
        if item.status[1] != " ":
            unstaged = _git(root, "diff", *options, "--", *paths)
        # 불변 데이터 객체는 원본 필드를 대입 수정하지 않고 새 객체로 확장한다.
        collected.append(replace(item, staged_diff=staged, unstaged_diff=unstaged))
    # 브랜치 정보는 유지하면서, 상태뿐이던 파일 목록을 diff가 채워진 목록으로 교체한다.
    return replace(changes, files=tuple(collected))
