# codyssey B3-2 — AI Git 설명 도우미

Git 변경 사항을 **Google Gemini**로 요약해 커밋 메시지와 PR 설명 초안을 터미널에 출력하는 Python 프로그램입니다. 생성된 글을 검토한 뒤 복사해 사용합니다. 프로그램이 직접 커밋·push·PR 생성·머지를 하지는 않습니다.

**[바로 실행하기](#4-처음-실행하기) · [실행 오류 해결](#7-실행-중-막혔을-때)**

| 문서 | 읽는 목적 |
| --- | --- |
| **README.md — 이 문서** | 설치·실행 방법과 핵심 코드 이해 |
| **[DESIGN.md](DESIGN.md) — 상세 기록** | API 선택 이유, 설계 근거, 단계별 구현·검증 기록 확인 |

## 1. 전체 흐름

**Git 변경 수집 → Key 확인·안전 처리 → Gemini 요청 → 형식 검사 → 터미널 출력**

Python은 자료 수집과 형식 검사를, Gemini는 설명 문장 작성을 담당합니다. 변경이 없으면 API 호출 없이 종료하고, 문제가 생기면 원인을 출력합니다.

## 2. 핵심 함수가 하는 일

실행은 [main.py](main.py)에서 시작하며, [cli.py의 main()](ai_gitgen/cli.py)이 전체 순서를 연결합니다.

| 함수 | 역할 |
| --- | --- |
| [main()](ai_gitgen/cli.py) | 명령과 옵션을 읽고 아래 함수들을 순서대로 실행 |
| [collect_changes()](ai_gitgen/git_changes.py) | Git status·diff로 변경 파일과 내용을 수집 |
| [load_api_key()](ai_gitgen/config.py) | 환경변수 AI_API_KEY를 읽고, 없으면 오류 처리 |
| [redact_changes()](ai_gitgen/safety.py) | 수집한 자료에서 현재 API Key 문자열을 가림 |
| [limit_changes()](ai_gitgen/safety.py) | --safe-mode 사용 시 최대 10개 파일·전체 200줄로 diff 제한 |
| [build_change_prompt()](ai_gitgen/prompts.py) | 파일명·diff·변경 이유를 Gemini에 보낼 자료로 정리 |
| [generate_text()](ai_gitgen/api_client.py) | Gemini API를 한 번 호출하고 생성된 글을 받아옴 |
| [format_commit() / format_pr()](ai_gitgen/formatting.py) | 결과를 검사하고 제목 길이·섹션·불릿을 맞춰 출력문 생성 |

## 3. commit과 pr의 차이

앞부분의 처리 흐름은 같고, Gemini에 주는 작성 규칙과 마지막 출력 형식이 다릅니다.

| 명령 | 출력 |
| --- | --- |
| `commit` | 변경 요약 + 커밋 제목 — 최대 72자, 50자 이내 권장 |
| `pr` | 변경 요약 + PR 제목 — 최대 80자 + Why / What / How to Test 본문 |

PR 본문의 **문장은 Gemini가 작성**하고, **섹션 제목과 불릿은 Python이 붙입니다.** 두 명령 모두 현재의 staged·unstaged 변경을 함께 요약합니다.

## 4. 처음 실행하기

아래는 **macOS 터미널 기준**입니다. Git과 Python 3.10 이상이 필요하며, 이 프로젝트를 위한 추가 Python 패키지는 없습니다.

```bash
git --version
python3 --version
```

두 명령에서 버전이 표시되고 **Python이 3.10 이상이면 4-1로 진행**합니다. 준비되지 않았다면 다음과 같이 설치합니다.

- **Git이 없으면:** `xcode-select --install`을 실행하고 나타나는 설치 창을 따라 완료합니다. [Git 공식 macOS 설치 안내](https://git-scm.com/install/mac)
- **Python이 없거나 3.10 미만이면:** [Python 공식 macOS 다운로드](https://www.python.org/downloads/macos/)에서 안정 버전의 `macOS installer`를 받아 `.pkg` 파일을 실행합니다.
- **python.org 설치 프로그램을 사용했다면:** 응용 프로그램의 `Python 3.x` 폴더에서 `Install Certificates.command`를 더블클릭해 인증서 설치까지 마칩니다. `3.x`는 설치한 버전이며, HTTPS API 연결에 필요한 Python 설치 과정입니다. [Python 공식 설치 완료 안내](https://docs.python.org/3/using/mac.html#installation-steps)

설치 후 터미널을 새로 열고 위의 두 버전 확인 명령을 다시 실행합니다.

### 4-1. 프로젝트 다운로드

처음 사용하는 경우에만 실행합니다.

```bash
git clone https://github.com/codewhite7777/codyssey_B3-2.git
cd codyssey_B3-2
```

이미 클론했다면 기존 `codyssey_B3-2` 폴더로 이동합니다. 이후 명령은 모두 **`main.py`가 있는 프로젝트 루트에서, 같은 터미널로** 실행합니다.

### 4-2. API Key 입력

아직 Key가 없다면 [Google AI Studio API Key 페이지](https://aistudio.google.com/apikey)에 Google 계정으로 로그인해 **Gemini API Key**를 발급받습니다. 이미 발급했다면 그 Key를 사용합니다. Key가 준비되면 아래 명령만 먼저 실행하세요.

```bash
read -r -s AI_API_KEY
```

입력을 기다리는 상태에서 **자신의 Key를 붙여넣고 Enter를 누릅니다.** 입력한 글자가 화면에 보이지 않는 것이 정상입니다. 이때 다른 명령을 함께 붙여넣지 마세요.

Key 입력을 마친 뒤 아래 두 줄을 실행합니다. `export`는 이 터미널에서 실행할 Python이 Key를 읽을 수 있게 합니다.

```bash
printf '\n'
export AI_API_KEY
```

### 4-3. 설정 확인

```bash
python3 -c "import os; print('설정됨' if os.environ.get('AI_API_KEY', '').strip() else '미설정')"
```

**`설정됨`이 나오면 다음 단계로 진행합니다.** 이 명령은 Key 값을 출력하거나 API를 호출하지 않습니다. 환경변수에 값이 있는지만 확인하며, 실제 인증은 초안을 생성할 때 확인합니다.

Key는 **현재 터미널의 환경변수 `AI_API_KEY`**로 관리합니다. 프로그램은 `.env` 파일을 자동으로 읽지 않습니다. 새 터미널을 열면 4-2부터 다시 설정하고, 실제 Key를 코드나 문서에 적어 Git에 올리지 마세요. 환경변수 방식은 과제의 Key 관리 요구사항에 따른 결정입니다. 발급 방법·Windows 설정·선택 근거는 [상세 Key 설정과 선택 근거](DESIGN.md#3-api-key-준비와-설정)에 있습니다.

### 4-4. 설명할 변경 사항 준비

**클론 직후에는 변경 사항이 없는 것이 정상입니다.** AI가 설명할 내용을 만들려면 Git이 이미 관리하는 파일을 수정하고 저장하세요. 새 파일을 만들었다면 해당 파일을 `git add 파일명`으로 추가해야 내용까지 수집됩니다.

실행 전 `git diff`와 `git diff --cached`로 변경 내용을 확인합니다. 전자는 아직 `git add`하지 않은 수정, 후자는 `git add`한 수정을 보여 줍니다. 다른 API Key나 개인정보가 들어 있지 않은지도 확인하세요.

두 생성 명령은 이 두 종류의 변경을 함께 요약합니다. 이미 커밋한 브랜치 전체의 변경을 비교하지는 않습니다. 실제 커밋에는 `git add`한 내용만 들어가므로 초안을 적용할 때 대상 변경을 확인합니다.

### 4-5. 커밋 메시지 또는 PR 초안 생성

커밋 메시지가 필요하면 다음을 실행합니다.

```bash
python3 main.py commit
```

PR 제목과 본문이 필요하면 다음을 실행합니다.

```bash
python3 main.py pr
```

**옵션을 붙이지 않아도 기본 설정으로 실행됩니다.** 변경이 없으면 `변경 사항이 없습니다`를 출력하고 API 호출 없이 종료합니다.

## 5. 필요한 경우에만 옵션 추가

### 전송할 diff 양 줄이기: `--safe-mode`

```bash
python3 main.py commit --safe-mode
```

`pr`에도 같은 옵션을 붙일 수 있습니다. Gemini에 보낼 diff를 **최대 10개 파일·전체 합계 200줄**로 제한하며, 헤더·문맥 줄도 포함합니다. 제한을 넘으면 일부 변경만 사용했다는 경고를 출력합니다. 옵션을 생략하면 이 제한은 적용하지 않습니다.

현재 `AI_API_KEY`의 값과 정확히 같은 문자열은 기본으로 가리지만, **다른 Key나 개인정보를 모두 자동 탐지하지는 않습니다.** 안전 모드를 사용해도 4-4의 내용 검토가 필요합니다. 일부 diff로 만든 초안은 전체 변경을 설명하지 못할 수 있습니다.

### 모델·표현·출력량 변경

| 옵션 | 기본값 | 바꾸는 내용 |
| --- | --- | --- |
| `--model` | `gemini-3.1-flash-lite` | 사용할 Gemini 모델 |
| `--temperature` | `1.0` | 표현의 변동성, 0~2 범위 |
| `--max-tokens` | `4096` | 생성 토큰 수 상한, 양의 정수 |
| `--context` | 빈 문자열 | 변경 이유·요구사항을 추가로 전달 |

변경할 값만 입력합니다. 예를 들어 temperature만 바꾸려면 다음과 같습니다.

```bash
python3 main.py pr --temperature 0.5
```

API를 호출하지 않고 변경 목록만 확인하려면 `python3 main.py inspect`, 전체 옵션을 보려면 `python3 main.py --help`를 실행합니다. 각 생성 명령은 API 요청을 최대 1회 시도하며 자동 재시도하지 않습니다. `commit`과 `pr`를 모두 실행하면 최대 2회 요청합니다.

## 6. 출력 예시

아래는 사용자 Mac에서 실제 Gemini로 생성한 결과의 발췌입니다. 당시 입력은 README.md에 테스트 문장을 추가한 변경입니다. 실행 조건과 파라미터 비교는 [실제 실행·파라미터 비교 기록](DESIGN.md#113-실제-gemini-실행과-파라미터-비교-결과)에 기록했습니다.

### 커밋 메시지

```text
[DONE] 커밋 메시지 생성 완료
--- Change Summary ---
- README.md 파일에 테스트용 문구 추가

--- Commit Message ---
docs: README.md 테스트용 문구 추가
----------------------
```

### PR 제목과 본문

```text
[DONE] PR 초안 생성 완료
--- Change Summary ---
- README.md 파일 내 테스트용 문구 추가

--- PR Title ---
README.md에 테스트용 변경 사항 추가

--- PR Body ---
## Why
- README.md 파일의 변경 사항을 확인하기 위한 테스트 용도입니다.

## What
- README.md 파일 하단에 '테스트용 변경입니다.'라는 문구를 추가하였습니다.

## How to Test
- README.md 파일을 열어 추가된 문구가 정상적으로 표시되는지 확인합니다.
----------------------
```

커밋 제목은 50자 이내를 권장하도록 요청하고 최대 72자로, PR 제목은 최대 80자로 후처리합니다. PR 본문은 `Why`·`What`·`How to Test`와 각 섹션의 불릿으로 구성합니다. **변경 배경과 테스트 방법은 사용자가 검토해야 합니다.** AI가 제안한 테스트 방법은 실제 테스트 통과 기록이 아닙니다.

## 7. 실행 중 막혔을 때

| 화면에 나온 내용 | 확인할 사항 |
| --- | --- |
| `변경 사항이 없습니다` | 정상 종료입니다. 설명할 파일을 수정한 뒤 다시 실행합니다. API 요청은 0회입니다. |
| `추적되지 않은 새 파일만 있습니다` | 새 파일을 `git add 파일명`으로 추가한 뒤 실행합니다. |
| `AI_API_KEY 환경변수가 설정되지 않았습니다` | 현재 터미널에서 4-2와 4-3을 다시 진행합니다. |
| 프로젝트 루트에서 실행하라는 안내 | `main.py`와 `.git`이 있는 프로젝트 폴더로 이동합니다. |
| HTTP 503과 일시 과부하 안내 | 잠시 후 직접 다시 실행합니다. 재실행은 별도 요청입니다. |
| 그 밖의 API 오류 | 함께 출력된 원인을 확인합니다. 상세 기준은 [상세 오류 안내](DESIGN.md#8-오류-처리-계약)에 있습니다. |

**기존 프로젝트를 업데이트하려면:** 먼저 `git status --short`를 실행합니다. 아무것도 출력되지 않을 때 `git pull --ff-only origin main`으로 업데이트합니다. 파일 목록이 나오면 로컬 변경을 먼저 확인·보존한 뒤 업데이트하세요. 로컬 변경 때문에 pull이 중단되면 작업 폴더에 새 코드가 반영된 상태가 아니므로, 업데이트가 완료됐는지 확인해야 합니다.

## 8. 테스트

자동 테스트는 프로젝트 루트에서 실행합니다.

```bash
python3 -m unittest discover -v
```

기존 검증에서 **자동 테스트 53개가 통과**했습니다. 단위 테스트와 실제 임시 Git 저장소를 이용한 통합 테스트를 포함하며, HTTP 요청은 모의 응답으로 검증합니다. 실제 Gemini 실행 결과는 사용자 Mac에서 확인한 별도 기록입니다. [자동 테스트 기록](DESIGN.md#101-코드-읽기-개선-함수-설명과-처리-순서-주석)과 [실제 API 실행 기록](DESIGN.md#113-실제-gemini-실행과-파라미터-비교-결과)을 확인할 수 있습니다.

각 파일과 함수에는 한국어 설명이 있습니다. 상세한 [파일별 역할](DESIGN.md#10-구현-파일의-책임)과 [테스트 코드](tests/)를 확인할 수 있습니다.
