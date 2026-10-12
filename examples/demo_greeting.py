"""AI가 설명할 작은 코드 변경을 만들기 위한 인사말 예제.

examples/의 원본을 프로젝트 루트로 복사하고 git add하면 새 파일의 내용이
diff에 포함된다. 그 변경으로 main.py의 commit/pr 명령을 각각 시연할 수 있다.
이 예제 자체는 Git이나 Gemini를 호출하지 않고 인사말만 출력한다.
"""


def greet(name: str) -> str:
    """입력한 이름을 일정한 형식의 인사말로 바꾼다.

    입력: 인사할 대상의 이름 문자열 name.
    처리: strip()으로 이름 앞뒤 공백을 없애고 문장 안에 넣는다.
    반환: '안녕하세요, 이름님!' 형식의 문자열. 함수 안에서 출력하지는 않는다.
    예: greet(" Codyssey ")는 '안녕하세요, Codyssey님!'을 반환한다.
    별도 입력 검증은 없으며 빈 이름도 인사말 문장 안에 넣는다.
    """
    # f-string의 중괄호 안에서 이름을 정리한 결과를 문장에 삽입한다.
    return f"안녕하세요, {name.strip()}님!"


if __name__ == "__main__":
    # python3 demo_greeting.py로 직접 실행한 경우에만 아래 예시를 실행한다.
    # greet는 문자열을 만들고, print가 그 반환값을 터미널에 표시한다.
    print(greet("Codyssey"))
