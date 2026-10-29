import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.datagen import GenConfig, generate  # noqa: E402
from core.dataset import Dataset  # noqa: E402
from core.scheduler import solve  # noqa: E402
from core.settings import Settings  # noqa: E402


def tiny_dataset(courses_extra=None) -> Dataset:
    """손으로 만든 작은 데이터: 학생 4명, 과목 4개, 교수 3명, 강의실 3개"""
    students = pd.DataFrame([
        dict(student_id="S1", name="가", major="물리학과", grade=2, double_major="", minor=""),
        dict(student_id="S2", name="나", major="물리학과", grade=2, double_major="", minor=""),
        dict(student_id="S3", name="다", major="수학과", grade=3, double_major="", minor=""),
        dict(student_id="S4", name="라", major="수학과", grade=3, double_major="", minor=""),
    ])
    rows = [
        # code, name, dept, prof, days, start, end, room, type, minutes
        ("A1", "역학", "물리학과", "P1", "월,수", "10:30", "11:45", "R50", "별도", 90),
        ("A2", "전자기", "물리학과", "P1", "화,목", "10:30", "11:45", "R50", "별도", 60),
        ("B1", "해석학", "수학과", "P2", "월,수", "13:30", "14:45", "R30", "수업시간", 75),
        ("B2", "대수학", "수학과", "P3", "화,목", "13:30", "14:45", "R30", "없음", 75),
    ]
    rows += courses_extra or []
    courses = pd.DataFrame([dict(course_code=c, course_name=n, department=d, target_grades="2,3", professor_id=p,
                                 class_days=dd, class_start=s, class_end=e, class_room=r, enrollment=0,
                                 exam_type=t, exam_minutes=m) for c, n, d, p, dd, s, e, r, t, m in rows])
    profs = pd.DataFrame([
        dict(professor_id="P1", name="교수1", department="물리학과", courses="", unavailable="금 09:00-18:00", preferred=""),
        dict(professor_id="P2", name="교수2", department="수학과", courses="", unavailable="", preferred=""),
        dict(professor_id="P3", name="교수3", department="수학과", courses="", unavailable="", preferred=""),
    ])
    rooms = pd.DataFrame([
        dict(room_id="R30", building="이과대학", room_no="101", capacity=30, departments="전체"),
        dict(room_id="R50", building="이과대학", room_no="102", capacity=50, departments="전체"),
        dict(room_id="R200", building="공동강의동", room_no="101", capacity=200, departments="전체"),
    ])
    enr = pd.DataFrame([dict(student_id=s, course_code=c) for s, c in [
        ("S1", "A1"), ("S1", "A2"), ("S1", "B1"), ("S1", "B2"),
        ("S2", "A1"), ("S2", "B1"),
        ("S3", "A2"), ("S3", "B2"),
        ("S4", "A1"), ("S4", "A2"), ("S4", "B1"),
    ]])
    cnt = enr.groupby("course_code").size()
    courses["enrollment"] = courses["course_code"].map(lambda c: int(cnt.get(c, 0)))
    return Dataset(students, courses, profs, rooms, enr)


@pytest.fixture
def tiny():
    return tiny_dataset()


@pytest.fixture(scope="session")
def default_data():
    return generate()


@pytest.fixture(scope="session")
def default_result(default_data):
    return solve(default_data, Settings())


@pytest.fixture(scope="session")
def small_data():
    return generate(GenConfig(n_students=150, n_courses=20, n_professors=12, n_rooms=20, seed=3))
