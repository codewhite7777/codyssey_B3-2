"""프로젝트 루트에서 실행하는 CLI의 시작 파일.

실행 예: python3 main.py commit / python3 main.py pr
이 파일은 실행을 시작하고 종료 코드를 터미널에 전달하는 역할만 담당한다.
옵션 해석, Git 수집, Key 확인, Gemini 요청, 결과 출력은 cli.main()이 연결한다.
main.py라는 파일명과 가져온 main() 함수는 구분해서 읽으면 된다.
"""

# ai_gitgen 패키지에서 실제 진행 함수를 가져온다. 여기서 새 main()을 정의하지 않는다.
from ai_gitgen.cli import main


if __name__ == "__main__":
    # 직접 실행할 때 __name__은 "__main__"이 된다. 다른 코드에서 import만 하면
    # 이 블록을 건너뛰므로 Git 수집이나 API 요청이 자동으로 시작되지 않는다.
    # main()의 반환값 0(정상) 또는 1(처리 오류)을 SystemExit로 셸에 전달한다.
    # 잘못된 옵션은 argparse가 별도로 2로 종료한다. 터미널에서는 echo $?로 확인한다.
    raise SystemExit(main())
