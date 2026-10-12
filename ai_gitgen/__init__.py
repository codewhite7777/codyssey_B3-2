"""Git 변경을 읽어 Gemini로 커밋·PR 초안을 만드는 기능 패키지.

이 파일은 ai_gitgen 폴더를 일반 Python 패키지로 구성하는 시작 파일이다.
직접 정의한 함수나 시작 작업은 없으며, import해도 Git/API를 호출하지 않는다.
읽는 순서는 main.py → cli.main() → 각 기능 모듈이다.

git_changes는 자료 수집, config는 Key·기본값, safety는 전송 자료 정리,
prompts는 작성 규칙·자료 구성, api_client는 통신, formatting은 결과 검사를 맡는다.
여기서 함수를 다시 노출하지 않고 사용하는 모듈에서 필요한 함수를 직접 가져온다.
"""
