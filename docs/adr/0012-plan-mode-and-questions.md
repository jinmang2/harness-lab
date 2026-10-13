# ADR-0012: plan mode와 `ask_user_question`은 DSH 문구 그대로, LangGraph interrupt로 받는다

- 상태: 채택 · 2026-10-13

## 맥락
- DSH Web에는 plan mode(`/plan`, `exit_plan_mode` → 계획 검토)와 `ask_user_question`(질문 카드)이 있어요. DSH standard 프리셋의 도구 목록에도 두 도구가 들어 있어요.
- lab 화면에는 이 둘이 없었어요. lab standard의 도구 목록도 DSH standard와 달랐어요.
- DSH headless는 한 번 실행하고 끝나서 사람에게 물을 수 없어요. 묻는 순간 "no user-questions answerer accepted the request"로 실패해요.

## 결정
- `lab/middleware/collaboration.py`에 두 도구와 plan 섹션을 둬요. 도구 이름, 스키마, 결과 문구, plan 프롬프트 섹션은 DSH(`interaction/tool-ask-user`, `plan/plan-mode`, `bundle/base` 설정)에서 그대로 가져와요.
- plan mode는 그래프 상태(`plan_mode`)예요. checkpointer가 턴을 넘어 유지해요. 켜져 있는 동안 시스템 프롬프트 끝에 plan 섹션을 붙이고, 도구 목록은 DSH처럼 바꾸지 않아요.
- 사람의 답은 LangGraph `interrupt()`로 받아요. 승인(HITL)과 같은 대기 흐름이라 화면은 질문 카드나 계획 검토 패널로 입력창 자리를 대신해요.
- standard 계열(standard, delegate, hitl, tools-skills, custom)에 넣어요. minimal 계열은 DSH minimal처럼 bash만 둬요.
- 배치 실행(`lab run`)과 DSH 엔진 대화에서는 묻지 않아요. 도구는 DSH headless와 같은 문구로 실패해요. 화면의 Plan 칩과 `/plan`은 lab 엔진의 standard 계열에서만 켜져요.
- 화면은 DSH `ui-user-questions`, `ui-plan`의 컴포넌트를 옮기고 CSS 모듈을 그대로 복사해요. 좁은 화면에서 버튼이 잘리는 것만 `global.css`에서 보완해요.

## 고려한 대안
- **lab 화면에서만 흉내 내기(도구 없이 프런트엔드 버튼으로 plan 전환):** 모델이 보는 요청이 DSH와 달라져서 비교 의미가 없어요.
- **도구 목록을 plan mode일 때만 바꾸기:** DSH는 캐시 안정성 때문에 목록을 고정해요. 같은 조건을 유지했어요.

## 결과
- 좋은 점: lab standard의 도구 목록이 DSH standard에 더 가까워졌어요. plan mode와 질문 흐름을 화면에서 직접 실험할 수 있어요.
- 감수한 점: lab standard 요청에 도구 두 개가 늘어서 입력 토큰이 조금 늘어요. 2026-10-13 week1 배치(`runs/20261013-104832-week1`)의 lab 엔진 수치는 이 변경 전 값이에요. DSH 엔진 수치는 영향이 없어요.

## 다시 볼 조건
- DSH가 두 도구의 스키마나 plan 섹션 문구를 바꾸면 따라 고쳐요.
- DSH headless에 질문 응답 채널이 생기면 DSH 엔진 대화에도 연결해요.
