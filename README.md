# codyssey B3-2 — AI Git 설명 도우미

Git 변경 사항을 읽어 커밋 메시지와 Pull Request 초안을 만드는 Python 3.10+ CLI 프로젝트입니다. 사용하는 AI는 **Google Gemini**입니다.

## 문서의 역할과 현재 상태

- **README.md:** 설치, API Key 설정, 실행 방법, 출력 예시를 안내하는 과제 필수 문서입니다.
- **[READ.md](READ.md):** 사용자가 요청한 설계 결정, 과제 근거, 단계별 구현·검증 기록입니다.

현재 Git 수집·환경변수 Key 처리·현재 Key 치환·최소 안전 모드에 이어 **Gemini REST 호출과 커밋 초안 생성**을 구현했습니다. `commit`은 요청을 한 번 시도하고 변경 요약과 커밋 제목을 출력합니다. **PR 생성은 다음 단계**이며, `pr`는 입력 준비 후 요청 0회와 다음 단계 안내, 종료 코드 1로 마칩니다. 실제 Key로 인증·생성한 결과와 모의 응답 테스트는 구분합니다.

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
python3 main.py commit --safe-mode --context "README.md에 실행 방법을 추가한 변경"
```

- 프로젝트 루트에서 `git status`와 staged·unstaged의 `git diff`를 읽습니다.
- 변경이 없으면 `변경 사항이 없습니다`를 출력하고 종료합니다. 새 파일만 있으면 `git add` 후 재실행하도록 안내합니다.
- 추적 파일 변경이 있는 `commit`·`pr`에서 Key가 없으면 설정 오류를 출력합니다. Key의 존재 확인과 실제 Gemini 인증은 별개입니다.
- `inspect`는 변경 목록만 확인하며 API를 호출하지 않습니다. 현재 초안 생성은 `commit` 명령으로 실행합니다.
- staged와 unstaged를 함께 요약합니다. 실제 커밋에는 staged 내용만 들어가므로 초안을 적용할 때 대상 변경을 확인합니다.

### `--safe-mode`의 의미

`--safe-mode`는 값 없이 붙이는 옵션이며, 생략하면 파일·줄 제한을 적용하지 않습니다. 지정하면 **Gemini 요청 전에 diff가 있는 추적 파일을 최대 10개, 모든 파일의 staged/unstaged diff 합계를 최대 200줄**로 제한합니다. diff 헤더·문맥·추가·삭제 줄을 모두 셉니다. 일부 변경을 제외하면 터미널에 경고하고 프롬프트에도 일부 diff임을 표시합니다.

과제 7번이 허용하는 **일부 diff 전송(B)**을 선택한 것입니다. 원본 파일과 Git 인덱스는 수정하지 않으며, Gemini 모델의 안전 설정을 바꾸는 옵션도 아닙니다. `commit`·`pr`의 입력 처리에서 옵션을 생략해도 현재 `AI_API_KEY`와 정확히 같은 문자열은 가립니다. 커밋 요청의 변경 이유와 생성된 출력에도 같은 치환을 적용합니다.

전송 범위를 줄이는 기능이며 모든 민감정보를 탐지하지는 않습니다. 실행 전 `git diff`와 `git diff --cached`를 검토해 다른 키나 개인정보가 포함되었는지 확인합니다. 제한된 경우 초안은 선택된 변경만 설명하므로 전체 변경을 대표한다고 가정하지 않습니다.

### 생성 옵션

| 옵션 | 기본값 | 처리 |
| --- | --- | --- |
| `--model` | `gemini-3.1-flash-lite` | 요청 URL의 Gemini 모델 이름 |
| `--temperature` | `1.0` | 0~2 범위, 표현의 변동성을 조절하는 생성 옵션 |
| `--max-tokens` | `4096` | 양의 정수, Gemini의 `maxOutputTokens`에 전달하는 생성 토큰 상한 |
| `--context` | 빈 문자열 | 변경 이유·요구사항을 프롬프트에 추가 |

앞의 세 옵션은 과제 예시의 `-model`, `-temperature`, `-max-tokens` 표기도 받습니다. 파라미터의 의미와 선택 근거는 [READ.md 5절](READ.md#5-cli-옵션과-api-파라미터의-연결)에 있습니다.

```bash
python3 main.py commit --safe-mode --model gemini-3.1-flash-lite --temperature 0.5 --max-tokens 4096
```

### 출력 예시

다음은 **형식 설명용 예시이며 실제 Gemini 생성 결과가 아닙니다.** Git 수집·Key 확인·안전 모드 로그 뒤에 표시됩니다. 별도의 커밋 본문은 생략하고 변경 요약과 제목을 구분합니다.

```text
[INFO] Gemini 요청 설정: model=gemini-3.1-flash-lite, temperature=1.0, max_tokens=4096
[INFO] Gemini API 요청 중...
[DONE] 커밋 메시지 생성 완료
--- Change Summary ---
- README.md에 커밋 생성 실행 방법을 추가했습니다.

--- Commit Message ---
docs: 커밋 생성 실행 방법 추가
----------------------
[INFO] AI가 만든 초안입니다. 변경 내용과 제목을 검토한 뒤 적용해 주세요.
[INFO] Gemini API 호출 횟수: 1회
```

제목은 50자 이내를 권장하도록 요청하고, Python에서 한 줄·최대 72자로 후처리합니다. 제목을 정리했으면 경고를 표시합니다. 비어 있거나 잘못된 JSON 결과는 오류로 종료합니다.

API Key 누락, HTTP 인증·권한·할당량 오류, 연결 실패, 시간 초과, 응답 잘림을 원인과 함께 안내합니다. 자동 재시도는 없으며 요청 실패도 시도 횟수 1회로 표시합니다. 요청 횟수는 인증 성공이나 과금 확정을 의미하지 않습니다.

## 검증

```bash
python3 -m unittest discover -v
```

2026-10-11 UTC, Python 3.12.14에서 **총 48개 테스트를 통과**했습니다. 실제 임시 Git 저장소와 가짜 Key를 사용하고, CLI 실행 함수에서 HTTP 요청을 모의 처리했습니다. 요청 주소·헤더·본문·옵션, 200줄 제한과 현재 Key 치환, 커밋 형식, 요청 횟수와 오류 경로를 확인했습니다. 상세 기록은 [READ.md 7.1절](READ.md#71-3단계-gemini-요청과-커밋-출력의-구현-계약)에 있습니다.

**실제 Gemini 인증·생성 품질과 파라미터에 따른 출력 차이는 아직 검증하지 않았습니다.** 실제 Key가 설정된 같은 터미널에서, 검토한 추적 파일 변경을 대상으로 `python3 main.py commit --safe-mode`를 실행해 확인합니다. 변경이 없는 저장소에서는 API를 호출하지 않습니다.

## 남은 필수 작업

| 단계 | 목표 | 완료 기준 |
| --- | --- | --- |
| 4 | PR 생성 | 요청 1회로 80자 이하 제목, Why/What/How to Test와 각 1개 이상 불릿 출력 |
| 5 | 실제 실행·파라미터 비교·문서 완성 | 실제 commit/pr 결과와 옵션 비교, 필수 출력 예시·평가 항목의 설명·원격 반영 확인 |

과제 7번의 **일부 diff 전송(B)**을 선택했습니다. 일반 비밀값 탐지, 별도 파일 제외 정책, 상한 조절 옵션, dry-run, 팀 컨벤션 등 추가 기능은 이번 범위에서 제외합니다. [범위 검토와 과제 근거](READ.md#0-과제-필수사항에-맞춘-구현-범위)를 확인할 수 있습니다.

각 단계의 목적을 먼저 READ.md에 기록한 뒤 구현 → 검증 → 커밋·PR 머지 순서로 진행하며 다음 단계 코드는 미리 작성하지 않습니다. 이 저장소의 개발 과정에서 하는 GitHub 반영과 별개로, **프로그램 자체는 커밋·push·PR 생성·머지를 실행하지 않습니다.** 생성된 텍스트는 사용자가 검토하고 적용합니다.
