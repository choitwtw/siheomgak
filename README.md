# 📅 시험각 — 충돌 없는 시험 일정·강의실 자동 배정

> 경희대학교 AI 활용 경진대회 출품작

교수들이 시험 일정을 잡을 때 수강생들의 다른 시험과 겹치지 않는지 일일이 확인하는 일을 없애 줍니다.
수강신청이 끝난 **학생 시간표**와 **교수 일정**을 바탕으로 **충돌 없는 시험 일정과 강의실**을 자동으로 배정하고,
교수가 **말로(자연어로) 조건을 바꾸면** AI가 조건으로 바꿔 다시 배정합니다.

| 화면 | 할 수 있는 일 |
|---|---|
| 관리자 대시보드 | 학기·시험 기간(날짜 범위) 설정 → 학과 우선순위 자동 계산, ① 전체 배정·지표·무작위 대비 비교, ② 학과별 확정 진행 현황·일괄 확정·**전체 발표(학생 알림)**, ③ **강의실별 시험 시간표**(강의실×날짜 표, 강의실 주간표, CSV·인쇄용 HTML), 데이터 생성·업로드 |
| 교수 화면 | **내 시간표와 시험 가능 시간**(수강생 전원 시간표 대조, 칸마다 가능/학생 부담/겹치는 학생 수) — 시험 블록을 **끌어다 '가능' 칸에 놓고 같은 화면에서 강의실(시험 좌석 표시)까지 골라 바로 재배정**, 추천 일정 + 이유·경고, 자연어 수정, 변경 전/후 비교, **우선순위 차례에 확정** |
| 학생 화면 | 학번 입력 → 시험 기간 시간표(정규 수업·교양 + 시험), 발표 전 **수업시간 기준 예상 시험 일자**·추천안, 발표 후 확정 일정과 알림함 |
| 강의실 현황 | 날짜별 강의실 점유 타임라인 (학과별 색상) |

API 키가 없어도 모든 화면이 작동합니다 (규칙 기반 **대체 모드**). 키를 넣으면 Claude가 자연어 변환과 설명 문장을 맡습니다.

---

## 1. 내 Mac에서 실행하기 (처음 하는 분 기준)

### 1-1. 터미널 열기
`⌘ + Space` → "터미널" 입력 → 엔터.

### 1-2. Python 버전 확인
```bash
python3 --version
```
- `Python 3.10` 이상(예: `Python 3.12.4`)이 나오면 **1-3**으로.
- `command not found` 가 나오거나 3.9 이하라면 아래 **방법 A(uv, 추천)** 로 Python을 함께 설치합니다.

### 1-3. 프로젝트 폴더로 이동
이 저장소를 내려받은 폴더로 이동합니다. (예: 바탕화면에 `siheomgak` 폴더가 있다면)
```bash
cd ~/Desktop/siheomgak
```
> GitHub에서 받는 경우: `git clone https://github.com/<내-아이디>/siheomgak.git` 후 `cd siheomgak`

### 1-4. 가상환경 만들고 패키지 설치

**방법 A — uv 사용 (추천, Python이 없어도 됨)**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv 설치 (한 번만)
source $HOME/.local/bin/env                          # 또는 터미널을 껐다 켜기
uv venv --python 3.12 .venv                          # Python 3.12 가상환경 생성 (자동 다운로드)
source .venv/bin/activate
uv pip install -r requirements.txt
```

**방법 B — 이미 Python 3.10 이상이 있을 때**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 1-5. 실행
```bash
streamlit run app.py
```
브라우저가 자동으로 열립니다 (안 열리면 `http://localhost:8501` 접속).
처음 화면을 열면 기본 데이터로 자동 배정이 한 번 실행됩니다 (보통 수 초, 최대 20초). 기본 데이터는 `data/custom/`의 학과 제공 데이터(학생 500명·과목 48개·교수 30명·강의실 40개)이고, 이 폴더가 비어 있으면 시드 고정 가상 데이터를 씁니다.

다음부터는 폴더로 이동한 뒤 `source .venv/bin/activate` → `streamlit run app.py` 두 줄이면 됩니다.

### 1-6. (선택) Claude API 키 넣기
키가 없으면 대체 모드로 작동합니다. AI 모드를 쓰려면 둘 중 하나:

- 터미널에서 실행 전에: `export ANTHROPIC_API_KEY="sk-ant-..."`
- 또는 `.streamlit/secrets.toml.example` 을 `.streamlit/secrets.toml` 로 복사하고 키를 적기
  ```bash
  cp .streamlit/secrets.toml.example .streamlit/secrets.toml
  open -e .streamlit/secrets.toml      # 텍스트 편집기로 열어 키 입력 후 저장
  ```
`secrets.toml` 은 `.gitignore` 에 들어 있어 GitHub에 올라가지 않습니다. 화면 오른쪽 아래에 현재 모드가 표시됩니다.

### 1-7. 테스트 실행
```bash
pytest -q
```
51개 테스트(데이터 생성·CSV 검증·우선순위 순환·검증기·배정 엔진·자연어 변환·AI 실패 시 대체)가 모두 통과해야 합니다.

---

## 2. Streamlit Community Cloud로 무료 배포하기

### 2-1. GitHub에 올리기
이 폴더에는 이미 git 커밋 기록(`.git` 숨김 폴더)이 들어 있습니다. API 키 파일(`secrets.toml`)은 올라가지 않습니다.

**방법 A — GitHub Desktop (클릭만으로, 처음이라면 추천)**
1. https://desktop.github.com 에서 GitHub Desktop 설치 → 실행 → **Sign in to GitHub.com** 으로 로그인.
2. 메뉴 **File → Add Local Repository…** → `siheomgak` 폴더 선택 → **Add Repository**.
3. 위쪽 **Publish repository** 클릭 → Name `siheomgak`, **Keep this code private** 체크 해제(공개 저장소) → **Publish Repository**.
4. 브라우저에서 `https://github.com/<내-아이디>/siheomgak` 에 파일이 보이면 완료.
5. 나중에 코드를 고치면: GitHub Desktop 왼쪽 아래에 변경 요약 입력 → **Commit to main** → 위쪽 **Push origin**.

**방법 B — 터미널 (GitHub CLI)**
```bash
brew install gh            # Homebrew가 없으면 https://brew.sh 의 설치 명령을 먼저 실행
gh auth login              # GitHub.com → HTTPS → Login with a web browser 선택, 화면의 코드 입력
cd ~/Desktop/siheomgak
gh repo create siheomgak --public --source=. --push
```

**방법 C — 웹에서 빈 저장소를 만든 뒤 push**
1. https://github.com 오른쪽 위 **+** → **New repository** → 이름 `siheomgak`, README 추가 체크는 **하지 않음** → **Create repository**.
2. 터미널에서 (프로젝트 폴더 안):
   ```bash
   git remote add origin https://github.com/<내-아이디>/siheomgak.git
   git push -u origin main
   ```
   비밀번호를 물으면 GitHub 비밀번호가 아니라 **Personal access token**을 넣어야 합니다 (Settings → Developer settings → Personal access tokens). 번거로우면 방법 A·B를 쓰세요.

### 2-2. Streamlit Cloud에서 앱 만들기
1. https://share.streamlit.io 접속 → **Continue with GitHub** 로 로그인.
2. **Create app** → **Deploy a public app from GitHub**.
3. Repository: `<내-아이디>/siheomgak`, Branch: `main`, Main file path: `app.py`.
4. **Advanced settings** → Python version **3.12** 선택.
5. (AI 모드를 쓸 경우) 같은 창의 **Secrets** 칸에 아래 한 줄 입력:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```
6. **Deploy** 클릭 → 몇 분 뒤 `https://<앱이름>.streamlit.app` 주소가 생깁니다.

배포 후 키를 바꾸려면: 앱 화면 오른쪽 아래 **Manage app** → **⋮** → **Settings** → **Secrets**.

> 무료 서버는 CPU가 적어서 배정 시간이 로컬보다 길 수 있습니다. 20초 제한에 걸리면 그때까지 찾은 가장 좋은 해(실행 가능해)를 보여 주며, 반드시 지킬 조건은 그 경우에도 항상 지켜집니다. 관리자 화면에서 제한 시간을 늘릴 수 있습니다.

---

## 3. 시연 순서 (본선용)

1. **관리자 대시보드** — 학기 26-2, 시험 기간 12/15(화)~12/21(월)(주말 제외 5일) 확인 → 우선순위 표(수학과 1순위) → **① 배정 실행**: "반드시 지킬 조건 위반 0건", 무작위 배정 대비 시간 충돌 학생 270여 명 → 0명.
2. **학생 화면(발표 전)** — 학생 선택 → "수업시간 기준 예상"으로 바꾸면 정규 수업 시간 기준 예상 시험 일자가 보임 (정정 기간 전에도 대략 알 수 있음).
3. **교수 화면** — 1순위 학과 교수(← 확정 차례) 선택 → **내 시간표와 시험 가능 시간**에서 수강생 시간표 대조 결과(가능/겹치는 학생 수) 확인 → 남색 시험 블록을 초록 칸으로 **끌어다 놓고** 아래에서 강의실 선택 → "이 시간·강의실로 옮기기", 또는 자연어 "목요일 오후는 안 되고, 가능하면 오전으로" → 재배정 → 전/후 비교 → **✅ 확정**.
4. 다른(하위 순위) 학과 교수를 고르면 "상위 학과 확정이 끝나야 확정 가능"으로 잠겨 있음을 보여 줌.
5. **관리자 ② 확정 진행·발표** — 남은 학과를 우선순위 순서대로 "추천안으로 일괄 확정" → **📢 발표하기** → 수강생 알림 발송.
6. **관리자 ③ 강의실별 시험 시간표** — 강의실×날짜 표, 강의실 주간표, CSV·인쇄용 HTML 내려받기.
7. **학생 화면(발표 후)** — 알림함의 "[26-2학기 기말 시험 일정 발표]" 알림, 시간표에 남색 확정 블록.

---

## 4. 배정 규칙

**반드시 지킬 조건** (하나라도 어기면 결과로 인정하지 않음 — 별도 검증기가 매번 다시 검사)
1. 같은 학생의 시험끼리, 그리고 수업시간 시험·진행 중인 정규 수업(시험 없음 과목)과 시간이 겹치지 않음
2. 교수 불가 시간 배정 금지, 같은 교수의 시험끼리 겹치지 않음
3. 강의실 수용인원 ≥ 수강인원, 같은 강의실·같은 시간에 두 시험 불가 (강의실 사용학과 제한 포함)
4. 교수가 확정한 시험은 이후 재배정에서도 바뀌지 않음

**되도록 지킬 조건** (벌점 최소화, 학과 우선순위 배수를 곱함)

| 조건 | 기본 벌점 |
|---|---|
| 학생 하루 3과목 이상 시험 (초과 1과목당) | 100 |
| 연속 시험 (앞 시험 종료 ~ 다음 시험 시작 30분 미만, 학생 1명당) | 20 |
| 교수 선호 시간 미반영 (교수가 직접 요청한 선호는 2배) | 50 |
| 강의실 남는 좌석 (10석당) | 3 |

**학과 우선순위 순환**: 기준 순서 물리 → 수학 → 생물 → 지리 → 정보디스플레이 → 화학. 26-1학기 물리학과 1순위, 26-2학기 수학과, 27-1학기 생물학과 … 매 학기 한 칸씩. 1순위 6배 … 6순위 1배.

**시험 기간**: 관리자 화면에서 날짜 범위로 정합니다(기본 26-2학기 12월 15일~21일, 주말 제외 → 화·수·목·금·월 5일). 정규 수업·교수 불가 시간은 요일로 적혀 있으므로 각 시험일의 요일로 맞춰 봅니다.

**시험 좌석**: 시험은 띄어 앉으므로 강의실마다 `시험 좌석`(기본 좌석의 2/3, rooms.csv 의 `exam_capacity` 로 직접 지정 가능)을 따로 둡니다. 별도 시험은 시험 좌석이 수강인원 이상인 강의실에만 배정합니다. 수업시간 시험은 정규 강의실에서 보며, 시험 좌석이 부족하면 교수 화면에 경고가 나옵니다.

**교양 과목**: 학생 시간표에 있는 다른 단과대 교양 과목은 시험 일정을 이 시스템이 정하지 않으므로, 그 정규 수업 시간을 수강생의 "시험 불가 시간"으로 막아 둡니다.

**진행 흐름**: ① 교수가 시험 가능 시간을 확인 → ② 학과 우선순위가 높은 학과부터 확정(상위 학과가 확정한 시간·강의실은 이후 배정에서 고정) → ③ 관리자가 강의실별 시간표 확인·출력 → ④ 전체 발표 시 학생 개인 알림 + 시간표 표시(정정 기간 참고). 관리자 화면에서 "교수 확정 즉시 개별 알림" 방식으로 바꿀 수도 있습니다.

**시험 방식**
- 수업시간 시험: 시험 주간의 정규 수업 요일·시각·강의실에서 시행. 주 2회 수업이면 두 회차 중 하루를 엔진이 고릅니다 (나머지 회차 휴강).
- 별도 시험: 엔진이 시간(30분 단위 시작)과 강의실을 배정.
- 시험 없음(과제 대체): 정규 수업이 계속 진행되어 수강생은 그 시간에 다른 시험 불가.

---

## 5. 폴더 구조

```
app.py                  진입점 (streamlit run app.py)
views/                  화면: admin.py, professor.py, student.py, rooms.py
ui/                     세션 상태(state.py), 디자인(style.py), 표 변환(tables.py)
core/
  config.py             설정 상수 (가중치, LLM 모델명 등)
  datagen.py            가상 데이터 생성기 (시드 고정)
  csvio.py              CSV 업로드·다운로드·검증 (한국어 오류 메시지)
  scheduler.py          배정 엔진 (OR-Tools CP-SAT) + 해 없음 원인 분석
  validator.py          독립 검증기 (반드시 지킬 조건 위반 수 + 품질 지표)
  baseline.py           비교 기준: 수작업(무작위) 배정
  explain.py            배정 이유·경고·대안(영향 분석) 계산
  nlparse.py            자연어 → 조건 (Claude, 실패 시 규칙 기반)
  llm.py                Claude API 연결 (키: 환경변수 / st.secrets)
  constraints.py        교수 요청 조건 JSON 스키마·검증
  priority.py           학기별 학과 우선순위 순환
prompts/                LLM 프롬프트 (조건 변환, 이유 설명, 영향 분석)
data/templates/         빈 CSV 템플릿 + 컬럼 설명 README
data/sample/            기본 가상 데이터 CSV (시드 42)
tests/                  pytest
DEVLOG.md               개발 기록 (AI 활용 과정)
```

## 6. CSV로 데이터 바꾸기
관리자 대시보드 → **🗂️ 데이터 준비** 탭에서 업로드합니다. 컬럼 설명은 [`data/templates/README.md`](data/templates/README.md).
틀린 값이 있으면 "몇 행, 어떤 컬럼, 무엇이 문제인지" 한국어로 알려 줍니다. 결과 일정표는 같은 화면에서 CSV/ZIP으로 내려받을 수 있습니다.

## 7. 설정 바꾸기
- 화면에서: 학기, 시험 주간 시작일, 하루 시간대(기본 09:00~18:00), 풀이 시간 제한(기본 20초), 가상 데이터 규모(학생·과목·교수·강의실 수, 시드).
- 코드에서: `core/config.py` — 벌점 가중치, 30분 단위, LLM 모델명(`LLM_MODEL`).
