# ADR-0008: 평가 지표 7개 구현 방식

- 상태: 채택 · 2026-10-13

## 맥락
스터디 README의 평가 지표는 7개예요: Task Success Rate, Tool Selection Accuracy, Number of Tool Calls, Token Usage, Latency, Failure/Recovery, Output Quality. 엔진마다 도구 이름이 달라요(`bash`와 `execute`, `fetch_url`과 `web_fetch`).

## 결정
- **성공**: 실행 성공에 태스크의 `check` 셸 명령이 통과해야 해요. 정답 파일은 `tasks/expected/`에 둬서 에이전트가 볼 수 없게 해요.
- **도구 선택 정확도**: 도구를 범주(shell, web, read, write, plan, delegate, skill)로 묶어요. 그다음 태스크의 `tools.allowed`와 비교해요. plan류는 중립으로 둬요.
- **복구**: 도구 에러가 있었는데도 성공과 check 통과로 끝났는지 봐요.
- **출력 품질**: 태스크의 `rubric`으로 LLM이 1~5점을 매겨요(`lab judge`). 채점 모델은 `LAB_JUDGE_MODEL_SPEC`이고, 없으면 실험 모델을 써요.

## 결과
- 좋은 점: 엔진이 달라도 같은 기준으로 비교해요.
- 감수한 점:
  - judge는 모델 호출이 추가로 들고, 채점 모델의 편향을 그대로 받아요.
  - 사람이 판단한 "Minimal이 더 좋다"(week1 과제)는 judge 점수와 따로 적어요.
