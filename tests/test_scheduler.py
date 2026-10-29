import time
from datetime import date

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
    fri = [k for k in range(ST.n_days) if ST.weekday(k) == 4]
    assert not ((r.schedule["course_code"].isin(["A1", "A2"])) & (r.schedule["day"].isin(fri))).any()


def test_request_is_respected(small_data):
    r0 = solve(small_data, ST)
    assert r0.ok
    row = r0.schedule[r0.schedule.exam_type == "별도"].iloc[0]
    code, day = row.course_code, int(row.day)
    req = {code: validate_request({
        "unavailable": [{"day": ST.day_name(day), "start": "09:00", "end": "18:00"}],
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
    req = {other.course_code: validate_request({"unavailable": [{"day": ST.day_name(int(other.day)),
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
        r = solve(ds, Settings(semester=sem, exam_start=date(2026, 12, 14), exam_end=date(2026, 12, 18)))
        s = r.schedule.set_index("course_code")
        got = [c for c in ("X", "Y") if int(s.loc[c, "day"]) == 2 and int(s.loc[c, "start"]) == H("09:00")]
        assert got == [winner], (sem, s)


def test_time_limit_respected(small_data):
    st = Settings(time_limit=3)
    t = time.time()
    r = solve(small_data, st)
    assert time.time() - t < 15 and r.ok


def test_exam_period_dates():
    """기본 시험 기간 12/15(화)~12/21(월), 주말 제외 → 화 수 목 금 월 5일"""
    st = Settings()
    assert [d.isoformat() for d in st.exam_dates] == ["2026-12-15", "2026-12-16", "2026-12-17", "2026-12-18", "2026-12-21"]
    assert [st.day_name(k) for k in range(st.n_days)] == ["화", "수", "목", "금", "월"]
    assert st.date_label(4) == "12월 21일(월)"
    assert Settings(include_weekends=True).n_days == 7


def test_schedule_respects_weekday_mapping(default_data, default_result):
    """수업시간 시험은 그 과목 수업 요일에 해당하는 시험일에만 놓인다 (예: 월·수 수업 → 12/21(월) 또는 12/16(수))"""
    st = Settings()
    s = default_result.schedule.set_index("course_code")
    for c in default_data.course_map.values():
        if c.exam_type == "수업시간":
            assert st.weekday(int(s.loc[c.code, "day"])) in c.days


def test_general_courses_block_exam_times(default_data, default_result):
    """교양 수업 시간에는 그 교양을 듣는 학생의 시험이 잡히지 않는다"""
    st = Settings()
    cm = default_data.course_map
    s = default_result.schedule.set_index("course_code")
    gens = [c for c in cm.values() if c.dept == "교양"]
    assert gens
    for g in gens:
        blocks = st.class_blocks(g)
        for sid in default_data.students_of[g.code]:
            for code in default_data.courses_of[sid]:
                if code in s.index:
                    r = s.loc[code]
                    assert not any(int(r.day) == d and int(r.start) < e and b < int(r.end) for d, b, e in blocks)


def test_room_timetable_has_no_overlap(default_data, default_result):
    from ui.tables import room_timetable
    st = Settings()
    rt = room_timetable(default_data, default_result.schedule, st, {})
    for (_room, _day), g in rt.groupby(["강의실", "day_idx"]):
        g = g.sort_values("start_min")
        assert (g["start_min"].iloc[1:].values >= g["end_min"].iloc[:-1].values).all()
    assert set(rt[rt["종류"] == "시험"]["과목코드"]) == set(default_result.schedule.course_code)


def test_availability_fixed_only_shows_more_options(default_data, default_result):
    """확정된 일정만 기준으로 보면, 다른 과목의 미확정 추천안까지 막을 때보다 가능한 시각이 같거나 많다"""
    from core.explain import slot_map
    st = Settings()
    for code in list(default_result.schedule.course_code)[:6]:
        loose = [x for x in slot_map(default_data, default_result.schedule, st, {}, code, fixed_only=True) if x["status"] != "blocked"]
        tight = [x for x in slot_map(default_data, default_result.schedule, st, {}, code) if x["status"] != "blocked"]
        assert len(loose) >= len(tight) >= 1     # 현재 배정 시각은 항상 가능


def test_separate_exams_fit_exam_seats(default_data, default_result):
    """별도 시험은 시험 좌석(띄어 앉기 기준)이 수강인원 이상인 강의실에 배정된다"""
    rm = default_data.room_map
    for r in default_result.schedule.itertuples(index=False):
        c = default_data.course_map[r.course_code]
        if c.exam_type == "별도":
            assert rm[r.room_id].exam_capacity >= c.enrollment, (c.code, r.room_id)
    assert all(0 < x.exam_capacity <= x.capacity for x in rm.values())


def test_move_request_to_exact_slot_and_room(small_data):
    """교수가 시간표에서 끌어다 놓은 시각·강의실(이 시간에만 + 강의실 지정)이 그대로 반영된다"""
    from core.explain import slot_map
    r0 = solve(small_data, ST)
    code = r0.schedule[r0.schedule.exam_type == "별도"].iloc[0].course_code
    cur = r0.schedule.set_index("course_code").loc[code]
    cands = [x for x in slot_map(small_data, r0.schedule, ST, {}, code, fixed_only=True)
             if x["status"] != "blocked" and (x["day"], x["start"]) != (int(cur.day), int(cur.start))]
    x = cands[0]
    room = x["rooms"][-1]["rid"]
    req = {code: validate_request({"allowed": [{"day": ST.day_name(x["day"]), "start": H_(x["start"]), "end": H_(x["end"])}],
                                   "room": {"min_capacity": None, "building": None, "room_ids": [room]}})}
    r1 = solve(small_data, ST, requests=req, previous=r0.schedule, focus={code})
    assert r1.ok, r1.messages
    new = r1.schedule.set_index("course_code").loc[code]
    assert (int(new.day), int(new.start), new.room_id) == (x["day"], x["start"], room)
    assert validate(small_data, r1.schedule, ST, requests=req).hard_count == 0


def H_(m):
    from core.timeutil import min_to_hm
    return min_to_hm(m)
