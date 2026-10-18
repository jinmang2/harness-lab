# ADR (Architecture Decision Records)

이 실험장에서 내린 결정과 그 이유를 적어 둬요. 나중에 "왜 이렇게 했지?"가 생기면 여기부터 봐요.

- 한 결정에 파일 하나. 번호는 바꾸지 않아요.
- 결정을 뒤집을 때는 새 ADR을 쓰고, 옛 ADR의 상태를 `대체됨 (→ ADR-xxxx)`로 바꿔요.
- 형식: 상태 · 날짜 · 맥락 · 결정 · 고려한 대안 · 결과(좋은 점, 감수한 점) · 다시 볼 조건

| 번호 | 제목 | 상태 |
|---|---|---|
| [0001](0001-record-decisions.md) | 결정은 ADR로 남긴다 | 채택 |
| [0002](0002-dsh-headless-not-web.md) | DSH는 Web 대신 headless를 npm 고정 버전으로 돌린다 | 채택 |
| [0003](0003-langchain-deepagents-engine.md) | 비교 엔진은 LangChain `create_agent` + deepagents + LangGraph (버전 고정) | 채택 |
| [0004](0004-same-model-deepseek.md) | 두 엔진은 같은 DeepSeek 모델과 설정을 쓴다 | 채택 |
| [0005](0005-measurement-three-sources.md) | 측정은 lab trace, DSH 세션 로그, gateway wire 세 갈래로 한다 | 채택 |
| [0006](0006-tracing-backends-optional.md) | LangSmith / Langfuse는 선택 사항, 기본은 로컬 파일 trace | 채택 |
| [0007](0007-local-only-ui-security.md) | UI는 127.0.0.1 전용, Host 검사와 `X-Lab` 헤더로 보호 | 채택 |
| [0008](0008-evaluation-metrics.md) | 평가 지표 7개 구현 방식 (도구 범주, rubric judge) | 채택 |
| [0009](0009-secrets-write-only.md) | 비밀값은 쓰기 전용, 에이전트 셸에서는 뺀다 | 채택 |
| [0010](0010-ui-react-dsh-design.md) | UI는 DSH Web과 같은 React 18 + CSS Modules, DSH 디자인 토큰을 쓴다 | 채택 |
| [0011](0011-week1-assignment-pipeline.md) | week1 과제는 태스크 파일과 제출용 결과 생성기로 돌린다 | 채택 |
| [0012](0012-plan-mode-and-questions.md) | plan mode와 `ask_user_question`은 DSH 문구 그대로, LangGraph interrupt로 받는다 | 채택 |
| [0013](0013-session-features-like-dsh.md) | goal, steer/대기열, fork, 첨부, 대화 중 모델 변경도 DSH 동작을 그대로 따른다 | 채택 |
| [0014](0014-dsh-0-2-runtime-for-week2.md) | week2 하네스는 DSH 0.2.0-rc.2 런타임을 따로 두고 돌린다 | 채택 |
| [0015](0015-lab-ralph-mechanisms.md) | 반복 실행은 Context × 끝내는 쪽으로 나눠, DSH 방식 재현과 우리 설계를 같은 작업으로 잰다 | 채택 |
| [0016](0016-dsh-web-engine.md) | Preset과 goal은 DSH Web host를 API로 돌려서 잰다 (`dsh-web` 엔진) | 채택 |
