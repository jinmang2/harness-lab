# ADR-0016: Preset과 goal은 DSH Web host를 API로 돌려서 잰다 (`dsh-web` 엔진)

- 상태: 채택 · 2026-10-19

## 맥락
- `dsh --profile headless`는 메시지 하나를 보내고 첫 idle에서 끝나요. 그래서 두 가지를 잴 수 없어요.
  - **goal**: goal-round-driver가 idle 때 다음 `<goal_round>`를 넣는데, 그 전에 프로세스가 끝나요. mock으로 확인했어요. goal은 만들어지지만 Round 1이 오지 않아요.
  - **agent preset**: 실행기가 preset을 조립하지 않아요(`runs under agent preset …, which the one-shot runner does not compose`). week2의 Verified RALPH preset도 patch로 흉내 내야 했어요(ADR-0014).
- headless 기본 구성과 Web standard preset은 행을 묶는 방식이 달라요. 공식 Ralph는 headless 기본 구성으로, goal은 Web으로만 돌면 두 결과를 같은 기준으로 비교할 수 없어요.
- DSH Web은 브라우저가 쓰는 것과 같은 단발 RPC로 조작할 수 있어요. 흐름은 `GET /?token=` → 쿠키 → `POST /api/<namespace>/<method>`예요(`dsh-client-connection`, `dsh-api-gateway`).

## 결정
- `lab/dsh_web.py`를 `dsh-web` 엔진으로 둬요. 실행마다 빈 포트에 Web host 하나를 따로 띄우고 끝나면 프로세스 그룹째 내려요. 홈은 `.dsh-home-<버전>-web/`이라 사람이 브라우저로 쓰는 홈과 섞이지 않아요.
- 실행 흐름은 이래요.
  1. `workspace/create {path}`
  2. `session/create {workspaceId, agentPreset}`
  3. 일반 프롬프트는 `session/prompt`, `/`로 시작하면 `commands/execute {agentId, line}`. composer가 slash 명령을 보내는 경로와 같아서, `/goal`은 모델 호출 없이 goal을 만들어요.
  4. `session/list`(running)와 `goals/get`을 1초마다 읽어요. idle이면서 active+armed goal이 없는 상태가 세 번 연속이면 끝으로 봐요.
- 로그는 본 세션과 `parentSession`이 그 세션인 child들이에요. headless 엔진과 같은 형식으로 돌려줘서, 파서와 summary를 그대로 써요.
- 하네스는 preset + patch 조합이에요.
  - `ralph-official` = `lab-ralph-official` preset. 설치된 standard preset을 텍스트 그대로 복사하고, 그 안의 `tool-ralph` 행만 켜요(`maxRounds: 5`). `dsh/patches/web-ralph-official.yml`은 `lab.dsh_web.ralph_preset_patch`가 만들고, 테스트가 standard와 그 한 행만 다른지 확인해요.
  - `ralph-custom` = Creator가 만든 `verified-ralph` preset을 그대로 써요. `lab dsh-web-setup`이 `dsh plugin --profile web add link:dsh/bundles/verified-ralph`로 설치해요.
  - `goal` = standard preset + `goal-5.yml`(goal 서비스 `defaultMaxGoalRounds: 5`).
- 그래서 week2의 DSH 세 방식은 모두 Web standard preset을 바탕으로 하고, 루프 장치 하나씩만 달라요.

## 고려한 대안
- **브라우저 자동화(agent-browser)로 Web 조작**: 화면이 바뀌면 깨지고 느려요. 반복 실행에 맞지 않아요.
- **headless에 `--session-id`로 이어 보내기**: 세션을 다시 열면 goal이 disarmed가 돼요(DSH 규칙: "opening a session is observation, not authority to spend resources").
- **host 하나를 batch 동안 유지**: 빠르지만 하네스마다 patch가 달라서 결국 다시 띄워야 하고, 세션끼리 host 상태를 공유해요. 실행마다 띄우는 비용은 몇 초예요.

## 결과
- 좋은 점: preset과 goal을 실제 DSH 동작 그대로 잴 수 있어요. Web 화면에서 본 것과 같은 구성이에요.
- 감수한 점: 실행마다 host 부팅 몇 초가 더 들고, 에이전트 시간(`turn_ms`)과 프로세스 시간이 더 벌어져요. 같은 홈을 쓰므로 `dsh-web` batch는 한 번에 하나만 돌려요. `session/list`는 홈의 모든 세션을 돌려주니 홈이 커지면 폴링이 느려져요.
- `/goal` 같은 slash 명령은 `commands/execute`로만 명령이 돼요. `session/prompt`로 보내면 평범한 텍스트예요.

## 다시 볼 조건
- DSH가 headless에서도 goal round와 preset을 지원하면 `dsh` 엔진으로 돌아가요.
- DSH Web RPC 이름이나 인증 방식이 바뀌면 `lab/dsh_web.py`와 그 테스트를 고쳐요.
