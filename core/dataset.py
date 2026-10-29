"""데이터 모델: 5개 테이블(학생·과목·교수·강의실·수강내역)과 스키마 정의."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

import pandas as pd

from .config import DEPARTMENTS, EXAM_IN_CLASS, EXAM_NONE, EXAM_SEPARATE
from .timeutil import Window, hm_to_min, parse_days, parse_windows

# ---------------------------------------------------------------------------
# 스키마: (컬럼명, 한국어 이름, 자료형, 필수 여부, 설명, 예시)
# 업로드 시 한국어 컬럼명도 받아들인다.
# ---------------------------------------------------------------------------
SCHEMAS: dict[str, list[tuple[str, str, str, bool, str, str]]] = {
    "students": [
        ("student_id", "학번", "str", True, "학생 고유 번호", "2026010001"),
        ("name", "이름", "str", True, "학생 이름", "김민준"),
        ("major", "주전공", "str", True, "주전공 학과명 (이과대학 6개 학과 중 하나)", "물리학과"),
        ("grade", "학년", "int", True, "1~4", "2"),
        ("double_major", "복수전공", "str", False, "복수전공 학과명, 없으면 빈칸", "수학과"),
        ("minor", "부전공", "str", False, "부전공 학과명, 없으면 빈칸", ""),
    ],
    "courses": [
        ("course_code", "과목코드", "str", True, "과목 고유 코드", "PHY201"),
        ("course_name", "과목명", "str", True, "과목 이름", "역학1"),
        ("department", "개설학과", "str", True, "개설 학과명", "물리학과"),
        ("target_grades", "대상학년", "str", True, "쉼표로 구분한 대상 학년", "2,3"),
        ("professor_id", "담당교수", "str", True, "교수ID (professors.csv의 professor_id)", "P01"),
        ("class_days", "수업요일", "str", True, "정규 수업 요일, 쉼표 구분 (월~금)", "월,수"),
        ("class_start", "수업시작", "str", True, "정규 수업 시작 시각 HH:MM", "10:30"),
        ("class_end", "수업종료", "str", True, "정규 수업 종료 시각 HH:MM", "11:45"),
        ("class_room", "정규강의실", "str", True, "정규 강의실 ID (rooms.csv의 room_id)", "이과대학-101"),
        ("enrollment", "수강인원", "int", False, "수강 인원 (비우면 수강내역에서 자동 계산)", "48"),
        ("exam_type", "시험방식", "str", True, "수업시간 / 별도 / 없음 (a/b/c 도 가능)", "별도"),
        ("exam_minutes", "시험시간", "int", True, "시험 시간(분): 60, 75, 90, 120", "90"),
    ],
    "professors": [
        ("professor_id", "교수ID", "str", True, "교수 고유 ID", "P01"),
        ("name", "이름", "str", True, "교수 이름", "이서연"),
        ("department", "소속학과", "str", True, "소속 학과명", "물리학과"),
        ("courses", "담당과목", "str", False, "담당 과목코드, 쉼표 구분 (비우면 과목표에서 자동 계산)", "PHY201,PHY301"),
        ("unavailable", "불가시간", "str", False, "시험 불가 시간대, 세미콜론 구분 (요일 HH:MM-HH:MM)", "수 13:00-18:00; 금 09:00-12:00"),
        ("preferred", "선호시간", "str", False, "선호 시간대, 형식 동일. '매일 09:00-12:00' 처럼 매일도 가능", "매일 09:00-12:00"),
    ],
    "rooms": [
        ("room_id", "강의실ID", "str", True, "강의실 고유 ID", "이과대학-101"),
        ("building", "건물", "str", True, "건물 이름", "이과대학"),
        ("room_no", "호실", "str", True, "호실 번호", "101"),
        ("capacity", "수용인원", "int", True, "좌석 수", "80"),
        ("departments", "사용학과", "str", True, "사용 가능 학과, 쉼표 구분. 모든 학과 공용이면 '전체'", "물리학과,수학과"),
    ],
    "enrollments": [
        ("student_id", "학번", "str", True, "학번 (students.csv)", "2026010001"),
        ("course_code", "과목코드", "str", True, "과목코드 (courses.csv)", "PHY201"),
    ],
}

TABLE_LABELS = {
    "students": "학생",
    "courses": "과목",
    "professors": "교수",
    "rooms": "강의실",
    "enrollments": "수강 내역",
}

EXAM_TYPE_ALIASES = {
    "a": EXAM_IN_CLASS, "수업시간": EXAM_IN_CLASS, "수업시간 시험": EXAM_IN_CLASS, "수업시간시험": EXAM_IN_CLASS,
    "b": EXAM_SEPARATE, "별도": EXAM_SEPARATE, "별도 시험": EXAM_SEPARATE, "별도시험": EXAM_SEPARATE,
    "c": EXAM_NONE, "없음": EXAM_NONE, "시험 없음": EXAM_NONE, "시험없음": EXAM_NONE, "과제대체": EXAM_NONE,
    "과제 대체": EXAM_NONE, "시험 없음(과제 대체)": EXAM_NONE,
}


def columns(table: str) -> list[str]:
    return [c[0] for c in SCHEMAS[table]]


def korean_labels(table: str) -> dict[str, str]:
    return {c[0]: c[1] for c in SCHEMAS[table]}


@dataclass
class Course:
    code: str
    name: str
    dept: str
    grades: list[int]
    prof: str
    days: list[int]
    start: int
    end: int
    room: str
    enrollment: int
    exam_type: str
    exam_minutes: int

    @property
    def class_len(self) -> int:
        return self.end - self.start

    def class_blocks(self) -> list[tuple[int, int, int]]:
        """정규 수업 (요일, 시작, 종료) 목록"""
        return [(d, self.start, self.end) for d in self.days]

    @property
    def in_class_exam_minutes(self) -> int:
        """수업시간 시험이 차지하는 시간: 정규 수업 길이 (시험시간이 더 길면 시험시간)"""
        return max(self.class_len, self.exam_minutes)

    def in_class_exam_options(self) -> list[tuple[int, int, int]]:
        """수업시간 시험이 가능한 회차: 시험 주간의 정규 수업 요일들 (같은 시작 시각·강의실).
        주 2회 수업이면 둘 중 하루를 배정 엔진이 고르고, 나머지 회차는 휴강."""
        return [(d, self.start, self.start + self.in_class_exam_minutes) for d in self.days]


@dataclass
class Professor:
    pid: str
    name: str
    dept: str
    unavailable: list[Window]
    preferred: list[Window]


@dataclass
class Room:
    rid: str
    building: str
    room_no: str
    capacity: int
    departments: list[str]   # 빈 리스트 = 전체 공용

    def allows(self, dept: str) -> bool:
        return not self.departments or dept in self.departments


@dataclass
class Dataset:
    students: pd.DataFrame
    courses: pd.DataFrame
    professors: pd.DataFrame
    rooms: pd.DataFrame
    enrollments: pd.DataFrame
    meta: dict = field(default_factory=dict)

    def tables(self) -> dict[str, pd.DataFrame]:
        return {
            "students": self.students,
            "courses": self.courses,
            "professors": self.professors,
            "rooms": self.rooms,
            "enrollments": self.enrollments,
        }

    # ---- 파생 구조 (읽기 전용으로 사용) ----
    @cached_property
    def course_map(self) -> dict[str, Course]:
        out = {}
        for r in self.courses.itertuples(index=False):
            out[r.course_code] = Course(
                code=r.course_code,
                name=r.course_name,
                dept=r.department,
                grades=[int(g) for g in str(r.target_grades).replace(" ", "").split(",") if g],
                prof=r.professor_id,
                days=parse_days(r.class_days),
                start=hm_to_min(r.class_start),
                end=hm_to_min(r.class_end),
                room=r.class_room,
                enrollment=int(r.enrollment),
                exam_type=r.exam_type,
                exam_minutes=int(r.exam_minutes),
            )
        return out

    @cached_property
    def prof_map(self) -> dict[str, Professor]:
        out = {}
        for r in self.professors.itertuples(index=False):
            out[r.professor_id] = Professor(
                pid=r.professor_id,
                name=r.name,
                dept=r.department,
                unavailable=parse_windows(r.unavailable),
                preferred=parse_windows(r.preferred),
            )
        return out

    @cached_property
    def room_map(self) -> dict[str, Room]:
        out = {}
        for r in self.rooms.itertuples(index=False):
            deps = [d.strip() for d in str(r.departments).split(",") if d.strip()]
            if any(d in ("전체", "공용", "all") for d in deps):
                deps = []
            out[r.room_id] = Room(r.room_id, str(r.building), str(r.room_no), int(r.capacity), deps)
        return out

    @cached_property
    def students_of(self) -> dict[str, list[str]]:
        """과목코드 -> 학번 목록"""
        out: dict[str, list[str]] = {c: [] for c in self.courses["course_code"]}
        for sid, cc in zip(self.enrollments["student_id"], self.enrollments["course_code"]):
            out.setdefault(cc, []).append(sid)
        return out

    @cached_property
    def courses_of(self) -> dict[str, list[str]]:
        """학번 -> 과목코드 목록"""
        out: dict[str, list[str]] = {s: [] for s in self.students["student_id"]}
        for sid, cc in zip(self.enrollments["student_id"], self.enrollments["course_code"]):
            out.setdefault(sid, []).append(cc)
        return out

    @cached_property
    def prof_courses(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {p: [] for p in self.professors["professor_id"]}
        for c in self.course_map.values():
            out.setdefault(c.prof, []).append(c.code)
        return out

    def summary(self) -> dict[str, int]:
        ct = self.courses["exam_type"].value_counts().to_dict()
        return {
            "학생": len(self.students),
            "과목": len(self.courses),
            "교수": len(self.professors),
            "강의실": len(self.rooms),
            "수강 내역": len(self.enrollments),
            "수업시간 시험": int(ct.get(EXAM_IN_CLASS, 0)),
            "별도 시험": int(ct.get(EXAM_SEPARATE, 0)),
            "시험 없음": int(ct.get(EXAM_NONE, 0)),
        }

    def with_course_update(self, code: str, **changes) -> "Dataset":
        """과목 한 개의 값을 바꾼 새 Dataset을 돌려준다 (원본 불변)."""
        courses = self.courses.copy()
        idx = courses.index[courses["course_code"] == code]
        for k, v in changes.items():
            courses.loc[idx, k] = v
        return Dataset(self.students, courses, self.professors, self.rooms, self.enrollments, dict(self.meta))


def dept_valid(name: str) -> bool:
    return name in DEPARTMENTS
