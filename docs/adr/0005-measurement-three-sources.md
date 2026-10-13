# ADR-0005: 측정은 lab trace, DSH 세션 로그, gateway wire 세 갈래로 한다

- 상태: 채택 · 2026-10-13

## 맥락
두 엔진이 사용량을 보고하는 방식이 달라요.
- LangChain의 `input_tokens`는 캐시를 포함한 총합이에요.
- DSH의 `inputTokens`는 캐시를 뺀 값이에요.

엔진이 스스로 남기지 않는 호출도 있어요. DSH의 세션 제목 생성 호출이 그 예예요.

## 결정
| 소스 | 무엇 | 위치 |
|---|---|---|
| lab trace | LangChain 콜백으로 모델 호출, 도구, 훅, 승인을 기록 | `lab/tracing.py` |
| DSH 세션 로그 | v3 JSONL을 `compression: none`으로 남기고 같은 형식으로 변환 | `lab/dsh.py` |
| gateway wire | 127.0.0.1 OpenAI 호환 게이트웨이가 두 엔진의 실제 HTTP 요청과 usage를 녹화. mock 모드는 키 없이 가짜 응답 | `lab/gateway.py` |

- 토큰은 겹치지 않게 나눠요: `input_uncached + cache_read (+ cache_write) = 청구된 입력`, 그리고 `output`, `reasoning`.
- 시간은 둘로 나눠요(2026-10-13 추가).
  - `turn_ms`: 에이전트 턴 시간. DSH는 세션 로그의 첫 `turn/start`부터 마지막 `turn/end`까지(DSH Web의 "Ran for")이고, lab은 실행 시간과 같아요.
  - `wall_ms`: 프로세스 포함 시간.
  - mock에서 DSH `minimal`의 `wall_ms`는 약 7초였지만 턴은 0.3초였어요. 영속 터미널을 닫는 데 시간이 들기 때문이에요. 비교와 과제에는 `turn_ms`를 써요.

## 결과
- 좋은 점:
  - 엔진과 무관하게 같은 기준으로 비교할 수 있어요.
  - 실제로 나간 시스템 프롬프트와 도구 스키마를 그대로 볼 수 있어요.
- 감수한 점:
  - DSH 로그에는 스트림 청크 시각만 있어요. 그래서 DSH 모델 지연은 "스트림 길이"이고, 도구 시간은 상한값이에요.
  - wire는 시간 구간으로 잘라서, 같은 시각에 돌던 다른 실행의 호출이 섞일 수 있어요.
