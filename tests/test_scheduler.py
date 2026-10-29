import time

from core.constraints import validate_request
from core.scheduler import Assignment, solve
from core.settings import Settings
from core.timeutil import hm_to_min as H
from core.validator import validate

ST = Settings()


def test_default_data_zero_hard_violations(default_data, default_result):
    r = default_result
    assert r.ok, r.messages
    assert r.solve_time <= 25
    rep = validate(default_data, r.schedule, ST)
    assert rep.hard_count == 0, rep.violations[:5]
    # 무작위(수작업) 배정보다 확실히 좋아야 한다
    from core.baseline import baseline_metrics
    base = baseline_metrics(default_data, ST, runs=5)
    assert rep.metrics["students_3plus"] < base["students_3plus"]
    assert base["conflict_students"] > 0 == rep.metrics["conflict_students"]


def test_tiny_solution_is_valid(tiny):
    r = solve(tiny, ST)
    assert r.ok
    assert validate(tiny, r.schedule, ST).hard_count == 0
    # 교수1 금요일 불가
    assert not ((r.schedule["course_code"].isin(["A1", "A2"])) & (r.schedule["day"] == 4)).any()


def test_request_is_respected(small_data):
    r0 = solve(small_data, ST)
    assert r0.ok
    row = r0.schedule[r0.schedule.exam_type == "별도"].iloc[0]
    code, day = row.course_code, int(row.day)
    req = {code: validate_request({
        "unavailable": [{"day": "월화수목금"[day], "start": "09:00", "end": "18:00"}],
        "preferred": [{"day": None, "start": "09:00", "end": "12:00"}],
    })}
    r1 = solve(small_data, ST, requests=req, previous=r0.schedule, focus={code})
    assert r1.ok
    new = r1.schedule.set_index("course_code").loc[code]
    assert int(new.day) != day
    assert validate(small_data, r1.schedule, ST, requests=req).hard_count == 0


def test_confirmed_exam_never_moves(small_data):
    r0 = solve(small_data, ST)
    row = r0.schedule[r0.schedule.exam_type == "별도"].iloc[0]
    conf = {row.course_code: Assignment(int(row.day), int(row.start), row.room_id)}
    # 확정 과목에 반대되는 요청이 있어도 확정이 우선 (요청은 다른 과목에)
    other = r0.schedule[r0.schedule.exam_type == "별도"].iloc[1]
    req = {other.course_code: validate_request({"unavailable": [{"day": "월화수목금"[int(other.day)],
                                                                  "start": "09:00", "end": "18:00"}]})}
    r1 = solve(small_data, ST, requests=req, confirmed=conf, previous=r0.schedule, focus={other.course_code})
    assert r1.ok
    new = r1.schedule.set_index("course_code").loc[row.course_code]
    assert (int(new.day), int(new.start), new.room_id) == (int(row.day), int(row.start), row.room_id)
    assert validate(small_data, r1.schedule, ST, requests=req, confirmed=conf).hard_count == 0


def test_duration_change(tiny):
    ds = tiny.with_course_update("A1", exam_minutes=120)
    r = solve(ds, ST)
    a1 = r.schedule.set_index("course_code").loc["A1"]
    assert int(a1.end) - int(a1.start) == 120


def test_infeasible_reports_reason_in_korean(tiny):
    # A1을 월~목 전부 불가로 → 교수1 금요일 불가와 합쳐 가능한 시간 없음
    req = {"A1": validate_request({"unavailable": [{"day": d, "start": "09:00", "end": "18:00"} for d in "월화수목"]})}
    r = solve(tiny, ST, requests=req)
    assert not r.ok and r.status == "해 없음"
    text = " ".join(r.messages)
    assert "A1" in text and "가능한 시험 시간이 하나도 없습니다" in text and "교수" in text


def test_infeasible_room_reason(tiny):
    req = {"A1": validate_request({"room": {"min_capacity": 500, "building": None, "room_ids": []}})}
    r = solve(tiny, ST, requests=req)
    assert not r.ok and any("강의실이 없습니다" in m for m in r.messages)


def test_infeasible_pairwise_diagnosis(tiny):
    # A1 과 A2 (같은 교수, 같은 학생)를 둘 다 수요일 09:00-10:30 에만 허용 → 서로 겹쳐 불가
    allow = {"allowed": [{"day": "수", "start": "09:00", "end": "10:30"}]}
    req = {"A1": validate_request(allow), "A2": validate_request(allow)}
    r = solve(tiny, ST, requests=req)
    assert not r.ok
    assert any("교수님이 추가한 조건" in m for m in r.messages)


def test_priority_department_wins_contested_slot():
    """물리학과·수학과 과목이 같은 시간(수 09:00)·같은 강의실을 원할 때, 그 학기 우선순위가 높은 학과가 가져간다."""
    import pandas as pd
    from core.dataset import Dataset
    st_ = pd.DataFrame([dict(student_id=f"S{i}", name="학생", major="물리학과", grade=2, double_major="", minor="")
                        for i in range(4)])
    co = pd.DataFrame([
        dict(course_code="X", course_name="물리X", department="물리학과", target_grades="2", professor_id="PX",
             class_days="월", class_start="09:00", class_end="10:15", class_room="R1", enrollment=2,
             exam_type="별도", exam_minutes=90),
        dict(course_code="Y", course_name="수학Y", department="수학과", target_grades="2", professor_id="PY",
             class_days="화", class_start="09:00", class_end="10:15", class_room="R1", enrollment=2,
             exam_type="별도", exam_minutes=90),
    ])
    pr = pd.DataFrame([
        dict(professor_id="PX", name="갑", department="물리학과", courses="X", unavailable="", preferred="수 09:00-10:30"),
        dict(professor_id="PY", name="을", department="수학과", courses="Y", unavailable="", preferred="수 09:00-10:30"),
    ])
    ro = pd.DataFrame([dict(room_id="R1", building="이과대학", room_no="101", capacity=30, departments="전체")])
    en = pd.DataFrame([dict(student_id=s, course_code=c) for s, c in [("S0", "X"), ("S1", "X"), ("S2", "Y"), ("S3", "Y")]])
    ds = Dataset(st_, co, pr, ro, en)
    for sem, winner in (("26-1", "X"), ("26-2", "Y")):   # 26-1 물리 1순위, 26-2 수학 1순위(물리 6순위)
        r = solve(ds, Settings(semester=sem))
        s = r.schedule.set_index("course_code")
        got = [c for c in ("X", "Y") if int(s.loc[c, "day"]) == 2 and int(s.loc[c, "start"]) == H("09:00")]
        assert got == [winner], (sem, s)


def test_time_limit_respected(small_data):
    st = Settings(time_limit=3)
    t = time.time()
    r = solve(small_data, st)
    assert time.time() - t < 15 and r.ok
