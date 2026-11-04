# 시험각 — 작업 인계 메모 (Claude Code가 세션 시작 시 자동으로 읽음)

## 프로젝트
- 경희대 AI 활용 경진대회 출품작. 수강생 시간표를 대조해 겹치지 않는 기말고사 일정·강의실을 자동 배정하는 Streamlit 웹앱.
- 배포: https://siheomgak.streamlit.app (Streamlit Community Cloud, 이 저장소 `main` 브랜치에 push하면 자동 반영)
- **심사 기간: 2026-11-13까지 앱이 항상 접속 가능해야 함.**

## 구조·명령
- `app.py`(진입점) · `views/`(관리자·교수·학생·강의실 화면) · `ui/`(상태·위젯·표) · `core/`(배정 엔진 `scheduler.py`, 독립 검증기 `validator.py`, 자연어 `nlparse.py`·`llm.py`) · `prompts/`(Claude 프롬프트)
- 실행: `streamlit run app.py` / 테스트: `python -m pytest -q` (57개 통과 상태)
- 기본 데이터: `data/custom/*.csv` (원본 엑셀 `data/custom/source/dataset_2026-2.xlsx`, 변환 `scripts/import_xlsx.py`). 대형강의실 3곳만 시험좌석=좌석 전체, 나머지는 2/3.
- 개발 기록: `DEVLOG.md` (단계별 문제와 해결). 새 작업도 여기에 기록.

## 배포 운영 (중요)
- `.github/workflows/keep-awake.yml`: 매시간 앱을 방문해 잠들지 않게 함(`scripts/keep_awake.py`). 관리자·교수·학생 화면을 열어 위젯 오류까지 검사하고, 실패하면 GitHub가 메일을 보냄. 결과 확인: `gh run list --repo choitwtw/siheomgak --workflow keep-awake.yml`
- 2026-11-03~04 장애: 배포 앱이 정적 파일(`~/+/static/js`)에 500을 내며 무한 로딩·위젯 오류("Importing a module script failed").
  조치: ① `requirements.txt`에 웹 서버 패키지(starlette·uvicorn·anyio·websockets·python-multipart) 버전 고정
  ② 첫 배정·무작위 비교 지표를 `st.cache_resource`로 세션 간 공유(`ui/state.py`) ③ CP-SAT 작업자 4개 고정.
  **그래도 11/04 02:00 UTC 기준 keep-awake #14~#24 모두 실패**(health는 정상, static js 500). 로컬 재현 안 됨 → Streamlit Cloud 쪽 문제로 보고 사용자에게 Reboot app 요청함. 다음 세션은 먼저 최신 실행 결과부터 확인할 것.
- 다시 이런 증상이 나면: share.streamlit.io → siheomgak → ⋮ → **Reboot app**, Manage app의 로그 확인.
- `requirements.txt`를 바꾸면 Streamlit Cloud가 패키지를 다시 설치·재시작함.

## 제출 문서 (claude.ai Docs, 사용자 계정)
- 프로젝트 소개서: https://claude.ai/artifact/9vuStzNHbfYK7cZGVWGXnn (글자 수 제한: 요약·1번·4번 1000자, 3번 500자)
- AI 활용 과정 설명서: https://claude.ai/artifact/EGHrpZWJctbM4qwbgnZTxp (출처 표는 대회 양식 5칸 형식)
- 핵심 수치(평가용 데이터, 무작위 20회 평균 → 시험각): 위반 309→0건, 시험 겹침 학생 237→0명, 하루 3과목 이상 143→0명, 연속 시험 81→8명, 좌석 활용률 57→75%, 배정 약 2초.

## 교수 화면 (11/04 개편)
- 연로한 교수님 기준 4단계 화면(`views/professor.py`): ① 과목 → ② 시험 시간 버튼(`EXAM_DURATION_BUTTONS`, 저장 전 미리 보기로 시간표 블록 길이·가능 칸이 바뀜) → ③ 시간표(`ui/board.py`)에서 초록 칸 누르기 → ④ 확정/되돌리기. 자연어·영향 분석·전후 비교는 '더 많은 기능' 접이식.

## 남은 일 / 확인할 것
- 11/13까지 keep-awake 실패 메일이 오면 원인 확인·조치. 심사가 끝나면 Actions에서 "앱 깨워 두기" 끄기.
- 소개서·설명서의 ChatKHU 요청문이 사용자가 실제로 쓴 문구와 같은지 확인 필요(사용자 확인 대기).
- 배포 앱의 AI 모드는 Streamlit Secrets에 `ANTHROPIC_API_KEY`가 있어야 동작(없으면 규칙 기반 대체 모드).
- 저장소에 LICENSE 없음(필요 시 MIT 추가는 사용자 결정).

## 작업 규칙
- 사용자와는 한국어로. 파일 삭제처럼 되돌릴 수 없는 작업, 저장소에 예약 작업 추가 같은 일은 먼저 물어볼 것.
- 변경 후 pytest 통과 확인 → commit → `main`에 push(배포 반영). 배포 반영은 keep-awake 수동 실행(`gh workflow run keep-awake.yml -f attempts=1`)으로 확인.
