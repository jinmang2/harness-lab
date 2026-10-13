# ADR-0004: 두 엔진은 같은 DeepSeek 모델과 설정을 쓴다

- 상태: 채택 · 2026-10-13

## 맥락
하네스만 비교하려면 모델, thinking, effort가 같아야 해요.

## 결정
- `LAB_MODEL`, `LAB_THINKING`, `LAB_REASONING_EFFORT` 세 값을 두 엔진이 같이 읽어요. DSH는 `dsh/patches/common.yml`이 이 값을 읽어요.
- 기본 모델은 `deepseek-v4-flash`예요. UI에서 세션마다 바꿀 수 있어요.
- `ChatDeepSeek`을 감싼 `ChatDeepSeekThinking`을 써요.
  - DeepSeek thinking 모드는 도구 호출 턴에 이전 `reasoning_content`를 다시 보내야 해요.
  - DSH 어댑터는 다시 보내는데 `ChatDeepSeek`은 버려요. 그래서 요청을 만들 때 복원해요.
- `LAB_MODEL_SPEC`(예: `openai:gpt-5.4`)을 주면 lab 엔진만 다른 provider로 바꿀 수 있어요. 비교 실험에서는 쓰지 않아요.

## 결과
- 좋은 점: 차이가 생기면 하네스 탓이라고 볼 수 있어요.
- 감수한 점: DeepSeek API 키가 있어야 실제 숫자가 나와요. 키 없이 확인할 때는 mock gateway를 써요(ADR-0005).
