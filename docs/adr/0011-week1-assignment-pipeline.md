# ADR-0011: week1 과제는 태스크 파일과 제출용 결과 생성기로 돌린다

- 상태: 채택 · 2026-10-13

## 맥락
- 스터디 week1 과제는 두 가지예요.
  - 같은 질문("오늘 서울 날씨는 어땠어?")을 Minimal과 Standard에서 비교하기
  - **Standard보다 Minimal이 더 잘 답하는 질문 3개**를 찾아 정확성, 토큰, 실행 시간을 비교하기
- 제출물은 `workspace/week1/<GitHub-ID>/result.md`예요. 실행 시각, 모델, 질문과 답변 요약, 사용 Tool, 입력/출력/전체 토큰, 실행 시간, Minimal이 더 낫다고 본 이유가 들어가요.
- 스터디는 DSH Web의 Minimal mode와 Standard mode를 기준으로 해요.

## 결정
- `tasks/week1-assignment.yaml`에 실험 질문과 후보 질문을 둬요. 후보마다 정답 확인(`check`)이나 rubric을 붙여요.
- **제출 수치는 DSH 엔진(`-e dsh`) 기준**으로 내요. 스터디가 DSH 프리셋을 비교하기 때문이에요. lab 엔진 결과는 참고로 함께 적어요.
- `lab week1 runs/<batch>`가 제출 형식의 `result.md`를 만들어요. "Minimal이 더 좋은 이유"는 기계가 정하지 않아요. 측정값과 judge 점수를 근거로 사람이 마지막에 고쳐 써요.
- 후보는 여러 개 돌리고, Minimal이 실제로 더 나은 3개를 골라요.

## 결과
- 좋은 점: 다시 돌려도 같은 형식으로 나오고, 다른 주차에도 재사용할 수 있어요.
- 감수한 점: 실제 모델 키가 있어야 해요. mock 결과는 제출에 쓰지 않아요. 키, credential, 세션 로그는 제출물에 넣지 않아요.
