# harness-lab

> 같은 모델, 다른 하네스. 하네스 구성만 바꿔 가며 에이전트 동작과 비용을 비교하는 가벼운 실험장.

All-About-Harness 스터디용 실험장이에요. DeepSeek Harness(DSH)의 프리셋을 LangChain/deepagents로 다시 만들고, 두 엔진을 **같은 모델, 같은 태스크, 같은 측정 기준**으로 나란히 돌려요.

- **빌드 없음**: Python은 `uv sync` 한 번이면 돼요(약 30초, 90MB). DSH는 소스 빌드 없이 npm 패키지를 받아요(약 1분).
- **무거운 Web 없음**: 에이전트는 DSH headless와 Python으로 돌아요. 화면은 `127.0.0.1`에 뜨는 HTML 파일 하나(`lab ui`)예요. 빌드도 Node 서버도 없어요.
  - `lab ui`: Chat, Runs, New run, Harnesses, Settings
  - `lab view`: 같은 화면의 읽기 전용판 (Runs, Harnesses)
- **키 없이 검증 가능**: mock 게이트웨이로 전체 파이프라인을 돌려 볼 수 있어요.

설계와 배경은 [docs/DESIGN.md](docs/DESIGN.md)에 있어요.

## Quick start

```bash
uv sync
cp .env.example .env              # DEEPSEEK_API_KEY 채우기

uv run lab list                    # 하네스 / 태스크 목록
uv run lab run -H minimal,standard # week1 태스크 전부, lab 엔진
uv run lab ui                      # http://127.0.0.1:8765  (키는 Settings → Models에서 넣어도 돼요)
```

DSH도 같이 비교하려면 이렇게 해요.

```bash
uv run lab dsh-install                         # @deepseek-ai/dsh@0.1.5-rc.3 → .dsh-runtime/
uv run lab run -e lab,dsh -H minimal,standard
```

키 없이 배선만 확인하려면 이렇게 해요.

```bash
uv run lab gateway --mode mock &                       # 127.0.0.1:8790
DEEPSEEK_API_KEY=dummy DEEPSEEK_BASE_URL=http://127.0.0.1:8790 \
  uv run lab run -e lab,dsh -H minimal,standard -t readme-structure -l mock
uv run pytest            # 테스트 결과는 임시 폴더에. LAB_TEST_DSH=1 이면 DSH까지
```

## 명령

| 명령 | 하는 일 |
|---|---|
| `lab list` | 등록된 하네스와 태스크 |
| `lab run -H <h,..> [-e lab,dsh] [-T tasks.yaml] [-t <task>] [-n N] [-l label] [--judge]` | 태스크 × 하네스 × 엔진 × N회 실행, `runs/<batch>/`에 기록 |
| `lab judge runs/<batch> [--force]` | 태스크 rubric으로 LLM-judge 채점 (Output Quality) |
| `lab ui` (= `lab play`) | 로컬 화면. 아래 "화면" 참고 |
| `lab gateway --mode mock\|proxy` | 로컬 모델 게이트웨이. 두 엔진의 요청을 똑같이 녹화 |
| `lab view` | 같은 화면, 읽기 전용 (대화, 실행, 설정 없음) |
| `lab week1 runs/<batch> --id <GitHub-ID>` | week1 과제 제출용 `result.md` |
| `lab week2 <batch>... --id <GitHub-ID>` | week2 RALPH 비교 (Round별 기록, 수락 테스트, 루프 끝 시점 채점, 차분 테스트, workspace 밖 접근 감사) |
| `lab report runs/<batch>` | `report.md` 다시 만들기 |
| `lab dsh-install` | 고정 버전 DSH를 npm으로 설치 (빌드 없음) |

## 화면 (`lab ui`)

DSH Web과 같은 구조와 디자인이에요. React 18 + CSS Modules에 DSH의 디자인 토큰, 아이콘, 컴포넌트 CSS를 MIT 고지와 함께 가져와서(`ui/src/dsh/`) 같은 DOM 구조로 다시 만들었어요(ADR-0010). DeepSeek 로고는 쓰지 않아요.

| 자리 | DSH Web | 여기 |
|---|---|---|
| 왼쪽 사이드바 | New Session, Workspaces(폴더별 세션 목록, 검색, 추가), Settings | 같음. 패널 자리에 실험용 **Runs / New run / Harnesses**가 있어요. 지난 `lab ui`의 세션은 읽기 전용으로 다시 열려요 |
| 새 세션 화면 | 워크스페이스 칩, 프리셋(mode) 칩, 입력창(권한, 모델과 effort) | 같음. 프리셋 메뉴에 DSH 프리셋(headless)과 lab 하네스가 함께 있어요. 권한은 Auto approve / Ask first |
| 세션 헤더 | 제목, 프리셋 라벨, 더 보기, 오른쪽 사이드바 토글, **Chat / Trajectory** 탭 | 같음 |
| Chat | System prompt 행, 사용자 말풍선, "N tool calls" 접힘, Think 행, Bash 터미널 카드, Edit diff, Inspect, 답변(markdown), Usage / Ran for 팝업 | 같음 |
| 입력창 | 권한, 모델·effort, context 링, 보내기/멈춤, 아래 "turns · steps · tok/s"와 "tok · Cache hit" | 같음. 승인 대기 중에는 **Reject / Allow once** 패널로 바뀌고, todo가 있으면 위에 todo 패널이 붙어요 |
| Trajectory | 툴바, Input/Model/Tools 타임라인, 기록 표와 상세 창 | 같음 |
| 오른쪽 사이드바 | Files 트리와 미리보기 탭 | 같음 |
| Settings | General(권한 기본값, 테마, 글자 크기, 대화 표시, Enter 동작), Models(키 쓰기 전용, 모델 목록), Plugins, Agent presets | 같음. Models에 LangSmith/Langfuse 키, Plugins에 gateway(mock/proxy), DSH 런타임, batch 승인 정책 |

여기에만 있는 것: **Runs**(batch 비교표, run별 Trajectory, wire body, 파일, LLM-judge 버튼), **New run**(`lab run`을 화면에서), **Harnesses**(API 호출 없이 하네스를 조립해서 미들웨어 스택, 훅 순서, 도구 스키마, 실제 시스템 프롬프트, 서브에이전트를 보여줘요).

plan mode(`/plan`, Plan 칩, 계획 검토), `ask_user_question` 질문 카드, goal(`/goal`, goal 바, 자동 이어 하기)은 lab 엔진의 standard 계열 세션에서 써요. 실행 중 보낸 메시지의 대기열과 steer(Cmd/Ctrl+Enter), 대화 fork(Branch into a new conversation), 파일·이미지 첨부, 대화 중 모델·effort 변경은 lab 엔진 세션 전체에서 돼요([ADR-0012](docs/adr/0012-plan-mode-and-questions.md), [ADR-0013](docs/adr/0013-session-features-like-dsh.md)). 이미지는 이미지 입력을 지원하는 모델(`deepseek-flash`, `deepseek-v4-flash-vision-exp`)에서만 보낼 수 있어요. **DSH 엔진 대화는 메시지마다 새 headless 작업이에요.** headless에는 이어서 대화하는 기능이 없어서, 작업 폴더의 파일만 이어지고 대화 기록은 이어지지 않아요.

UI를 고칠 때만 Node가 필요해요. 빌드 결과(`lab/viewer/static/`)는 레포에 들어 있어서 `lab ui`만 쓸 때는 필요 없어요.

```bash
cd ui && npm install && npm run build   # → lab/viewer/static/
npm run dev                             # 개발 서버 :5173, API는 실행 중인 lab ui(:8765)로 프록시
```

## Week 1 과제

스터디 week1 과제("Standard보다 Minimal이 더 잘 답하는 질문 3개")를 그대로 돌리는 태스크 파일과 정리 명령이 있어요(ADR-0011).

```bash
uv run lab run -T tasks/week1-assignment.yaml -e dsh,lab -H minimal,standard -n 3 -l week1 --judge
uv run lab week1 runs/<batch> --id <GitHub-ID>     # → runs/<batch>/week1-result.md (제출 형식)
```

- 실험 질문("오늘 서울 날씨는 어땠어?")과 후보 질문 7개를 돌려요. 후보마다 정답 정규식(`expect`)이나 채점 기준(`rubric`)이 붙어 있어요.
- 제출 숫자는 DSH 엔진 기준이에요. lab 엔진 결과는 참고 표로 붙어요. 숫자는 반복 실행의 중앙값이에요.
- **실행 시간은 에이전트 턴 시간**(DSH Web의 "Ran for")이에요. DSH headless 프로세스는 부팅과 종료에 몇 초가 더 걸리는데(`minimal`의 영속 터미널이 닫히는 데 약 6초), 이건 에이전트 시간이 아니라서 따로 "프로세스 포함" 열에 둬요.
- "Minimal이 더 좋은 이유"는 측정값으로 초안을 쓰니, 실제 답변을 보고 고쳐서 `workspace/week1/<GitHub-ID>/result.md`로 제출해요. 키, credential, 세션 로그는 넣지 않아요.

## Week 2 과제

스터디 week2 과제("Build Your Own RALPH")용이에요(ADR-0014, 0015, 0016). DSH 0.2.0-rc.2 런타임을 따로 써요.

```bash
uv run lab dsh-install --version 0.2.0-rc.2
uv run lab dsh-web-setup          # .dsh-home-0.2.0-rc.2-web/: Web profile + dsh/bundles/verified-ralph 링크 (pnpm 필요)
uv run lab run -T tasks/week2.yaml -t durations-backlog -t sizes-backlog -e dsh-web -H ralph-official,ralph-custom -n 5
uv run lab run -T tasks/week2.yaml -t durations-backlog-goal -t sizes-backlog-goal -e dsh-web -H goal -n 5
uv run lab run -T tasks/week2.yaml -t versions-backlog -e dsh-web -H ralph-official,ralph-custom,ralph-custom-tests -n 5
uv run lab run -T tasks/week2.yaml -t durations-backlog -t sizes-backlog -e dsh-web -H ralph-custom-tests -n 5
uv run lab run -T tasks/week2.yaml -t durations-backlog -t sizes-backlog -e dsh-web -H ralph-custom-tests-v2 -n 5   # 종료 = 검증 통과 + worker 완료
LAB_RECURSION_LIMIT=1000 uv run lab run -T tasks/week2.yaml -t durations-backlog -t sizes-backlog -e lab \
    -H ralph-fresh,ralph-verified,ralph-judge,ralph-check,ralph-reset -n 3
LAB_RECURSION_LIMIT=1000 uv run lab run -T tasks/week2.yaml -t durations-backlog-goal -t sizes-backlog-goal -e lab -H goal -n 3
uv run lab week2 runs/<batch>... --id <GitHub-ID>
```

- **`dsh-web` 엔진**: 실행마다 DSH Web host를 따로 띄우고, 브라우저가 쓰는 RPC(`/api/<namespace>/<method>`)로 조작해요. headless는 첫 idle에서 끝나서 goal Round가 돌지 않고, preset을 조립하지도 않기 때문이에요. 세 DSH 방식이 모두 Web standard preset을 바탕으로 해요.
  - 공식 Ralph: `lab-ralph-official` preset. standard에서 `tool-ralph` 행만 켠 거예요.
  - Custom: Creator가 만든 `verified-ralph` preset
  - goal: standard + `goal-5.yml`
- `dsh/bundles/verified-ralph/`는 DSH Web Creator Mode가 쓴 Plugin 번들이에요. headless로 재현할 때는 `dsh/patches/ralph-custom.yml`을 써요(`dsh` 엔진).
- **검증 명령**: 하나로 고정돼 있어요(`tasks/checks/week2_verify.py`). SPEC 제목을 보고 durations, sizes, versions 수락 테스트를 돌려요.
- **채점과 감사**:
  - 채점은 workspace 밖의 수락 테스트로 해요.
  - week2 태스크는 `isolate: true`라서, workspace가 목록을 볼 수 없는 임시 디렉터리에 만들어져요.
  - `lab week2`는 다음을 정리해요: Round별 기록, 거짓 완료 보고(그대로 끝났는지 포함), workspace 밖 접근 감사.
  - "성공률 너머" 표도 만들어요: 부모 모델이 루프 뒤에 고친 것을 되돌린 **루프 끝 시점 점수**, 정답 코드와 무작위 입력으로 비교하는 **차분 테스트**(`tasks/checks/week2_fuzz.py`), 검증이 worker의 `continue`를 덮고 끝낸 실행, 부모 세션 토큰 몫.
  - 채점할 수락 테스트는 태스크 id로 골라요(worker가 SPEC.md를 고쳐도 채점이 바뀌지 않아요).
  - workspace 밖 접근 중 채점 자료(`tasks/`, `tests/`, `runs/`, 다른 실행의 workspace)에 닿은 실행만 오염으로 세서 중앙값에서 빼요. 나머지는 기록만 해요.
  - 루프가 실패한 뒤 모델이 루프 도구를 다시 부르면, Round는 합으로 세고 종료 사유는 마지막 호출 기준으로 봐요.

## 하네스

| 이름 | 엔진 | 구성 |
|---|---|---|
| `minimal` | lab, dsh | 한 줄 프롬프트 + 영속 bash 하나. DSH `minimal` 프리셋과 같은 프롬프트, 같은 도구 설명 |
| `standard` | lab, dsh | lab: deepagents 기본 스택 + `fetch_url` / dsh: headless 기본 구성 (도구 25개) |
| `prompt-only` | lab | A: 프롬프트만, 도구 없음 |
| `tools` | lab | B: minimal 프롬프트 + bash + `fetch_url` |
| `tools-skills` | lab | C: standard + `skills/` (deepagents SkillsMiddleware) |
| `custom` | lab | D: standard + 직접 만든 가드 미들웨어 + 호출 제한 + 재시도 |
| `hooks` | lab | minimal + HookLogger. 미들웨어 훅 실행 순서 관찰용 |
| `ctx-prune` / `ctx-edit` / `ctx-summarize` | lab | 3단계: minimal + 결과 자르기 / 오래된 도구 결과 지우기 / 모델 요약. 컨텍스트 전략만 다름 |
| `delegate` | lab | 6단계: standard + researcher/coder 서브에이전트 |
| `hitl` | lab | 6단계: standard + `execute`/`write_file`/`edit_file` 전 승인. 일괄 실행은 `LAB_HITL=approve\|reject`, Playground는 버튼 |
| `ralph-official` / `ralph-custom` / `ralph-custom-tests` / `ralph-custom-tests-v2` | dsh, dsh-web | week2 (`-tests`는 dsh-web만, 검증 = workspace 테스트, `-v2`는 검증 통과 + worker `complete`일 때만 종료): 공식 `tool-ralph` / Creator Mode로 만든 `verified_ralph` (DSH 0.2.0-rc.2) |
| `ralph-custom-tests-v3` / `ralph-custom-tests-v3-low` | dsh-web | week2 파일럿: v2 + worker 도구 6개로 제한 + `focused` 지시 / 여기에 worker 추론 `low`. 각 2회만 재서 결론은 없어요(ADR-0015) |
| `ralph-fresh` / `ralph-verified` / `goal` | lab | week2 DSH 재현: 공식 `tool-ralph` / Custom `verified_ralph` / DSH goal(같은 대화, `<goal_round>`) |
| `ralph-judge` / `ralph-check` / `ralph-reset` | lab | week2 우리 설계: 같은 대화 + judge / 같은 대화 + 검증 명령 / 대화 초기화 + handoff |

## 태스크

| 파일 | 태스크 | 용도 |
|---|---|---|
| `tasks/week1.yaml` | weather, meeting-summary, exchange-rate, order-analysis, readme-structure | week1 과제와 기본 비교 |
| `tasks/context.yaml` | log-stats (정답 자동 검증), log-incident-report | 3단계: 1,200줄 로그 4개로 컨텍스트 압박 |
| `tasks/delegation.yaml` | usd-orders, readme-structure | 6단계: 조사 + 코딩이 섞인 작업 |
| `tasks/week1-assignment.yaml` | seoul-weather + 후보 7개 | week1 과제 (Minimal이 더 잘 답하는 질문 찾기) |
| `tasks/week2.yaml` | durations, durations-backlog(-goal), sizes-backlog(-goal), versions-backlog | week2 과제 (반복 실행 비교, 수락 테스트 13개 / versions 17개) |

태스크 필드:
- `prompt`
- `fixture`: 작업 폴더에 복사할 디렉터리
- `check`: 끝난 뒤 작업 폴더에서 실행할 셸 명령. 종료 코드 0이면 통과. `{tasks}`는 tasks 디렉터리 절대경로로 치환돼요
- `tools: {allowed: [범주], required: bool}`
- `rubric: [기준]`
- `expect`: 최종 답변이 맞아야 하는 정규식. `check`가 없으면 이게 성공 판정이에요
- `isolate`: `true`면 작업 폴더를 `runs/` 아래가 아니라 새 임시 디렉터리에 만들고, 끝나면 `runs/<batch>/<run>/workspace`로 옮겨요

정답이 필요한 검증용 파일은 `tasks/expected/`에 둬요. 작업 폴더 밖이지만 **읽기까지 막히지는 않아요.** 에이전트가 cwd 상위로 올라가면 레포와 다른 run이 보여요(week2 파일럿에서 실제로 일어났어요). 정답이 새면 안 되는 태스크는 `isolate: true`를 켜고, `lab week2`처럼 workspace 밖 접근을 같이 봐요.

## 평가 지표 (스터디 README의 7개)

| 지표 | 어떻게 |
|---|---|
| Task Success Rate | 실행 성공 + `check` 통과 |
| Tool Selection Accuracy | 도구를 범주(shell, web, read, write, plan, delegate, skill)로 묶어 태스크의 `tools.allowed`와 비교. plan류는 중립이에요. 필요한 도구를 안 썼는지(`required`), 범주 밖 도구도 표시 |
| Number of Tool Calls | 횟수, 종류, 순서 |
| Token Usage | uncached, cached, output, reasoning. 첫 요청 고정비 |
| Latency | 전체, 모델 호출별, TTFT, 도구별 |
| Failure / Recovery | 도구 에러 수와, 에러가 있었는데도 성공과 check 통과로 끝났는지 |
| Output Quality | `lab judge` 또는 `--judge`: 태스크 rubric으로 1~5점. 모델 호출이 추가로 들어요. 채점 모델은 `LAB_JUDGE_MODEL_SPEC`, 없으면 실험 모델 |

새 하네스는 `lab/harnesses/` 아무 모듈에 `@harness("name", "설명")`를 붙인 빌더 함수를 추가하면 돼요. DSH 쪽은 `dsh/patches/`의 overlay YAML과 `lab/dsh.py`의 `HARNESSES`에 등록해요.

## 측정: 무엇을 어디서 보나

| 소스 | 어디서 | 무엇 |
|---|---|---|
| **lab trace** | LangChain callback (`lab/tracing.py`) | 모델 호출별 토큰, 지연, TTFT, 도구 호출, 서브에이전트 포함 |
| **DSH trace** | DSH 세션 로그 (`.dsh-home/sessions/**.jsonl`) → `lab/dsh.py` | 같은 형식으로 변환. 토큰은 provider 보고값 |
| **wire** | `lab gateway` (`runs/gateway/`) | 엔진과 무관하게 실제 HTTP 요청과 provider usage. 요청 body 전체를 저장해서 시스템 프롬프트와 도구 스키마를 그대로 볼 수 있어요 |
| LangSmith / Langfuse | 선택 | lab 엔진만. `.env`에 키를 넣으면 붙어요 |

토큰은 겹치지 않게 나눠요: `input_uncached + cache_read (+ cache_write) = 청구된 입력`. LangChain은 cache를 포함한 총합을, DSH는 uncached만 보고하므로 둘 다 이 형태로 바꿔요.

## 결과물

```
runs/<batch>/
  summary.jsonl, report.md
  <task>__<engine>-<harness>__<n>/
    trace.jsonl   wire.jsonl   final.md   workspace/
    dsh-session.jsonl   stderr.txt          # dsh only
runs/gateway/calls.jsonl, bodies/<id>.json   # gateway
```

`report.md`는 week1 제출 표 형식(성공 여부, 사용 Tool, 호출 횟수, 실행 순서, 토큰, 시간)이라 그대로 옮겨 쓸 수 있어요.

## 알아 둘 점

- **`-e dsh`의 standard는 Web의 standard 프리셋과 완전히 같지 않아요.** headless에는 프리셋 로스터가 없어서 base 구성의 도구 row를 그대로 써요. 대부분 겹치지만 예를 들어 `present`는 없고 `read_image`는 있어요.
- **DSH는 세션 제목용 LLM 호출을 따로 해요.** 이 호출은 세션 로그에는 없고 wire에만 보여요. 비용을 비교할 때는 wire 합계를 함께 보세요.
- **DSH 세션 로그에는 스트림 청크 도착 시각만 있어요.** 그래서 trace의 DSH 모델 지연은 "스트림 길이"이고, 도구 시간은 상한값이에요. 정확한 요청 지연은 wire를 보세요.
- **headless는 사용자에게 되묻지 못해요.** 승인이나 `ask_user`를 쓰는 흐름은 Web과 다르게 동작할 수 있어요.
- **mock 결과는 배선 확인용이에요.** mock 토큰은 문자 수 ÷ 4로 근사한 값이에요. 메시지에 `[mock:ask]`, `[mock:plan]`, `[mock:slow]`(2초 걸리는 명령, steer 확인용), `[mock:goal]`을 넣으면 mock이 해당 도구를 불러서 키 없이 화면을 확인할 수 있어요. goal 라운드에서는 mock이 goal을 읽고 complete로 표시해요.
- **HITL에서 거절된 호출은 실행되지 않으므로 도구 호출 수에 들어가지 않아요.** 승인 요청 수는 `hitl` 열에 따로 나와요.
- **`lab ui`는 에이전트를 실행하고 `.env`를 고쳐요.** 127.0.0.1 바인딩, Host 검사, `X-Lab` 헤더 요구로 다른 웹페이지가 조종하지 못하게 막았어요. 그래도 외부에 노출하지 마세요. 키 값은 서버에서 브라우저로 절대 보내지 않아요.
- **화면에서 켠 gateway는 `lab ui`가 떠 있는 동안만 유효해요.** `.env`는 바꾸지 않아요. Chat 세션의 wire는 시간 구간으로 잘라서, 같은 시각에 돌던 다른 실행의 호출이 섞일 수 있어요.
- **Stop은 다음 모델 토큰이나 도구 호출 직전에 멈춰요.** 이미 돌고 있는 셸 명령은 끝날 때까지 기다려요. 실행되지 못한 도구 호출에는 "사용자가 멈춤" 결과를 채워서 다음 메시지를 바로 보낼 수 있어요.
- **에이전트 셸에는 이름에 KEY, TOKEN, SECRET, PASSWORD가 들어간 환경변수를 넘기지 않아요.** DSH가 자식 프로세스에 쓰는 규칙과 같아요. 단, 샌드박스가 아니라서 에이전트가 `.env` 파일을 직접 읽는 것까지 막지는 못해요.
- **실험 에이전트는 로컬 셸을 그대로 써요.** 각 run의 `workspace/`가 cwd이지만 샌드박스는 아니에요.
- DSH는 `DSH_HOME=.dsh-home`으로 격리해서 `~/.dsh`를 건드리지 않아요. 피드백 연동 OTel 업로드는 `DSH_TELEMETRY_MODE=DISABLED`로 꺼요.
