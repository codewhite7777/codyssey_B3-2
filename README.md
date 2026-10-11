# codyssey B3-2 — AI Git 설명 도우미

Git 변경 사항을 읽어 커밋 메시지와 Pull Request 초안을 터미널에 출력하는 Python 3.10+ CLI입니다.

**사용 API는 Google Gemini입니다. [READ.md](READ.md)에서 API 선택과 연동 방법을 먼저 확인해 주세요.** 사용할 모델, API Key 설정, HTTP 요청·응답, 파라미터, 보안·오류 처리 및 검증 기준을 설명합니다.

## 과제 범위

- 프로그램의 Git 호출은 `git status`, `git diff`로 제한합니다.
- AI API Key는 환경변수 `AI_API_KEY`에서만 읽습니다.
- 결과는 사용자가 검토하는 초안이며, 프로그램이 커밋·push·PR 생성·머지를 수행하지 않습니다.
- 개발 과정의 단계별 브랜치·PR·머지는 이 도구 외부에서 수행합니다.

## 단계별 구현 계획

| 단계 | 목표 | 핵심 개념 | 완료 기준 |
| --- | --- | --- | --- |
| 1 | CLI와 Git 변경 수집 | argparse, subprocess, staged/unstaged | 실제 임시 Git 저장소에서 정상·예외 테스트 |
| 2 | 안전 모드 | 마스킹, 파일·줄·크기 제한 | 요청에 전달될 민감정보와 전송 범위 검증 |
| 3 | REST API 연동 | HTTP, JSON, 환경변수, timeout | 로컬 HTTP 서버로 성공·인증·연결 오류 검증 |
| 4 | 커밋 생성 | 프롬프트와 후처리 분리 | 제목 72자 이하, 본문 품질 규칙 검증 |
| 5 | PR 생성 | 템플릿, JSON 검증 | 제목 80자 이하, 세 섹션과 불릿 검증 |
| 6 | 전체 검증·사용 가이드 | 통합 테스트, 평가 근거 | 전체 테스트와 원격 반영 확인 |

각 단계는 구현 → 검증 → 커밋·원격 반영 → PR 머지 순서로 진행합니다.

## 검증 상태

1단계 CLI·Git 수집과 2-1단계 지정 문자열 마스킹 함수를 구현했습니다. CLI에 안전 모드를 연결하는 작업과 AI 생성은 후속 단계입니다.

2026-10-11 검증: 기존 Git 수집·해석 테스트 12개와 마스킹 테스트 4개, **총 16개 테스트를 통과**했습니다. 마스킹 확인에는 가짜 값만 사용했으며 Gemini API 호출은 0회입니다.

```bash
python main.py inspect
python -m unittest discover -v
```

staged/unstaged 변경을 각각 읽으며 새 파일의 본문은 `git add` 후 수집합니다.
Git 수집 중 파일·인덱스를 변경하지 않습니다. 루트 이외의 위치와 미해결 병합 충돌은 안내 후 종료합니다.

## 2-1단계: 지정한 민감 문자열 가리기

`ai_gitgen/safety.py`의 `redact(text, secret)`는 입력 문장에 있는 지정 문자열을 `[REDACTED]`로 바꾸어 반환합니다. 같은 값이 여러 번 나오면 모두 바꾸고, `secret`이 빈 문자열이거나 입력에 없으면 원문을 유지합니다. Git·환경변수·API 접근 없이 문자열 처리만 담당합니다.

실제 API Key를 사용하지 않고 다음 명령으로 확인합니다.

```bash
python -c "from ai_gitgen.safety import redact; print(redact('token=FAKE_KEY_FOR_TEST', 'FAKE_KEY_FOR_TEST'))"
python -m unittest tests.test_safety -v
```

첫 명령의 예상 결과는 `token=[REDACTED]`입니다. 두 번째 명령은 한 번 등장·여러 번 등장·등장하지 않음·빈 `secret`의 네 상황을 확인합니다. 과제 근거와 함수의 책임은 [READ.md의 9.1절](READ.md#91-2-1단계-지정-문자열-마스킹-구현)에 설명합니다.

이 함수는 지정받은 값만 가립니다. 알려지지 않은 키·이메일 등의 패턴 탐지, 전송량 제한, CLI의 `--safe-mode` 연결은 다음 단계에서 구현합니다.
