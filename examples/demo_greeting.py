"""커밋·PR 생성 시연에 사용할 간단한 인사말 예제."""


def greet(name: str) -> str:
    """이름 앞뒤 공백을 지우고 같은 형식의 인사말을 만든다."""
    return f"안녕하세요, {name.strip()}님!"


if __name__ == "__main__":
    # 이 파일을 직접 실행하면 예시 이름으로 인사말을 출력한다.
    print(greet("Codyssey"))
