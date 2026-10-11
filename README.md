# codyssey B3-2 — AI Git 설명 도우미

Git 변경 사항을 읽어 커밋 메시지와 Pull Request 초안을 만드는 Python 3.10+ CLI 프로젝트입니다. 사용하는 AI는 **Google Gemini**입니다.

## 문서의 역할과 현재 상태

- **README.md:** 설치, API Key 설정, 실행 방법, 출력 예시를 안내하는 과제 필수 문서입니다.
- **[READ.md](READ.md):** 사용자가 요청한 설계 결정, 과제 근거, 단계별 구현·검증 기록입니다.

현재 Git 수집·환경변수 Key 처리·현재 Key 치환을 구현했고, 이번 단계에서 `--safe-mode`의 고정 파일·줄 제한을 연결했습니다. **Gemini 호출과 커밋/PR 초안 생성은 다음 단계입니다.** 현재 `commit`·`pr`는 입력 준비 후 요청 횟수 0회와 미구현 안내, 종료 코드 1로 마칩니다.

## 설치와 API Key 설정

Git과 Python 3.10 이상이 필요합니다. 별도 Python 패키지를 설치하지 않습니다.

```bash
git clone https://github.com/codewhite7777/codyssey_B3-2.git
cd codyssey_B3-2
```

이미 클론했다면 기존 프로젝트 루트에서 실행합니다. macOS의 bash/zsh에서는 같은 터미널에서 아래를 **한 줄씩** 실행합니다. `read`가 입력을 기다리면 자신의 Gemini Key를 붙여넣고 Enter를 누른 뒤 나머지 줄을 실행합니다.

```bash
printf 'Gemini API Key를 입력하세요: '
read -r -s AI_API_KEY
printf '\n'
export AI_API_KEY
```

프로그램은 환경변수 `AI_API_KEY`만 읽습니다. `.env`를 자동으로 읽지 않으며, 새 터미널에서는 다시 설정합니다. 실제 Key는 Git에 저장하거나 화면에 출력하지 않습니다. 다른 터미널의 설정과 선택 근거는 [READ.md 3절](READ.md#3-api-key-준비와-설정)에 있습니다.

## 현재 실행 방법

macOS 예시입니다. Python 명령 이름이 `python`인 환경에서는 `python3`를 `python`으로 바꿉니다.

```bash
python3 main.py inspect
python3 main.py commit --safe-mode
python3 main.py pr --safe-mode
```

- 프로젝트 루트에서 `git status`와 staged·unstaged의 `git diff`를 읽습니다.
- 변경이 없으면 `변경 사항이 없습니다`를 출력하고 종료합니다. 새 파일만 있으면 `git add` 후 재실행하도록 안내합니다.
- 추적 파일 변경이 있는 `commit`·`pr`에서 Key가 없으면 설정 오류를 출력합니다. Key의 존재 확인과 실제 Gemini 인증은 별개입니다.
- `--safe-mode`는 `commit`·`pr`의 입력을 **최대 10개 파일·모든 파일의 staged/unstaged 합계 200줄**로 제한합니다. diff 헤더·문맥·추가·삭제 줄을 모두 셉니다.
- 옵션을 생략해도 현재 Key와 정확히 같은 문자열은 가립니다. 원본 파일과 Git 인덱스는 수정하지 않습니다.

다음은 **초안 생성 전, 200줄 제한이 적용된 현재 단계의 출력 예시**입니다. Git 수집 로그 뒤에 표시되며 실제 AI 응답이 아닙니다.

```text
[INFO] AI_API_KEY 환경변수 설정을 확인했습니다.
[INFO] 현재 API Key 마스킹 적용 완료: diff·파일명·브랜치
[INFO] 안전 모드 적용: 1개 파일, 200줄 (최대 10개 파일·200줄)
[WARN] 전송 제한으로 일부 변경만 AI 입력에 포함합니다.
[INFO] Gemini API 호출 횟수: 0회
[ERROR] Gemini API 호출과 초안 생성은 아직 구현되지 않았습니다. 현재 단계는 최소 안전 모드까지입니다.
```

안전 모드는 전송 범위를 줄이며 모든 민감정보를 탐지하지는 않습니다. 실행 전 `git diff`와 `git diff --cached`를 검토해 다른 키나 개인정보가 포함되었는지 확인합니다. 제한이 발생한 경우 이후 생성할 초안은 선택된 변경만 설명하므로 전체 변경을 대표한다고 가정하지 않습니다.

## 검증

```bash
python3 -m unittest discover -v
```

2026-10-12, Python 3.12에서 **총 33개 테스트를 통과**했습니다. 기존 29개에 파일·줄 제한 함수 3개와 실제 CLI 1개를 추가했습니다. 테스트는 가짜 Key와 임시 Git 저장소를 사용하며 실제 Gemini API를 호출하지 않습니다. 상세 범위는 [READ.md 9.3절](READ.md#93-2-4단계-옵션으로-diff-전송-범위-제한)에 있습니다.

## 남은 필수 작업

| 단계 | 목표 | 완료 기준 |
| --- | --- | --- |
| 3 | Gemini REST 연동·커밋 생성 | 모델·temperature·max-tokens 옵션, 요청·응답·오류 처리, 요청 1회로 변경 요약·72자 이하 커밋 제목 출력 |
| 4 | PR 생성 | 요청 1회로 80자 이하 제목, Why/What/How to Test와 각 1개 이상 불릿 출력 |
| 5 | 실제 실행·파라미터 비교·문서 완성 | 실제 commit/pr 결과와 옵션 비교, 필수 출력 예시·평가 항목의 설명·원격 반영 확인 |

과제 7번의 **일부 diff 전송(B)**을 선택했습니다. 일반 비밀값 탐지, 별도 파일 제외 정책, 상한 조절 옵션, dry-run, 팀 컨벤션 등 추가 기능은 이번 범위에서 제외합니다. [범위 검토와 과제 근거](READ.md#0-과제-필수사항에-맞춘-구현-범위)를 확인할 수 있습니다.

각 단계의 목적을 먼저 READ.md에 기록한 뒤 구현 → 검증 → 커밋·PR 머지 순서로 진행하며 다음 단계 코드는 미리 작성하지 않습니다. 이 저장소의 개발 과정에서 하는 GitHub 반영과 별개로, **프로그램 자체는 커밋·push·PR 생성·머지를 실행하지 않습니다.** 생성된 텍스트는 사용자가 검토하고 적용합니다.
