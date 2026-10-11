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

2단계는 2-1 지정 문자열 마스킹 → 2-2 환경변수·누락 오류 처리 → 2-3 현재 Key와 Git 수집 결과 마스킹 연결 → 일반 패턴·제외·전송량 제한 순서로 나누어 진행합니다.

## 검증 상태

1단계 CLI·Git 수집, 2-1단계 지정 문자열 마스킹, 2-2단계 환경변수 API Key 읽기·누락 오류 처리, 2-3단계 현재 Key의 Git 수집 결과 마스킹 연결을 구현했습니다. 일반 패턴 탐지·전송량 제한과 AI 생성은 후속 단계입니다.

2026-10-12 검증: Git 수집·해석 12개, 문자열·변경 정보 마스킹 8개, 설정 함수 3개, 실제 CLI 실행 6개, **총 29개 테스트를 통과**했습니다. 가짜 Key로 staged·unstaged 전체와 파일명 마스킹을 확인했고, 원본 객체·실제 파일·Git 인덱스가 유지되는 것도 검증했습니다. CLI 테스트의 실제 제공자 키는 제거하고 가짜 값만 사용했으며 Gemini API 호출은 0회입니다.

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
python -m unittest tests.test_safety.RedactTests -v
```

첫 명령의 예상 결과는 `token=[REDACTED]`입니다. 두 번째 명령은 한 번 등장·여러 번 등장·등장하지 않음·빈 `secret`의 네 상황을 확인합니다. 과제 근거와 함수의 책임은 [READ.md의 9.1절](READ.md#91-2-1단계-지정-문자열-마스킹-구현)에 설명합니다.

이 함수는 지정받은 값만 가립니다. 알려지지 않은 키·이메일 등의 패턴 탐지, 전송량 제한, CLI의 `--safe-mode` 연결은 다음 단계에서 구현합니다.

## 2-2단계: 환경변수에서 API Key 읽기

`ai_gitgen/config.py`의 `load_api_key()`는 실행 환경의 `AI_API_KEY`만 읽고 앞뒤 공백을 제거한 값을 반환합니다. 미설정·빈 문자열·공백뿐인 값은 설정 안내와 함께 오류로 처리합니다. 함수는 키를 출력하거나 저장하지 않습니다. 터미널 설정 방법은 [READ.md의 3.3절](READ.md#33-현재-터미널에-api-key-설정), 구현 근거와 검증 기준은 [3.7절](READ.md#37-2-2단계-python에서-api-key-읽기)에 정리했습니다.

추적 중인 파일에 변경이 있는 프로젝트 루트에서 실행합니다.

```bash
python main.py commit
python main.py pr
```

키가 없으면 표준 오류에 다음 안내를 출력하고 종료 코드 `1`로 마칩니다.

```text
[ERROR] AI_API_KEY 환경변수가 설정되지 않았습니다. READ.md의 3.3절에 따라 같은 터미널에서 설정해 주세요.
```

키가 있으면 값 대신 설정 확인·현재 Key 마스킹 적용 안내와 API 호출 횟수 `0회`가 표시됩니다. 이어서 **Gemini API 호출·초안 생성은 아직 구현되지 않았다는 안내와 종료 코드 `1`**로 마칩니다. 이는 인증 실패가 아니라 현재 구현 단계의 범위를 나타냅니다.

`inspect`, 변경 없음, 추적되지 않은 새 파일만 있는 경우에는 키 없이도 기존 안내 후 정상 종료합니다. 따라서 키 누락 동작을 확인하려면 추적 중인 파일의 변경이 필요합니다.

실제 키를 바꾸지 않고 가짜 값과 임시 Git 저장소로 이번 단계를 검증합니다.

```bash
python -m unittest tests.test_config tests.test_cli -v
```

## 2-3단계: 현재 API Key를 Git 변경 정보에서 가리기

`redact_changes(changes, secret)`는 staged·unstaged diff 전체와 현재·이전 파일명, 브랜치에서 지정 문자열을 가린 새 데이터를 반환합니다. 삭제한 줄과 주변 문맥도 포함합니다. 원본 수집 객체·실제 파일·Git 인덱스·환경변수·인증에 사용할 Key는 변경하지 않습니다.

추적 파일 변경이 있는 `commit`·`pr`는 `load_api_key()`로 읽은 값을 이 함수에 전달합니다. Git 수집이 끝난 뒤 마스킹하고, 그 결과로 파일 목록을 출력합니다. 따라서 이 경로의 파일명에 현재 Key가 들어 있더라도 먼저 원문이 출력되지 않습니다. 과제 근거와 필드별 처리·검증 기준은 [READ.md의 9.2절](READ.md#92-2-3단계-현재-api-key를-git-수집-결과에서-가리기)에 정리했습니다.

키가 있고 추적 파일 변경이 있을 때 Git 수집 로그 다음에 표시되는 안내입니다.

```text
[INFO] AI_API_KEY 환경변수 설정을 확인했습니다.
[INFO] 현재 API Key 마스킹 적용 완료: diff·파일명·브랜치
[INFO] Gemini API 호출 횟수: 0회
[ERROR] Gemini API 호출과 초안 생성은 아직 구현되지 않았습니다. 현재 단계는 API Key 마스킹 연결까지입니다.
```

CLI는 아직 diff 본문을 출력하지 않습니다. 안내 문구만 확인하는 대신 가짜 Key를 넣은 반환 데이터와 실제 CLI 출력을 테스트로 검증합니다. 실제 Key를 파일에 넣을 필요가 없습니다.

```bash
python -m unittest tests.test_safety tests.test_cli -v
```

이번 보호 범위는 추적 파일 변경이 있는 `commit`·`pr`에서 현재 Key와 정확히 일치하는 문자열입니다. `inspect`·변경 없음·새 파일만 존재하는 경로는 기존 동작을 유지합니다. 일반 키·이메일 패턴 탐지, 민감 파일 제외, 전송량 제한, `--safe-mode`·`--dry-run` 및 Gemini 호출은 후속 작업입니다.
