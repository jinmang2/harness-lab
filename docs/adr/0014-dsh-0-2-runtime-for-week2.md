# ADR-0014: week2 하네스는 DSH 0.2.0-rc.2 런타임을 따로 두고 돌린다

- 상태: 채택 · 2026-10-18

## 맥락
- week2 과제는 Creator Mode로 RALPH Plugin을 만들고, Plugin Manager로 설치하고, Custom Preset에 연결하는 과제예요. 과제 문서가 가리키는 Plugin Manager(`install_bundle`)는 DSH **0.2.0-rc.1부터** 있어요.
- 스터디 `setup.sh`와 week1 결과는 0.1.5-rc.3 기준이에요. rc.3의 Creator Mode는 `cordis_define`/`cordis_run`이라서 Plugin이 **세션 안에서만, 메모리에만** 살아요. 그래서 Preset 연결도, headless로 다시 돌리기도 안 돼요.
- 공식 `tool-ralph`의 `lib/index.js`는 0.1.5-rc.3, 0.2.0-rc.2, 0.2.1-alpha.5에서 같아요. 버전을 올려도 비교 대상 자체는 그대로예요.
- 0.2.0-rc.2를 직접 돌려 보며 확인한 차이:
  - DeepSeek 경로가 Anthropic 호환 Messages(`/anthropic/v1/messages`)예요. rc.3와 lab 엔진은 `chat/completions`를 써요.
  - 요청마다 세션 로그 전체를 `dsh_session_log` 필드로 붙여요(`session-log-deepseek`, 기본 **켜짐**. rc.3는 꺼짐). 설치된 Plugin 목록 `dsh_plugin_packages`는 두 버전 모두 기본으로 보내요.
  - 세션 로그 형식이 v4예요. `tool/result`가 `tool-result` 블록 없이 message 자체를 결과로 써요.
  - `tool-ralph`가 base와 모든 preset에서 꺼져 있어요. rc.3는 standard, ptc, cordis에서 켜져 있어요.
  - `web`과 `headless`가 서로 다른 프로필이에요. Web에서 설치한 번들은 headless에 보이지 않아요.

## 결정
- week1 하네스는 rc.3에 그대로 두고, week2 하네스만 `HARNESS_VERSIONS`로 0.2.0-rc.2를 지정해요. 버전마다 `.dsh-runtime-<버전>/`와 `.dsh-home-<버전>/`를 따로 써요. 설치는 `lab dsh-install --version 0.2.0-rc.2`예요.
- `common.yml`에서 `session-log-deepseek`와 `plugin-package-inventory-deepseek`를 끄고, 두 버전 모두에 적용해요. mock 게이트웨이로 녹화해서 필드가 빠졌는지 테스트로 확인해요.
- 게이트웨이가 `/v1/messages`도 프록시, 녹화, mock으로 처리해요. Messages usage는 이미 서로 겹치지 않는 값(`input_tokens`에 cache 미포함)이라 그대로 옮겨요.
- 파서는 v3와 v4를 모두 읽어요.
- 공식 ralph는 `dsh/patches/ralph-official.yml`로 켜요. base 행 주석에 적힌 복원 방법 그대로이고, 비교를 위해 `maxRounds: 5`로 맞춰요.
- Web에서 Creator Mode로 만든 번들은 headless 프로필에 `dsh plugin`으로 한 번 더 설치하고, Preset은 patch로 재현해요(minimal을 재현한 방식과 같아요).

## 고려한 대안
- **전부 0.2.0으로 올리기:** week1 수치와 스터디 기준 버전이 함께 바뀌어요.
- **rc.3에서 `cordis_define`으로만 하기:** 과제의 Preset 연결과 반복 실행 비교를 재현할 수 없어요.
- **0.2.1-alpha.5:** Web에 "Ralph loops" 토글이 있지만 alpha예요. latest 태그는 0.2.0-rc.2예요.

## 결과
- 좋은 점: 과제 문서의 설치 경로를 그대로 쓰면서, week1 결과와 재현 경로는 건드리지 않아요. 두 버전을 같은 wire 기준으로 잴 수 있어요.
- 감수한 점: 런타임 하나가 더 늘어요(약 508MB, 설치 약 1분). DSH 0.2 하네스는 Messages, lab 엔진은 chat/completions로 같은 모델을 불러서, **wire 형식이 다르다는 점은 비교 변수로 남아요.** 프롬프트 캐시 동작도 다를 수 있어요.

## 다시 볼 조건
- 스터디가 기준 버전을 0.2.x로 올리면, 기본 `DSH_VERSION`을 바꾸고 이 ADR을 대체해요.
- DSH가 업로드 Plugin의 기본값이나 id를 바꾸면 `common.yml`과 테스트를 고쳐요.
