"""시험각 전역 설정값.

화면에서 바꿀 수 있는 값은 기본값만 여기 두고, 실제 값은 세션 상태(Settings)에 저장한다.
"""
from __future__ import annotations

# ---- 학과 (우선순위 기준 순서) ----
DEPARTMENTS: list[str] = [
    "물리학과",
    "수학과",
    "생물학과",
    "지리학과",
    "정보디스플레이학과",
    "화학과",
]

# 이과대학 밖에서 듣는 교양 과목 (시험 일정은 우리가 정하지 않음 → 정규 수업 시간을 막아 둔다)
GENERAL_DEPT = "교양"

# 화면용 학과 색상 (남색 계열 포인트와 어울리는 차분한 팔레트)
DEPT_COLORS: dict[str, str] = {
    "물리학과": "#3B5BDB",
    "수학과": "#0CA678",
    "생물학과": "#E8590C",
    "지리학과": "#AE3EC9",
    "정보디스플레이학과": "#1098AD",
    "화학과": "#D6336C",
    GENERAL_DEPT: "#868E96",
}

DAYS: list[str] = ["월", "화", "수", "목", "금"]          # 정규 수업 요일
WEEKDAYS: list[str] = ["월", "화", "수", "목", "금", "토", "일"]
DAY_FULL: dict[str, str] = {d: d + "요일" for d in DAYS}

# ---- 시험 방식 ----
EXAM_IN_CLASS = "수업시간"   # (a) 정규 수업 시간·강의실 고정
EXAM_SEPARATE = "별도"       # (b) 알고리즘이 시간·강의실 배정
EXAM_NONE = "없음"           # (c) 과제 대체, 정규 수업 계속 진행
EXAM_TYPES = [EXAM_IN_CLASS, EXAM_SEPARATE, EXAM_NONE]
EXAM_TYPE_LABEL = {
    EXAM_IN_CLASS: "수업시간 시험",
    EXAM_SEPARATE: "별도 시험",
    EXAM_NONE: "시험 없음(과제 대체)",
}
EXAM_MINUTES_CHOICES = [60, 75, 90, 120]

# ---- 시간 모델 기본값 ----
DEFAULT_DAY_START = "09:00"
DEFAULT_DAY_END = "18:00"
SLOT_MINUTES = 30            # 시작 시각 단위
CONSECUTIVE_GAP_MIN = 30     # 이 값 미만 간격이면 '연속 시험'
MAX_EXAMS_PER_DAY = 2        # 학생 1명당 하루 최대 시험 수 (되도록)
DEFAULT_TIME_LIMIT_SEC = 20
# 시험 좌석: 시험은 한 칸씩 띄어 앉으므로 좌석 수보다 적게 들어간다 (rooms.csv 의 exam_capacity 를 비우면 이 비율)
EXAM_SEAT_RATIO = 2 / 3
STALL_SEC = 6               # 더 좋은 해가 이 시간 동안 안 나오면 탐색 종료

# ---- 최적화 벌점 가중치 (되도록 지킬 조건) ----
W_OVERLOAD = 100      # 하루 3과목 이상 시험 학생 1명(초과 1과목)당
W_CONSECUTIVE = 20    # 연속 시험 학생 1명당
W_PREFERENCE = 50     # 선호 시간 미반영 과목 1개당
W_AVOID = 50          # '가능하면 피해 달라'는 시간에 배정된 과목 1개당
W_ROOM_WASTE = 3      # 남는 좌석 10석당
W_STABILITY = 30      # 재배정 시 다른 과목 일정이 바뀌면 1과목당 (우선순위 무관)

# ---- 데이터 생성 기본 규모 ----
DEFAULT_SEED = 42
DEFAULT_N_STUDENTS = 500
DEFAULT_N_PROFESSORS = 25
MAX_COURSE_ENROLLMENT = 190

# ---- LLM ----
LLM_MODEL = "claude-opus-5-5"       # 모델명은 여기서만 바꾸면 된다
LLM_EFFORT = "low"                  # 짧은 변환·문장 작업이라 응답 속도 우선
LLM_TIMEOUT_SEC = 20
LLM_MAX_TOKENS = 4000      # 적응형 사고 토큰 포함
