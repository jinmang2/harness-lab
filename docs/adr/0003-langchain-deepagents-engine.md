# ADR-0003: 비교 엔진은 LangChain `create_agent` + deepagents + LangGraph (버전 고정)

- 상태: 채택 · 2026-10-13

## 맥락
DSH 프리셋을 "다른 구현"으로 다시 만들어 보면 하네스의 어느 부분이 결과를 바꾸는지 분리해서 볼 수 있어요. 스터디 README에도 "LangChain / LangGraph와 비교하면 어떨까요?"가 있어요.

## 결정
- 버전을 고정해요: `langchain==1.4.2`, `deepagents==0.6.12`, `langgraph==1.2.12`.
- 하네스 하나 = 빌더 함수 하나(`@harness`). 이렇게 대응시켜요.
  - DSH minimal → `create_agent` + `ShellToolMiddleware`(영속 bash 하나)
  - DSH standard → `create_deep_agent` 기본 스택(todo, 파일, 셸, 서브에이전트, 요약)
  - DSH의 plugin row → LangChain `AgentMiddleware`(before/after/wrap 훅)
- 상태와 재개는 LangGraph 체크포인터(`InMemorySaver`)로, 승인은 `HumanInTheLoopMiddleware`의 interrupt와 `Command(resume=...)`로 해요.

## 고려한 대안
| 대안 | 안 고른 이유 |
|---|---|
| LangGraph `StateGraph`를 직접 짜기 | 루프부터 다시 만들어야 해요. 미들웨어 단위로 하나씩 붙이는 스터디 흐름과 안 맞아요 |
| 직접 만든 최소 루프 | 비교 대상이 하나 더 생겨서 변수가 늘어요 |
| OpenAI Agents SDK, Claude Agent SDK | 모델 제공자에 묶여요. 같은 DeepSeek 모델로 비교하기 어려워요 |

## 결과
- 좋은 점:
  - 미들웨어 훅 모델이 DSH의 plugin 조합과 1:1에 가깝게 대응해요.
  - 의존성이 가벼워요(`uv sync` 약 30초, 85MB).
  - DB나 Redis 없이 메모리만으로 돌아요.
- 감수한 점:
  - deepagents 기본 스택에는 `AnthropicPromptCachingMiddleware`처럼 DeepSeek에서는 아무 일도 안 하는 것도 끼어 있어요. Harnesses 화면에서 그대로 보여줘요.
  - 버전을 올리면 프롬프트와 도구 설명이 바뀌어서 이전 결과와 직접 비교하기 어려워요.

## 다시 볼 조건
- 고정 버전을 올릴 때는 `lab ui`의 Harnesses 탭에서 시스템 프롬프트 길이와 도구 수를 기록해 두고 비교해요.
