"""앱 전체 실행 테스트 (Streamlit AppTest)."""
import os

from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def test_app_recovers_from_old_session_state():
    """새 버전이 배포될 때 열려 있던 탭에는 옛 구조의 세션 상태가 남아 있다.
    이때도 오류 없이 새 상태로 다시 시작해야 한다 (배포 직후 AttributeError 재발 방지)."""
    at = AppTest.from_file(APP, default_timeout=120)

    class OldSettings:          # 옛 버전 설정 객체 (period_label 등 새 기능 없음)
        semester = "26-2"

    at.session_state["ds"] = object()
    at.session_state["settings"] = OldSettings()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert type(at.session_state["settings"]).__name__ == "Settings"


def test_first_solve_shared_between_sessions():
    """조건 없는 첫 배정은 세션끼리 공유하고, 데이터가 바뀌면 다시 푼다"""
    from core.datagen import generate
    from core.settings import Settings
    from ui import state
    ds = generate()
    key = (state._fingerprint(ds), __import__("dataclasses").astuple(Settings()))
    r1 = state._shared_first_solve(key, ds, Settings())
    r2 = state._shared_first_solve(key, ds, Settings())
    assert r1 is r2 and r1.ok
    first = ds.courses.iloc[0]
    changed = ds.with_course_update(first.course_code, exam_minutes=int(first.exam_minutes) + 15)
    assert state._fingerprint(changed) != state._fingerprint(ds)


def test_minutes_text():
    from core.timeutil import minutes_text
    assert minutes_text(60) == "1시간"
    assert minutes_text(90) == "1시간 30분"
    assert minutes_text(135) == "2시간 15분"
    assert minutes_text(45) == "45분"


def run(at):
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_professor_sets_exam_duration_with_buttons():
    """교수 화면 ② 시험 시간 버튼: 고르면 저장 전 미리 보기, 저장하면 시험 시간과 일정 길이가 바뀌고, 되돌리기로 원래대로"""
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    at.switch_page("views/professor.py")
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    code = at.session_state["avail_code"]
    ds = at.session_state["ds"]
    c = ds.course_map[code]
    assert c.exam_type == "별도"                     # 기본 데이터 첫 교수의 첫 과목 (별도 시험)
    before = c.exam_minutes
    new = 60 if before != 60 else 90
    at.session_state[f"dur_{code}"] = new
    run(at)
    texts = " ".join(m.value for m in at.markdown)
    assert "바꾸려고 합니다" in texts and "아직 저장하지 않았습니다" in texts
    assert at.session_state["ds"].course_map[code].exam_minutes == before      # 저장 전에는 데이터 그대로
    save = [b for b in at.button if b.key in (f"save_dur_{code}", f"auto_dur_{code}")]
    assert save, "저장 또는 자동 찾기 버튼이 있어야 한다"
    save[0].click()
    run(at)
    assert at.session_state["ds"].course_map[code].exam_minutes == new
    row = at.session_state["schedule"].set_index("course_code").loc[code]
    assert int(row.end) - int(row.start) == new
    assert at.session_state["report"] is None or at.session_state["report"].metrics["hard_violations"] == 0
    undo = [b for b in at.button if b.key == f"undo_{code}"]
    undo[0].click()
    run(at)
    assert at.session_state["ds"].course_map[code].exam_minutes == before


def test_student_timetable_shows_expected_then_confirmed():
    """학생 화면: 교수 확정 전에는 '예상', 확정하면 같은 시험이 '확정'으로 시간표에 표시된다"""
    from core.scheduler import Assignment
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    at.switch_page("views/student.py")
    run(at)
    sid = at.session_state["student_id"]
    ds = at.session_state["ds"]
    code = next(c for c in ds.courses_of[sid] if ds.course_map[c].exam_type != "없음")
    name = ds.course_map[code].name
    html_all = lambda: " ".join(m.value for m in at.markdown)   # noqa: E731
    assert f"{name} 시험</b>예상" in html_all()
    row = at.session_state["schedule"].set_index("course_code").loc[code]
    at.session_state["confirmed"][code] = Assignment(int(row.day), int(row.start), str(row.room_id))
    run(at)
    assert f"{name} 시험 ✔</b>확정" in html_all()
