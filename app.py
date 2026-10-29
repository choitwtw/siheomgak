"""시험각 — 충돌 없는 시험 일정·강의실 자동 배정

실행: streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="시험각 · 시험 일정 자동 배정", page_icon="📅", layout="wide",
                   initial_sidebar_state="expanded")

from core import llm  # noqa: E402
from core.priority import semester_label  # noqa: E402
from ui import state  # noqa: E402
from ui import calendar  # noqa: E402
from ui.style import inject_css, mode_indicator  # noqa: E402

state.init_state()
inject_css()
calendar.inject()

pages = [
    st.Page("views/admin.py", title="관리자 대시보드", icon=":material/space_dashboard:", default=True),
    st.Page("views/professor.py", title="교수 화면", icon=":material/school:"),
    st.Page("views/student.py", title="학생 화면", icon=":material/person:"),
    st.Page("views/rooms.py", title="강의실 현황", icon=":material/meeting_room:"),
]
nav = st.navigation(pages)

with st.sidebar:
    s = st.session_state
    st.markdown("<div style='font-size:1.45rem;font-weight:800;letter-spacing:-.02em'>📅 시험각</div>"
                "<div style='opacity:.7;font-size:.82rem;margin-bottom:4px'>충돌 없는 시험 일정 자동 배정</div>",
                unsafe_allow_html=True)
    if s.schedule is None:
        status = "처음 화면을 열면 자동 배정"
    else:
        status = f"확정 {len(s.confirmed)}건 · " + ("발표 완료" if s.published_at else "발표 전")
    st.markdown(
        f"<div class='sg-side-card'><b>{semester_label(s.settings.semester)}</b><br>"
        f"시험 기간 {s.settings.period_label()}<br>"
        f"<span style='opacity:.75'>{s.ds.meta.get('source', '-')} · 과목 {len(s.ds.courses)} · 학생 {len(s.ds.students)}"
        f"<br>{status}</span></div>", unsafe_allow_html=True)

label, ok = llm.status()
mode_indicator(label, ok)
nav.run()
