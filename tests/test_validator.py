import pandas as pd

from core.scheduler import Assignment
from core.settings import Settings
from core.timeutil import hm_to_min as H
from core.validator import validate
from core.constraints import validate_request

from datetime import date

ST = Settings(exam_start=date(2026, 12, 14), exam_end=date(2026, 12, 18))   # 월~금 한 주 (날 번호 = 요일)


def sched(rows):
    return pd.DataFrame([dict(course_code=c, day=d, start=H(s), end=H(e), room_id=r, exam_type=t, locked=False)
                         for c, d, s, e, r, t in rows])


def good_rows():
    return [
        ("A1", 2, "09:00", "10:30", "R50", "별도"),
        ("A2", 3, "09:00", "10:00", "R30", "별도"),
        ("B1", 0, "13:30", "14:45", "R30", "수업시간"),
    ]


def test_clean_schedule_has_no_violation(tiny):
    rep = validate(tiny, sched(good_rows()), ST)
    assert rep.hard_count == 0, rep.violations


def test_detects_student_overlap(tiny):
    rows = good_rows()
    rows[1] = ("A2", 2, "10:00", "11:00", "R30", "별도")  # S1, S4 가 A1 과 겹침
    rep = validate(tiny, sched(rows), ST)
    assert rep.by_rule()["H1"] == 2
    assert rep.metrics["conflict_students"] == 2


def test_detects_overlap_with_running_class(tiny):
    rows = good_rows()
    rows[1] = ("A2", 1, "13:00", "14:00", "R30", "별도")  # B2(시험 없음) 화 13:30 수업과 겹침 (S1, S3)
    rep = validate(tiny, sched(rows), ST)
    assert rep.by_rule()["H1"] == 2


def test_detects_professor_rules(tiny):
    rows = good_rows()
    rows[0] = ("A1", 4, "09:00", "10:30", "R50", "별도")  # 교수1 금요일 불가
    rep = validate(tiny, sched(rows), ST)
    assert rep.by_rule()["H2"] == 1
    req = {"A2": validate_request({"unavailable": [{"day": "목", "start": "09:00", "end": "12:00"}]})}
    rep = validate(tiny, sched(good_rows()), ST, requests=req)
    assert rep.by_rule()["H2"] == 1


def test_detects_room_rules(tiny):
    rows = good_rows()
    rows[0] = ("A1", 2, "09:00", "10:30", "R30", "별도")  # 수강 3명이라 용량은 OK
    rows[1] = ("A2", 2, "10:00", "11:00", "R30", "별도")  # 같은 강의실 겹침 (+학생 겹침)
    rep = validate(tiny, sched(rows), ST)
    assert rep.by_rule()["H3"] >= 1
    small = tiny.rooms.copy()
    small.loc[small.room_id == "R30", "capacity"] = 1
    from core.dataset import Dataset
    ds2 = Dataset(tiny.students, tiny.courses, tiny.professors, small, tiny.enrollments)
    rep = validate(ds2, sched(good_rows()), ST)
    assert any("수용인원" in v["detail"] for v in rep.violations)


def test_detects_confirmed_change_and_missing(tiny):
    conf = {"A1": Assignment(2, H("09:00"), "R200")}
    rep = validate(tiny, sched(good_rows()), ST, confirmed=conf)
    assert rep.by_rule()["H4"] == 1
    rep = validate(tiny, sched(good_rows()[:2]), ST)  # B1 누락
    assert rep.by_rule()["H0"] == 1


def test_in_class_exam_must_be_regular_session(tiny):
    rows = good_rows()
    rows[2] = ("B1", 2, "13:30", "14:45", "R30", "수업시간")   # 수요일 회차 → 허용
    assert validate(tiny, sched(rows), ST).hard_count == 0
    rows[2] = ("B1", 2, "15:00", "16:15", "R30", "수업시간")   # 수업 시간 아님
    assert validate(tiny, sched(rows), ST).by_rule()["H0"] == 1


def test_quality_metrics(tiny):
    rows = [
        ("A1", 0, "09:00", "10:30", "R50", "별도"),
        ("A2", 0, "10:30", "11:30", "R30", "별도"),      # A1 종료 직후 → S1, S4 연속
        ("B1", 0, "13:30", "14:45", "R30", "수업시간"),  # S1, S4 월요일 3과목
    ]
    rep = validate(tiny, sched(rows), ST)
    assert rep.hard_count == 0
    assert rep.metrics["students_3plus"] == 2
    assert rep.metrics["consecutive_students"] == 2
