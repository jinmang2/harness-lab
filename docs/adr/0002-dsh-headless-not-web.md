# ADR-0002: DSH는 Web 대신 headless를 npm 고정 버전으로 돌린다

- 상태: 채택 · 2026-10-13

## 맥락
- 스터디 레포의 기본 경로는 DSH를 소스에서 빌드하고 Web으로 쓰는 방식이에요. 패키지 287개, 네이티브 애드온, 프론트엔드 빌드가 들어가서 무거워요.
- 하네스는 "모델이 무엇을 보고, 무엇을 할 수 있고, 어떤 루프로 도는가"를 정하는 층이에요. Web은 그 결과를 그리는 surface예요. DSH 스스로도 Web, headless, SDK, ACP를 같은 base 위의 surface로 둬요.
- 다만 프리셋 로스터(minimal/standard/ptc/creator)는 Web 번들에만 있어요. headless는 base 구성을 그대로 써요.

## 결정
- `@deepseek-ai/dsh@0.1.5-rc.3`를 npm으로 받아 `.dsh-runtime/`에 둬요. 빌드 없이 81초, 289MB예요.
- 실험은 `dsh --profile headless`로 돌려요. 하네스 차이는 `--patch` overlay YAML(`dsh/patches/`)로 만들어요.
  - `minimal.yml`은 Web의 minimal 프리셋과 같은 시스템 프롬프트와 도구가 나가도록 맞췄고, wire로 확인했어요.
- `DSH_HOME=.dsh-home`으로 격리하고, `DSH_TELEMETRY_MODE=DISABLED`로 피드백 업로드를 꺼요.

## 고려한 대안
| 대안 | 안 고른 이유 |
|---|---|
| 소스 빌드 + Web | 무겁고, Web은 하네스가 아니에요 |
| npm 패키지의 Web (`dsh web`) | 빌드는 없지만 비교 실험을 자동화하기 어려워요(토큰 URL, RPC). 화면 참고용으로만 띄워요 |
| SDK 프로필 (JSON-RPC) | 세션 재개가 되지만 프로토콜 구현 비용이 커요. 다시 볼 조건 참고 |

## 결과
- 좋은 점: 설치가 가볍고, 같은 태스크를 스크립트로 반복할 수 있어요.
- 감수한 점:
  - headless는 대화를 이어가지 못해요. UI에서 DSH 세션은 메시지마다 새 작업이에요.
  - headless는 승인이나 `ask_user`에 사람이 답하지 못해서 Web과 다르게 동작할 수 있어요.
  - standard는 Web 프리셋과 도구가 조금 달라요(`present` 없음, `read_image` 있음).

## 다시 볼 조건
- DSH 엔진으로 여러 턴 대화나 승인을 비교해야 하면 SDK 프로필(`dsh --profile sdk`)을 붙여요.
- DSH 버전을 올릴 때는 `minimal.yml`이 여전히 같은 요청을 만드는지 wire로 다시 확인해요.
