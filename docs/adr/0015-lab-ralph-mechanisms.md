# ADR-0015: 반복 실행은 "Context를 어떻게 넘기나 × 누가 끝을 정하나"로 나눠서, DSH 방식 재현과 우리 설계를 같은 작업으로 잰다

- 상태: 채택 · 2026-10-18 · 개정 2026-10-19

## 맥락
- week2 과제는 공식 `tool-ralph`와 직접 만든 RALPH Plugin을 같은 작업·모델·초기 workspace·최대 Round(5)로 비교하는 거예요.
- DSH에는 반복 실행이 두 갈래 있고, 코드를 공유하지 않아요.
  - **Ralph**: Round마다 새 child를 띄우고, workspace와 보고서 하나만 넘겨요. 끝은 worker가 정해요.
  - **goal**: 같은 세션에 `<goal_round>`를 다시 보내요. 끝은 모델이 `update_goal complete`로 정해요.
  - DSH 스스로 "평범한 긴 작업은 goal, Ralph는 사람이 명시적으로 요청할 때"라고 나눠요.
- 반복 방식을 가르는 축은 두 개예요.
  - **Context**: Round마다 새 agent를 띄우나 / 같은 대화를 이어 가나 / 같은 대화를 비우고 handoff만 남기나
  - **끝내는 쪽**: worker 자신 / 별도 judge 호출 / 배포 쪽 검증 명령
- DSH 세 방식(공식 Ralph, Creator가 만든 Custom, goal)만으로는 이 칸 중 셋만 채워져요.

## 결정
`lab/middleware/ralph.py`, `lab/middleware/goal.py`, `lab/harnesses/ralph.py`에 여섯 방식을 둬요. 모두 `standard` 위에 장치 하나씩만 얹고, 최대 Round는 5예요.

| harness | Context | 끝내는 쪽 | Round 사이에 넘어가는 것 | 출처 |
|---|---|---|---|---|
| `ralph-fresh` | Round마다 새 child | worker 보고서 | 구조화 보고서(16KB) + workspace | DSH `tool-ralph` 재현 |
| `ralph-verified` | Round마다 새 child | 검증 명령 exit 0 | 검증 출력 끝 4,000자 + worker 보고 + progress 파일 | `dsh/bundles/verified-ralph` 재현 |
| `goal` | 같은 대화 | 모델의 `update_goal complete` | 대화 전체 + `<goal_round>` | DSH goal 재현 |
| `ralph-judge` | 같은 대화 | 같은 모델의 별도 judge 호출 | judge가 쓴 다음 메시지(4,000자 이내) | 우리 설계 |
| `ralph-check` | 같은 대화 | 검증 명령 exit 0 | 검증 출력 끝 4,000자 | 우리 설계 |
| `ralph-reset` | 같은 대화, Round마다 메시지 전부 삭제 | worker가 handoff 도구를 안 부르면 끝 | objective + handoff 메모 | 우리 설계 |

**DSH 재현은 원본과 줄 단위로 맞춰요.**
- `ralph-fresh`는 `tool-ralph`의 다음 부분을 옮겨요.
  - 문구: 설명, prompt section, Round 프롬프트, 결과 문구
  - 보고서 스키마와 정규화 규칙. 길이는 UTF-16 단위로 세요
  - 실패 처리: 잘못된 보고서는 `Ralph workflow failed: …`, 보고가 없으면 round-failed, 재시도 없음
  - 오류를 실행 전체를 멈추지 않고 도구 결과로 부모에게 돌려주기
  - 재귀 호출은 프롬프트로만 말려요. DSH도 코드로 막지 않아요.
- `ralph-verified`는 Creator가 쓴 `index.js`를 그대로 옮겨요(설명, 스키마 설명문, trim 정규화, Round 프롬프트, progress 파일 형식, 결과 문구, 1회 재시도).
- 두 방식 모두 child는 부모와 같은 구성(루프 도구와 그 안내 포함)을 받아요. DSH spawn child가 그렇기 때문이에요.
- child의 구조화 보고는 DSH `dsh-subagent-in-process-driver` 방식을 따라요. 평범한 `structured_output` 도구 + "반드시 이 도구로 보고하라"는 프롬프트 + 호출 즉시 턴 종료 + 기록 뒤 다른 도구 차단이에요.
  - langchain `ToolStrategy`는 `tool_choice="any"`를 강제하는데, DeepSeek thinking 모드가 이걸 400으로 거절해요. 첫 실제 실행의 child가 전부 이 이유로 실패했어요.
- `goal`의 문구와 규칙은 ADR-0013 그대로예요. 이번에 driver(`goal.next_round`)를 채팅 세션과 `lab run`이 같이 쓰게 했고, `/goal <objective>` 작업은 모델 호출 없이 goal을 만들어요. 하네스 설정 `goal_rounds`가 DSH goal 서비스의 `defaultMaxGoalRounds`에 해당하고, week2에서는 5예요.

**우리 설계는 문제에서 출발해 정해요.**
- `ralph-judge`
  - judge는 `done / reason / next`만 답해요. 근거를 댈 수 없는 신뢰도 문턱값은 두지 않아요.
  - 도구 오류만으로 멈추지 않아요. 실패하는 테스트도 작업의 일부라서요.
  - judge 답을 읽을 수 없거나 Round 상한에 닿으면 끝나요.
- `ralph-check`
  - Custom과 같은 검증 명령, 같은 상한, 같은 피드백 크기를 써요. 다른 점은 Round가 새 child가 아니라 **같은 대화**라는 것 하나예요. 그래서 "새 Context"의 효과만 따로 볼 수 있어요.
- `ralph-reset`
  - 같은 대화 기록(checkpoint)을 쓰면서, Round마다 메시지를 비우고 handoff만 남겨요.
- 검증 명령은 배포 설정이라 작업마다 바꾸지 않아요. `tasks/checks/week2_verify.py` 하나가 workspace의 SPEC 제목을 보고 맞는 수락 테스트를 돌려요. Custom preset, `ralph-verified`, `ralph-check`가 모두 이 명령을 써요.
- **검증과 채점 분리** (2026-10-19 추가): 위 검증 명령은 채점에 쓰는 수락 테스트와 같아서, Custom worker만 Round마다 채점 결과를 봐요. 공식과 비교할 때 이 정보 비대칭이 루프 설계의 효과와 섞여요. 그래서 `dsh-web`에 `ralph-custom-tests`를 더했어요.
  - Creator Plugin과 Preset을 그대로 쓰고, 검증 명령만 workspace 자체 테스트(`python3 -m unittest discover -s tests`)로 바꿔요.
  - Preset 파일(`dsh/patches/web-ralph-custom-tests.yml`)은 번들의 `cordis.patch.yml`에서 생성하고, id·이름·설명·순서·검증 명령만 다르다는 걸 테스트로 지켜요.
  - 채점은 그대로 worker가 본 적 없는 수락 테스트예요. 그래서 "검증은 통과했지만 채점은 실패"가 이 방식의 거짓 완료예요.

**측정 장치**
- 모든 방식이 trace에 `{"kind": "round", mechanism, round, decision, ...}` 이벤트를 남겨요. child는 부모 callbacks를 물려받아 같은 trace에 기록되고, metadata에 `child_thread`, `child_label`, `delegation_depth`를 달아요. batch trace의 `llm`/`tool` 이벤트에도 이 값이 `child`, `child_label`, `depth`로 남아서, `lab view`의 Trajectory가 child 호출을 `SUBAGENT`로, Round 판단을 `ROUND`로 보여 줘요.
- 작업은 두 개이고, 어느 쪽도 결과를 보기 전에 정했어요.
  - `durations-backlog`
  - `sizes-backlog`: 대소문자 구분, 밑줄 표기, half-even 반올림, 단위 넘김처럼 "다 했다고 믿기 쉬운" 규칙이 있어요.
  - `versions-backlog` (2026-10-19 추가): 앞의 두 작업에서 모든 깨끗한 실행이 13/13이라 차이를 잴 수 없었어요(천장). 그래서 버전 파싱·비교·범위 매칭 작업을 더했어요. prerelease 순서, `^0.0.x`, 부분 버전 hyphen 상한, "prerelease는 초대받아야 맞는다"처럼 모델이 자주 틀리는 규칙이 있고, 수락 테스트는 17개예요.
    - 파일럿에서 SPEC 모순(규칙 10의 "`*`는 모든 버전"과 규칙 14)이 드러나서 SPEC을 고치고 파일럿 결과는 버렸어요.
  - 둘 다 BACKLOG 4항목으로 나눠 "Round마다 한 항목"을 지시해요(원래 Ralph의 한 루프 한 가지 원칙). goal 방식은 같은 문장을 `/goal`로 넣는 짝 작업(`*-goal`)을 써요.
- 채점은 workspace 밖의 수락 테스트(규칙마다 1개, 13개)로 해요. 어느 수락 테스트를 돌릴지는 workspace의 SPEC이 아니라 **태스크 id**로 골라요. worker가 SPEC.md를 고칠 수 있어서요.
- workspace는 목록을 볼 수 없는 임시 디렉터리에 만들어요(`isolate: true`). `lab week2`는 도구 호출 인자에서 workspace 밖 경로를 모두 찾아 기록하고, 그중 **채점 자료**(`tasks/`, `tests/`, `runs/`, 다른 실행의 workspace)에 닿은 실행만 오염으로 세서 중앙값에서 빼요. DSH 시스템 프롬프트가 알려 주는 런타임 소스나 목록을 볼 수 없는 격리 폴더처럼 답과 무관한 경로는 기록만 해요.
- Round가 실패하면 루프 도구가 오류를 부모에게 돌려주고, 부모 모델이 루프 도구를 **다시 부르기도** 해요(DSH도 같아요). Round 수는 모든 호출의 합으로, 종료 사유는 마지막 호출 기준으로 세요.
- 같은 대화 방식에서 worker가 goal 도구를 스스로 쓰면 goal의 `round` 이벤트도 남아요. 집계는 그 하네스 자신의 mechanism 이벤트만 봐요.
- **네트워크 장애는 결과가 아니에요** (2026-10-19 추가). 나중 25회를 돌릴 때 DeepSeek 연결이 요청 시작 약 3초 뒤에 끊기거나(2~7%), DNS가 아예 안 되는 시간이 있었어요. 처음 30회는 3,236번 호출 중 끊김 0번이었어요. DSH는 스트림 끊김(`STREAM_CLOSED`)을 재시도하지 않아서, 그대로 두면 방식마다 운에 따라 Round가 죽어요.
  - 게이트웨이: `LAB_GATEWAY_BUFFER=1`이면 응답을 끝까지 받은 뒤 넘기고, 끊기면 업스트림에 다시 요청해요(3회). 기다리는 동안 SSE 주석으로 연결을 유지해요. 기본값에서도 첫 토큰 전(`message_start`, `ping`, `content_block_start`)의 끊김은 다시 요청해요.
  - runner: dsh 엔진은 실행 전에 API 호스트가 풀릴 때까지 기다리고, 네트워크 오류(DNS, 스트림 끊김, 연결 리셋)로 죽은 실행은 새 workspace에서 다시 돌려요(2회). summary에 `infra_retries`를 남겨요.
  - dsh-web: 마지막 턴이 오류로 끝난 세션은 host가 idle이어도 실패로 기록해요. 전에는 이걸 `ok`로 적고 있었어요.
- **최종 점수는 루프만의 결과가 아니에요** (2026-10-19 추가). DSH 루프 도구는 결과를 부모 모델에게 돌려주고, 부모는 답하기 전에 workspace를 검토하고 고치기도 해요. 공식 `tool-ralph`는 "완료는 worker 보고"라고 알려 주니 부모가 15회 모두 사후 검토를 했어요. 그래서 `lab week2`는 세 가지를 더 재요.
  - **루프 끝 시점 채점**: 부모 세션 로그에서 마지막 루프 결과 뒤의 `edit`/`write` 중 태스크 모듈을 고친 것을 찾아, `edit`는 되돌린 뒤 수락 테스트를 다시 돌려요. `write`나 셸로 고친 경우는 되돌릴 수 없어서 근사로 표시해요(`‡`).
  - **차분 테스트**(`tasks/checks/week2_fuzz.py`): 정답 코드와 최종 모듈에 같은 시드의 무작위 입력 수천 개를 넣고 결과나 예외 종류를 비교해요. 규칙마다 1개인 수락 테스트의 천장 위를 보려는 거예요. SPEC이 정하지 않은 입력은 만들지 않아서, 불일치는 곧 SPEC 위반이에요.
  - **과정 지표**: worker가 `continue`인데 검증 통과로 끝난 실행, BACKLOG 항목 수만큼 Round를 쓴 실행, 부모 세션의 토큰 몫.
  - 이걸로 처음 결론("검증과 채점을 분리한 Custom 13/14")이 "루프 끝 기준 9/14, 원인은 검증 통과만 보는 종료 규칙"으로 바뀌었어요.
- **종료 규칙 v2** (2026-10-20 추가): `verified_ralph`에 `stopWhen` 설정을 더했어요. 기본값 `verifier`는 지금까지 실험을 재현할 수 있게 그대로 두고, `verifier-and-worker`는 검증 exit 0이고 같은 Round worker가 `complete`일 때만 끝내요. `dsh-web`의 `ralph-custom-tests-v2`가 이 설정을 써요. Preset 파일(`dsh/patches/web-ralph-custom-tests-v2.yml`)은 같은 생성기에서 나오고, v1과 `stopWhen` 한 줄만 다르다는 걸 테스트로 지켜요. 종료 규칙 자체는 가짜 child와 가짜 검증을 붙인 node 실행으로 테스트해요.
  - 같은 14회 조건에서 루프 끝 만점이 9/14 → 13/14가 됐어요. v1이었다면 일찍 끝났을 실행 9회를 모두 worker `complete`까지 이어 갔어요. 남은 실패 2회(worker와 worker 테스트가 같이 틀림, 차분 테스트의 숨은 버그)는 종료 규칙이 아니라 검증 명령의 한계예요.
- **v3 파일럿과 근본 원인 검토** (2026-10-20 추가): `verified_ralph`에 worker 설정 세 개를 더했어요. 기본값은 모두 꺼져 있어요. `workerTools`(child 도구 allow 목록, provider의 `toolFilter`), `workerEffort`(child 추론 강도, `agentOptions`), `workerProtocol: focused`(progress 파일은 루프만 쓰고, 읽기를 묶고, 이번 Round 몫만 하라는 지시)예요. provider가 이 기능을 지원하지 않으면 child를 띄우기 전에 실패해요. `dsh-web`의 `ralph-custom-tests-v3`, `-v3-low`가 써요. 각 2회 만점이었지만 본 배치가 API 잔액 부족으로 멈췄어요.
  - 다시 돌리기 전에 기존 기록(게이트웨이 요청 본문)으로 비용을 분해했어요. 돈의 75%가 출력 토큰이고 시간의 97%가 모델 생성이에요. "전체 토큰"은 95%가 캐시라 지표로 쓰지 않아요. 비용은 출력 토큰과 $로 봐요.
  - 도구 제한은 대부분 캐시 입력을 줄여서 돈으로 1~2%예요. `low`는 child 출력을 10~20% 줄여요. 실행당 비용의 변동계수가 0.17이라, 방식마다 작업당 5회로는 20%보다 작은 차이를 가려낼 수 없어요. 그래서 v3는 더 재지 않아요.
  - Web Custom 실행의 Round 159개 중 "worker `complete`, 검증 실패"는 0개였어요. 검증이 worker 테스트면 종료 결정이 공식과 같아져요. 실제 실패는 모두 worker와 worker 테스트가 같이 틀린 경우라, 다음 설계는 worker와 독립된 점검자예요(재지 않았어요).
  - 실행별 `wire.jsonl`은 시간 구간으로 자른 기록이라, 같은 시간에 돈 다른 엔진의 호출이 섞일 수 있어요. 분석에서는 `bash` 도구가 있는 호출만 DSH 호출로 봐요.
- 같은 대화 방식(goal, judge, check, reset)은 graph 실행 하나가 모든 Round를 담으니 `LAB_RECURSION_LIMIT=1000`(5 × 200)으로 돌려요. 새 child 방식은 Round마다 child가 200을 따로 받아요.

## 고려한 대안
- **DSH 방식만 비교**: "새 Context의 효과"와 "검증의 효과"를 떼어 볼 수 없어요. check는 Custom과 Context만 다르고, goal은 공식 Ralph와 Context만 달라요.
- **다른 제품의 반복 기능을 그대로 옮겨 오기**: 우리 실험이 그 제품의 기본값에 묶여요. 축에서 출발해 우리 방식으로 만들어요.
- **judge를 별도 모델로**: 비교 변수가 하나 늘어요. 같은 모델로 둬요.

## 결과
- 좋은 점: 2×3 칸을 거의 다 같은 작업으로 잴 수 있어요. DSH 재현은 원본과 대조하는 테스트로 지켜요.
- 감수한 점: lab 엔진은 chat/completions, DSH 0.2는 Messages API를 써서 엔진 사이 wire 형식이 달라요(ADR-0014). 엔진 사이 수치는 같은 엔진 안의 비교보다 약하게 읽어요.
- 검증 명령에는 부모 환경변수가 그대로 넘어가요(Custom 원본과 같음). 지금 수락 스크립트는 환경변수를 읽지 않지만, 임의 명령을 받는 배포라면 넘길 변수를 골라야 해요.
- 실행 중 이력: 처음 파일럿에서는 workspace가 `runs/<batch>/` 아래에 있어서 worker가 상위 폴더로 나가 옆 실행의 구현, reference, 수락 스크립트를 읽었어요. 두 배치를 동시에 돌릴 때는 `$TMPDIR`의 옆 실행도 읽었어요. 그래서 지금의 격리(목록 권한 제거)와 감사가 생겼어요.
- 격리 뒤에도 경로를 알아낸 경우가 있었어요. ① DSH 시스템 프롬프트가 런타임 위치(`harness-lab/.dsh-runtime-…`)를 알려 줘서, 그 상위 폴더를 검색했어요. ② lab shell의 환경변수(비밀 값은 DSH와 같은 규칙으로 빼요)에 저장소 경로가 남아 있었어요. 두 경우 모두 **검증 출력의 테스트 이름**(`test_r07_sign`)을 단서로 수락 테스트 파일을 찾으러 갔어요. 검증 피드백을 주는 방식만 이렇게 움직였어요. 감사가 이런 실행을 잡아서 결과에서 빼요.
