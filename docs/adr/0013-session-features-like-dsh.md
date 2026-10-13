# ADR-0013: goal, steer/대기열, fork, 첨부, 대화 중 모델 변경도 DSH 동작을 그대로 따른다

- 상태: 채택 · 2026-10-13

## 맥락
- DSH Web에는 plan mode 말고도 goal(`/goal`, 자동 이어 하기), 실행 중 보낸 메시지의 대기열과 steer, 대화 fork("Branch into a new conversation"), 첨부(이미지·파일), 대화 중 모델·effort 변경이 있어요.
- 스터디 목적상 "모델이 무엇을 보는가"가 DSH와 같아야 비교가 의미 있어요.

## 결정
- **goal** (`lab/middleware/goal.py`): 도구 3개(`create_goal`, `get_goal`, `update_goal`)의 이름·설명·스키마·결과 JSON·오류 문구, `tool:goal` 프롬프트 섹션, `<goal_round>` 이어 하기 프롬프트, `<goal_complete>`/`<goal_blocked>` 마무리 안내를 DSH에서 그대로 가져와요. goal은 그래프 상태(`goal`)에 두고, 채팅 세션이 DSH round driver처럼 턴이 끝나 idle이고 goal이 active+armed이면 다음 라운드를 보내요. 기본 상한 256라운드, `blocked`는 3라운드 이후만 허용해요.
- **steer와 대기열** (`lab/middleware/inbox.py`): 실행 중 보낸 메시지는 기본으로 다음 턴 대기열(next-turn)에 들어가요. steer는 다음 모델 호출 직전에 평범한 user 메시지로 들어가고, 남아 있으면 턴이 끝나지 않아요(DSH agent loop와 같음). 대기열 항목은 수정·삭제·steer할 수 있어요.
- **fork**: 끝난 턴까지의 그래프 체크포인트와 화면 이벤트를 새 세션으로 복사해요. 작업 폴더는 DSH처럼 공유해요(복사하지 않음). 제목은 `(1)`, `(2)`로 늘리고, goal은 disarmed로 시작해요.
- **첨부** (`lab/viewer/attachments.py`): 이미지(PNG/JPEG/WebP/GIF)는 이미지 입력을 선언한 모델(`deepseek-flash`, `deepseek-v4-flash-vision-exp`)에서만 image 블록으로 보내요. 그 밖의 파일은 읽기 전용 사본으로 저장하고 DSH의 `[File …]` 안내 문구만 보내요. DSH headless 엔진에는 파일 안내 문구만 붙이고 이미지는 거절해요.
- **모델 변경**: 실행 중에도 바꿀 수 있어요. LangChain 에이전트는 요청마다 도구를 다시 바인딩하므로 모델 객체를 제자리에서 바꾸면 DSH처럼 다음 요청부터 적용돼요.
- 모두 lab 엔진 기능이에요. goal과 plan은 standard 계열에만 있고, steer는 모든 lab 하네스에 있어요.

## 고려한 대안
- **goal을 UI 쪽 반복 전송으로 흉내 내기:** 모델이 보는 도구·프롬프트가 DSH와 달라져 비교 의미가 없어요.
- **steer를 다음 턴으로 미루기:** 구현은 쉽지만 DSH의 "실행 중 끼어들기" 동작과 달라요.

## 결과
- 좋은 점: DSH Web의 대화 기능을 lab 엔진에서 같은 문구로 실험할 수 있어요.
- 감수한 점: standard 계열 도구가 3개 늘어 입력 토큰이 늘어요(ADR-0012와 같은 이유로 DSH standard에 더 가까워짐). goal activation은 프로세스 메모리 대신 그래프 상태에 둬요. 서버를 다시 띄우면 지난 세션은 읽기 전용이라 차이가 드러나지 않아요.

## 다시 볼 조건
- DSH가 goal·inbox·fork 규칙을 바꾸면 따라 고쳐요.
- DeepSeek API의 이미지 입력 지원이 바뀌면 모델 목록의 `input`을 고쳐요.
