"""터미널 실행의 시작점: python3 main.py commit 또는 python3 main.py pr로 실행한다.

Git 프로젝트 루트에서 실행한다. 실제 처리 순서는 ai_gitgen/cli.py의 main()에 있다.
"""

from ai_gitgen.cli import main


if __name__ == "__main__":
    # 직접 실행할 때만 CLI를 시작하고, 반환값을 셸의 종료 코드(echo $?)로 전달한다.
    raise SystemExit(main())
