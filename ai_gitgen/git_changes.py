"""Read Git status/diff without changing the index or working tree."""

from dataclasses import dataclass, replace
import os
from pathlib import Path
import subprocess

from .errors import UserError


@dataclass(frozen=True)
class FileChange:
    status: str
    path: str
    old_path: str | None = None
    staged_diff: str = ""
    unstaged_diff: str = ""

    @property
    def tracked(self) -> bool:
        return self.status != "??"


@dataclass(frozen=True)
class GitChanges:
    branch: str
    files: tuple[FileChange, ...]

    @property
    def tracked_files(self) -> tuple[FileChange, ...]:
        return tuple(item for item in self.files if item.tracked)

    @property
    def diff_lines(self) -> int:
        return sum(
            len(item.staged_diff.splitlines()) + len(item.unstaged_diff.splitlines())
            for item in self.files
        )


def project_root(directory: Path) -> Path:
    root = directory.resolve()
    # A linked worktree uses a .git file, so do not require a directory here.
    if (root / ".git").exists():
        return root
    if any((parent / ".git").exists() for parent in root.parents):
        raise UserError("프로젝트 루트 디렉토리에서 실행해 주세요.")
    raise UserError("Git이 초기화된 프로젝트 루트 디렉토리에서 실행해 주세요.")


def _git(root: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    # Inherited overrides must not redirect reads to another repository/index.
    for name in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        environment.pop(name, None)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
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
    if result.returncode:
        raise UserError("Git 명령이 실패했습니다. 저장소 상태와 접근 권한을 확인해 주세요.")
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise UserError("UTF-8로 읽을 수 없는 파일명 또는 diff입니다. 파일 인코딩을 확인해 주세요.") from error


def parse_status(raw: str) -> GitChanges:
    records = iter(raw.split("\0"))
    branch = "알 수 없음"
    files = []
    for record in records:
        if not record:
            continue
        if record.startswith("## "):
            branch = record[3:]
            continue
        if len(record) < 4 or record[2] != " ":
            raise UserError("Git status 결과 형식을 해석할 수 없습니다.")
        status, path = record[:2], record[3:]
        if status in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}:
            raise UserError("해결되지 않은 병합 충돌이 있습니다. 충돌 해결 후 다시 실행해 주세요.")
        old_path = None
        if "R" in status or "C" in status:
            old_path = next(records, "")
            if not old_path:
                raise UserError("이름이 변경된 파일의 원래 경로를 읽을 수 없습니다.")
        files.append(FileChange(status, path, old_path))
    return GitChanges(branch, tuple(files))


def collect_changes(directory: Path | None = None) -> GitChanges:
    root = project_root(directory or Path.cwd())
    changes = parse_status(_git(
        root, "status", "--porcelain=v1", "-z", "--branch",
        "--untracked-files=all", "--ignore-submodules=none",
    ))
    collected = []
    for item in changes.files:
        if not item.tracked:
            collected.append(item)
            continue
        paths = [item.path] if item.old_path is None else [item.old_path, item.path]
        options = (
            "--no-ext-diff", "--no-textconv", "--no-color", "--unified=3",
            "--ignore-submodules=none",
        )
        staged = ""
        unstaged = ""
        if item.status[0] != " ":
            # No explicit HEAD: --cached also works before the initial commit.
            staged = _git(root, "diff", "--cached", *options, "--", *paths)
        if item.status[1] != " ":
            unstaged = _git(root, "diff", *options, "--", *paths)
        collected.append(replace(item, staged_diff=staged, unstaged_diff=unstaged))
    return replace(changes, files=tuple(collected))
