# ADR-0010: UI는 DSH Web과 같은 React 18 + CSS Modules, DSH 디자인 토큰을 쓴다

- 상태: 채택 · 2026-10-13 (단일 HTML + vanilla JS 화면을 대체)

## 맥락
- 처음 만든 화면은 HTML 파일 하나에 vanilla JS였어요. 기능은 돌아가지만 DSH Web과 생김새와 흐름이 달라서, DSH에서 하던 것을 그대로 해 보기 어려웠어요.
- DSH Web은 React 18, CSS Modules, 자체 아이콘과 디자인 토큰으로 만들어져 있어요. 라이선스는 MIT예요.

## 결정
- `ui/`에 React 18 + TypeScript + Vite 앱을 둬요. 화면 구성은 DSH Web을 그대로 따라요.
  - 왼쪽 사이드바(새 세션, 세션 목록, 설정)
  - 가운데 Chat / Trajectory 탭
  - 아래 composer(권한, 모델과 effort, 보내기/멈춤)와 통계 줄
  - 오른쪽 파일 사이드바
  - 설정 모달(General, Models, Plugins, Agent presets)
- DSH의 디자인 토큰 CSS와 아이콘을 `ui/src/vendor/dsh/`에 MIT 고지와 함께 가져와요. DeepSeek 로고와 워드마크는 쓰지 않아요.
- DSH Web에 없는 실험 기능(Runs 비교, New run, 하네스 해부)은 같은 디자인으로 사이드바의 "Experiments"에 둬요.
- 빌드 결과(`lab/viewer/static/`)를 레포에 넣어요. Python만 쓰는 사람은 Node 없이 `lab ui`를 쓸 수 있어요. UI를 고칠 때만 `cd ui && npm i && npm run build`를 해요.

## 고려한 대안
| 대안 | 안 고른 이유 |
|---|---|
| DSH Web 자체를 띄워서 쓰기 | lab 엔진(LangChain) 세션을 붙일 수 없어요. DSH의 RPC와 Cordis host가 필요해요 |
| DSH의 React 컴포넌트를 import | 컴포넌트가 Cordis 컨텍스트와 Typert RPC에 묶여 있어서 떼어 쓰기 어려워요 |
| vanilla JS 유지 | 생김새를 맞추기 어렵고 코드가 커질수록 관리가 힘들어요 |

## 결과
- 좋은 점: DSH Web에서 하던 동작을 같은 자리, 같은 모양으로 할 수 있어요.
- 감수한 점: UI 수정에는 Node가 필요해요. 빌드 산출물을 커밋하므로 소스와 산출물이 어긋나지 않게 빌드 후 함께 커밋해요.
