# harness-lab 설계 노트

All-About-Harness 스터디의 "Same Model / Same Task / Different Harness" 실험을 가볍게 돌리기 위한 설계와, 그 근거가 된 DeepSeek Harness(DSH) 분석을 정리한 문서예요. 측정값은 2026-10-12 ~ 13, macOS arm64, Node 26, `@deepseek-ai/dsh@0.1.5-rc.3`, deepagents 0.6.12 기준이에요.

## 1. 출발점: All-About-Harness 레포

- **정체**: DSH를 뜯어보고 실험하는 스터디 레포예요. 레포에는 `setup.sh`, 주차별 `workspace/`, README만 있고, DSH 소스는 `deepseek-harness/`에 따로 clone돼요(.gitignore 처리).
- **`setup.sh` 흐름**
  1. fork `poqopo/deepseek-harness`에서 tag `dsh-v0.1.5-rc.3`를 clone하고 브랜치 `study/npx-0.1.5-rc.3`를 만들어요.
  2. `upstream` remote를 추가하고, tag의 `apps/cli/package.json` 버전을 검증해요.
  3. pnpm을 확보해요. 순서는 pnpm → corepack → `npx pnpm@11.7.0`이에요.
  4. `pnpm install --frozen-lockfile`
  5. `pnpm run clean`과 `pnpm run build`를 실행해요. build는 `build:native-system` → `build:lib`(host와 client 각각 tsc + tsdown) → `build:web` 순서예요.
  6. `npm run dsh -- web`을 실행하면 `127.0.0.1:3080?token=...`에 떠요.
- **week1 과제**: Minimal mode와 Standard mode를 비교하고, "Minimal이 더 나은 질문 3개"를 찾는 과제예요. 제출 항목은 토큰, 시간, 사용 도구예요.

## 2. DSH의 "모드" = Agent Preset

DSH의 모든 기능은 Cordis 플러그인이고, 프리셋은 플러그인 row 목록 YAML(`packages/preset/agent-presets/presets/*/agent.cordis.yml`)이에요.

| | minimal | standard | ptc | cordis |
|---|---|---|---|---|
| 시스템 프롬프트 | `You are a helpful software engineer assistant.`. `complete: true`라 다른 섹션이 끼어들 수 없음 | persona + AGENTS.md + 런타임 컨텍스트 + 도구 가이드 | standard와 같음 | standard + Cordis 자기수정 지식 |
| 도구 | 영속 bash 하나 | bash, fs, fs 검색, jobs, skill, goal, plan, subagent/fork, workflow, ralph, ask_user, todo, web, present | standard에서 workflow를 빼고, 나머지를 TS SDK로 감싸 `run_code` 하나로 노출 | standard + `cordis_mount` |
| 스킬 | 없음 | 카탈로그 → `skill` 도구로 로드 | 있음 | 있음 |
| 컨텍스트 압축 | 없음 | compaction-basic + tool-result-pruner (8KB 넘으면 head 4KB, tail 1KB만 남김) | 있음 | 있음 |

**week1 결과를 이 표로 읽으면**
- 도구를 하나도 안 쓰는 질문에서도 입력 토큰이 6,939 vs 838이었어요. 이 차이가 standard의 **고정 오버헤드**(도구 스키마 + 가이드 프롬프트)예요.
- 환율 질문: standard는 `web_search`/`web_fetch`를 쓰다 403을 맞고 다시 검색했어요. minimal은 bash `curl` 한 번이었어요. 결과는 같고 총 토큰은 43k vs 8k였어요.
- CSV 질문: standard가 테스트와 검증까지 해서 품질이 높았어요. 대신 78k vs 9k였고, 대부분 cached 입력이었어요.

## 3. 왜 무거운가, 그리고 Web은 하네스인가

**무거운 이유**
1. 레포 기본 경로가 **소스 빌드**예요. 패키지 287개, 네이티브 애드온, 웹 프론트엔드 빌드가 포함돼요.
2. Web은 브라우저 ↔ BFF ↔ Typert RPC ↔ host 구조예요. 그래서 토큰 URL이 필요해요.
3. 프리셋은 agent plane만 바꿔요. 샌드박스, 승인, 영속화, 설정, 자격증명, MCP, webhook, 텔레메트리 같은 host plane은 minimal에서도 다 떠요. "minimal이 가볍다"는 건 모델이 받는 토큰 기준이에요.
4. 부팅할 때 Cordis 플러그인 트리를 조합해요.

**실측**
- `npm i @deepseek-ai/dsh@0.1.5-rc.3`: 81초, 289MB, `@deepseek-ai/*` 241개. 두 번째 설치는 57초.
- headless 부팅: 약 1.3초.
- deepagents 스택(`uv`): 29초, 85~92MB.

**Web은 하네스가 아니에요.** 하네스는 "모델이 무엇을 보고, 무엇을 할 수 있고, 어떤 루프로 도는지 정하는 층"이고, Web은 그 결과를 그리는 surface예요. DSH 스스로도 Web, TUI, headless, ACP를 같은 base 위의 surface로 둬요. 다만 두 가지는 짚어 둬야 해요.
1. **Minimal/Standard 전환은 Web 번들에만 있어요.**
   - `bundle/web-app/cordis.patch.yml`이 base의 agent-plane row를 끄고 세션마다 프리셋을 붙여요.
   - headless는 "composes no preset roster"라 base row를 그대로 써요.
   - 그래서 이 실험장은 minimal을 `dsh/patches/minimal.yml`로 재현했고, 결과적으로 원본 프리셋과 **같은 시스템 프롬프트와 같은 도구**가 나가는 걸 wire로 확인했어요.
2. **"사람에게 묻는 포트"는 하네스 경계에 있어요.** 승인, `ask_user`, plan 리뷰가 여기에 해당해요. headless는 후속 입력이 없어서 이 흐름이 Web과 다를 수 있어요. 실험할 때 변수로 기록해요.

**결론**: 실험은 headless와 patch로 하고, 관찰은 로컬 뷰어로 해요. Web은 궤적을 눈으로 보고 싶을 때만 `npx @deepseek-ai/dsh@0.1.5-rc.3 web`으로 띄워요. 소스를 고쳐야 할 때도 `pnpm run build:native-system && pnpm run build:lib`이면 충분하고, Web 빌드는 건너뛸 수 있어요.

## 4. DSH의 추적과 토큰 기능 (조사 결과)

| 기능 | 패키지 | 내용 | 실험장에서 |
|---|---|---|---|
| 세션 로그 | `session-persistence-jsonl` | 이벤트 소싱 JSONL. 모델 호출마다 `usage`(uncached / cacheRead / cacheWrite / output / reasoning)와 스트림 청크 시각, `tool/call`, `tool/result`, `system/message`, `request/header`(도구 스키마)를 기록해요. 기본은 zstd 압축 | `compression: none`으로 바꿔 직접 파싱해요 → `lab/dsh.py` |
| 토큰 미터 | `token-meter` | 로그를 재생해서 context pressure와 breakdown을 추정하고 Web에 투영해요 | (Web 전용) |
| 세션 통계 | `session-stats` | 턴, 스텝, LLM, 도구, 첫 토큰, decode 시간 | (Web 전용) |
| 세션 검색 | `session-query(-sqlite)` | FTS5 검색과 trace 조회. 모델용 도구도 있어요(opt-in) | 미사용 |
| 로그 내보내기 | `session-log-export` | Web에서 ZIP 다운로드 | 불필요 (파일 직접) |
| OTel 텔레메트리 | `session-telemetry-otel` | **기본 `FEEDBACK_ONLY`**: 피드백을 보낼 때 세션 기록을 `harness-telemetry.deepseeksvc.com`으로 업로드해요. 일반 tracing이 아니라 피드백 공유 기능이에요 | `DSH_TELEMETRY_MODE=DISABLED` |
| 세션 로그 업로드 | `session-log-deepseek` | 공식 API 요청에 세션 로그를 첨부해요. 기본 `enabled: false` | 손대지 않음 (꺼져 있음) |
| Inspector | `experimental/inspector` | Chrome DevTools로 host와 Cordis 트리를 보는 도구. private, 소스에서만 | 미사용 |

**정리**: DSH에는 Langfuse/LangSmith 같은 span 트레이서가 따로 없어요. 대신 **세션 로그 자체가 완전한 trace**예요. "모델이 본 것은 전부 로그에서 재구성할 수 있어야 한다"는 게 DSH의 규칙이에요.

## 5. 실험장 구조

```
lab/
  model.py        같은 모델 팩토리 (DeepSeek thinking 모드, reasoning_content 왕복)
  harnesses/      하네스 = 프리셋. @harness 등록
  middleware/     주제별로 직접 만든 미들웨어
  tracing.py      LangChain callback → 공통 trace
  dsh.py          DSH headless 실행 + 세션 로그 → 공통 trace
  gateway.py      127.0.0.1 OpenAI 호환 게이트웨이 (mock / proxy), 요청 녹화
  runner.py       태스크 × 하네스 × 엔진 × N
  report.py       week 표 형식 report.md
  evaluate.py     도구 범주, 선택 정확도, 복구, LLM-judge
  anatomy.py      하네스 해부: probe 모델로 조립해서 미들웨어, 훅, 도구, 첫 요청 추출
  settings.py     쓰기 전용 키와 모델 설정 (.env)
  week1.py        week1 과제 result.md 생성
  viewer/         127.0.0.1 서버 (stdlib http.server): play.py 세션, jobs.py 실행, workspaces.py,
                  gateway_control.py, static/ (ui 빌드 결과)
ui/               React 18 + CSS Modules. DSH Web 구조 (src/dsh/ = DSH에서 가져온 토큰·아이콘·CSS, MIT)
docs/adr/         설계 결정 기록
dsh/patches/      DSH 하네스 = headless + overlay YAML
skills/           tools-skills 하네스가 쓰는 스킬
tasks/            week1.yaml (+ fixtures)
```

**localhost를 "내 쪽에서만" 띄우는 건 괜찮은가?** 괜찮고, 이 구조가 그 답이에요.
- DSH Web이 무거운 이유는 에이전트를 **실행하고 제어하는** 컨트롤 플레인이라서예요. 셸 권한이 있으니 토큰 인증과 RPC가 필요해요.
- 실험장의 뷰어는 파일을 **읽기만** 해요. 게이트웨이는 키를 들고 있지 않고, 요청 헤더를 그대로 넘기기만 해요.
- 둘 다 `127.0.0.1`에만 바인딩해요. 뷰어는 Host 헤더를 검사해서 DNS rebinding도 막아요.
- 주의: `0.0.0.0`으로 바꿔서 외부에 노출하지 마세요.

**공정 비교를 위한 장치**
- 모델: `LAB_MODEL`, `LAB_THINKING`, `LAB_REASONING_EFFORT` 하나로 두 엔진에 같이 적용해요(DSH는 `common.yml` patch).
- DeepSeek thinking 모드는 도구 호출 턴에 이전 `reasoning_content`를 다시 보내야 해요. DSH 어댑터는 이걸 하는데 `ChatDeepSeek`은 버려요. 그래서 `ChatDeepSeekThinking`에서 복원해요.
- 토큰은 겹치지 않는 형태로 정규화해요(`uncached + cached = 입력`). week1 표에는 두 의미가 섞여 있었어요.
- wire(게이트웨이)는 엔진과 무관한 하나의 측정 기준이에요. DSH의 숨은 제목 생성 호출도 여기서 보여요.

## 6. DSH 개념 ↔ LangChain / deepagents 대응

| DSH | LangChain / deepagents |
|---|---|
| preset (`agent.cordis.yml`) | `HarnessProfile` (`base_system_prompt`, `excluded_tools`, `excluded_middleware`, `extra_middleware`) 또는 `create_deep_agent` 인자 |
| minimal: persona `complete` + persistent-bash | `create_agent(system_prompt=…, middleware=[ShellToolMiddleware(...)])` |
| Cordis plugin + lifecycle | `AgentMiddleware` 훅: `before_agent`, `before_model`, `wrap_model_call`, `after_model`, `wrap_tool_call`, `after_agent` |
| tool-fs, fs-search, bash | `FilesystemMiddleware` + `LocalShellBackend` (`ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute`) |
| tool-todo | `TodoListMiddleware` (`write_todos`) |
| subagent / fork | `SubAgentMiddleware` (`task`), `AsyncSubAgentMiddleware` |
| compaction-basic | `SummarizationMiddleware` |
| tool-result-pruner | `ContextEditingMiddleware`, 직접 만든 `ToolResultPruner` |
| tool-skill | `SkillsMiddleware` (`skills=`), 또는 list/load 도구 |
| plan mode, approval, ask_user | `interrupt_on`, `HumanInTheLoopMiddleware`, `CollaborationMiddleware`(`interrupt()`) |
| guard / repeat-tool-reminder | 직접 만든 `RepeatToolCallGuard`, `ToolCallLimitMiddleware` |
| llm-retry | `ModelRetryMiddleware`, `ModelFallbackMiddleware` |
| ptc (`run_code`) | 직접 대응 없음 (실험 소재) |
| 세션 로그 | callback trace / LangSmith / Langfuse |

## 7. 스터디 범위 대비 상태

| 스터디 항목 | 실험장 | 위치 |
|---|---|---|
| Agent ↔ Harness, Agent Loop | ✅ | `minimal` vs `standard`, `hooks` |
| Model Adapter | ✅ 부분 | `lab/model.py` (DeepSeek thinking 왕복), `LAB_MODEL_SPEC`으로 다른 provider |
| Tool System, Skill & Preset | ✅ | `prompt-only`, `tools`, `tools-skills`, `custom`, `skills/` |
| Context & Session | ✅ | `ctx-*` 하네스 + `tasks/context.yaml` |
| Permission & Guard | ✅ | `hitl` (일괄 정책, Playground 승인), `custom` 가드 |
| Planning | ✅ | todo(`write_todos`)와 DSH plan mode(`exit_plan_mode`, plan 섹션)가 lab standard 계열에 있어요. headless DSH는 계획 검토를 받을 수 없어서 대화 화면에서만 비교해요 |
| Cordis (Plugin, Service, Event) | 코드 읽기 | DSH 소스. 이 문서의 대응표(6절) |
| 평가 지표 7개 | ✅ | README "평가 지표" |
| GUI | ✅ | `lab ui`: DSH Web과 같은 구조와 디자인(React, DSH 토큰). 세션, Chat/Trajectory, 승인, Stop, todo, context 링, 통계, Files, Settings 4섹션 + Runs, New run, Harnesses. `lab view`는 읽기 전용 |
| week1 과제 | ✅ (실행은 키 필요) | `tasks/week1-assignment.yaml`, `lab week1` |
| API 키, 모델 설정 | ✅ | Settings 탭 (쓰기 전용 `.env`, 연결 확인, 모델 목록) |

## 8. 진행안 (스터디 Phase 1~3)

| 단계 | 질문 | 하네스와 도구 | 볼 것 |
|---|---|---|---|
| 1. 베이스라인 오버헤드 | 도구를 안 써도 드는 고정비는 얼마인가? | `minimal` vs `standard`, 양 엔진, `meeting-summary` | report의 "첫 요청 입력", wire body의 시스템 프롬프트와 도구 |
| 2. 미들웨어 해부 | 훅은 어떤 순서로 돌고, 어디에 무엇을 끼워야 하나? | `hooks`, `lab/middleware/`, `lab ui` Harnesses 탭 | Harnesses 탭의 스택·훅 순서·실제 프롬프트, trace의 `hook` 이벤트 (before는 순서대로, after는 역순, wrap은 양파 구조) |
| 3. 컨텍스트 관리 | 긴 작업에서 요약, 편집, 자르기 중 무엇이 나은가? | `minimal`, `ctx-prune`, `ctx-edit`, `ctx-summarize` × `tasks/context.yaml` | check 통과율, 토큰, cached 비율, judge |
| 4. 스킬 노출 | 스킬은 언제 도움이 되고 언제 비용만 늘리나? | `standard` vs `tools-skills` (`skills/live-data`, `csv-analysis`) | 날씨/환율에서 도구 호출 수, 첫 요청 크기 |
| 5. 프로필 = 프리셋 | 프리셋 4종(A~D)으로 README 실험 재현 | `prompt-only`, `tools`, `tools-skills`, `custom` | 전 태스크 report |
| 6. 위임과 HITL | 서브에이전트와 승인은 비용과 품질에 어떻게 작용하나? | `standard`, `delegate`, `hitl` × `tasks/delegation.yaml`. `LAB_HITL=reject` 비교. `lab ui` Chat에서 직접 승인 | 서브에이전트 trace, 승인 수, 거절 시 행동 |

각 단계마다 `lab run ... -n 3 -l <단계명>`으로 반복 실행해서 편차를 같이 봐요.
