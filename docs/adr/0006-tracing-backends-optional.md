# ADR-0006: LangSmith / Langfuse는 선택 사항, 기본은 로컬 파일 trace

- 상태: 채택 · 2026-10-13

## 맥락
- LangChain 쪽에는 LangSmith(호스팅)와 Langfuse(오픈소스, self-host 가능)라는 span 트레이서가 있어요.
- DSH에는 이런 트레이서가 따로 없어요. 대신 **세션 로그 자체가 완전한 trace**예요. DSH 규칙상 모델이 본 것은 전부 로그에서 재구성할 수 있어야 해요.
- DSH의 OTel 텔레메트리(`session-telemetry-otel`)는 tracing이 아니에요. 기본값 `FEEDBACK_ONLY`로, 사용자가 피드백을 보낼 때 세션 기록을 DeepSeek 서버로 올리는 기능이에요.

## 결정
- 기본 trace는 `runs/<batch>/<run>/trace.jsonl`(로컬 파일)이고, `lab ui`의 Runs와 Trajectory 화면이 이걸 읽어요.
- LangSmith와 Langfuse는 `.env`나 Settings에 키를 넣었을 때만 lab 엔진에 콜백으로 붙여요(`lab/tracing.py`의 `extra_callbacks`). Langfuse는 선택 extra(`uv sync --extra langfuse`)예요.
- DSH는 `DSH_TELEMETRY_MODE=DISABLED`로 OTel 업로드를 꺼요.

## 고려한 대안
| 대안 | 안 고른 이유 |
|---|---|
| Langfuse를 필수로 self-host | docker compose와 Postgres, ClickHouse가 들어가서 "가볍게"라는 목표와 안 맞아요. 그리고 DSH는 Langfuse로 보낼 수 없어서 두 엔진을 같은 화면에서 비교하지 못해요 |
| LangSmith를 기본으로 | 외부 SaaS로 프롬프트와 출력이 나가요. 로컬 실험의 기본값으로는 과해요 |
| OpenTelemetry로 통일 | DSH OTel은 피드백 업로드용이라 span 구조가 달라요. 변환 비용이 커요 |

## 결과
- 좋은 점: 아무것도 띄우지 않아도 두 엔진의 trace가 같은 형식으로 남아요.
- 감수한 점: span 검색, 대시보드 공유 같은 기능은 LangSmith나 Langfuse를 켰을 때만 있어요. 그것도 lab 엔진만 돼요.

## 다시 볼 조건
- 팀이 같은 trace를 함께 봐야 하면 Langfuse self-host를 다시 검토해요. DSH 쪽은 세션 로그를 Langfuse로 보내는 변환기가 필요해요.
