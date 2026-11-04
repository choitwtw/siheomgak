"""학생 화면 — 학생을 고르면 시험 기간 시간표 하나만 보여 준다.

- 교수가 아직 확정하지 않은 시험: 현재 배정안을 '예상' 시간으로 (점선, 바뀔 수 있음)
- 교수가 확정한 시험: '확정' 시간으로 (남색)
- 시험 주간에는 수업이 없다. 다른 단과대 교양 과목만 그쪽 시험이 있을 수 있는 수업 시간을 회색으로 표시
관리자가 발표하면 받은 알림은 시간표 아래에 접어서 보여 준다.
"""
from __future__ import annotations

import html

import streamlit as st

from core.config import EXAM_NONE, GENERAL_DEPT
from core.timeutil import min_to_hm
from ui import state
from ui.calendar import legend, week_grid
from ui.style import NAVY, badge, hero

S = st.session_state
ds = S.ds
state.ensure_schedule()
stg = S.settings

st.markdown(f"""<style>
.sg-cal .ev {{ font-size:.85rem; }}
.sg-cal .ev b {{ font-size:.92rem; }}
.sg-cal .hd {{ font-size:1rem; }}
.sg-stu-status {{ font-size:1.12rem; margin:.4rem 0 .8rem; }}
.sg-stu-status b {{ color:{NAVY}; }}
.sg-exam-row {{ display:flex; align-items:center; gap:12px; padding:10px 4px; border-bottom:1px solid #EEF0F5; font-size:1rem; }}
.sg-exam-row:last-child {{ border-bottom:none; }}
.sg-exam-row .nm {{ flex:1.3; font-weight:700; }}
.sg-exam-row .wh {{ flex:2; }}
.sg-exam-row .wh.tent {{ color:#4A5265; }}
</style>""", unsafe_allow_html=True)

hero("STUDENT", "학생 화면", "내 시험 시간표를 확인합니다. 교수님이 확정하기 전에는 예상 시간이, 확정하면 확정 시간이 표시됩니다.")

# ---- 학생 선택 (학번이나 이름을 입력하면 목록이 좁혀진다) ----
students = ds.students.set_index("student_id")
sids = list(students.index)
noti_sids = list(dict.fromkeys(n["student_id"] for n in reversed(S.notifications)))
default = S.get("student_id") if S.get("student_id") in sids else (noti_sids[0] if noti_sids else sids[0])
sid = st.selectbox("학번 또는 이름 (입력하면 찾아 줍니다)", sids, index=sids.index(default),
                   format_func=lambda x: f"{x} · {students.at[x, 'name']} ({students.at[x, 'major']} {students.at[x, 'grade']}학년)")
S.student_id = sid

cm = ds.course_map
codes = sorted(ds.courses_of[sid], key=lambda c: (cm[c].dept == GENERAL_DEPT, c))
sched = S.schedule.set_index("course_code") if S.schedule is not None else None
exam_codes = [c for c in codes if cm[c].exam_type != EXAM_NONE and sched is not None and c in sched.index]
n_conf = sum(c in S.confirmed for c in exam_codes)

if not exam_codes:
    msg = "시험이 있는 과목이 없습니다."
elif n_conf == len(exam_codes):
    msg = f"시험 <b>{len(exam_codes)}과목</b>이 모두 <b>확정</b>되었습니다."
else:
    msg = (f"시험 <b>{len(exam_codes)}과목</b> 중 <b>{n_conf}과목 확정</b>, {len(exam_codes) - n_conf}과목은 아직 "
           "<b>예상</b> 시간입니다. 교수님이 확정하면 이 화면에 확정 시간이 표시됩니다.")
st.markdown(f"<div class='sg-stu-status'>{msg}</div>", unsafe_allow_html=True)

# ---- 시험 기간 시간표 ----
events, rows = [], []
for code in codes:
    c = cm[code]
    if c.exam_type == EXAM_NONE:
        label = "다른 단과대 교양 (그쪽 시험 시간일 수 있음)" if c.dept == GENERAL_DEPT else "정규 수업"
        for d, s0, e0 in stg.class_blocks(c):
            events.append(dict(day=d, start=s0, end=e0, cls="general" if c.dept == GENERAL_DEPT else "class",
                               title=c.name, sub=f"{label} · {c.room}"))
        continue
    if sched is None or code not in sched.index:
        continue
    r = sched.loc[code]
    d, s0, e0 = int(r.day), int(r.start), int(r.end)
    room = state.room_text(str(r.room_id))
    conf = code in S.confirmed
    tag = "확정" if conf else "예상"
    events.append(dict(day=d, start=s0, end=e0, cls="exam" if conf else "tentative",
                       title=f"{c.name} 시험" + (" ✔" if conf else ""),
                       sub=f"{tag} · {min_to_hm(s0)}~{min_to_hm(e0)} · {room}"))
    rows.append((d, s0, c.name, conf, f"{stg.date_label(d)} {min_to_hm(s0)}~{min_to_hm(e0)}", room))

with st.container(border=True):
    st.markdown(f"#### 시험 기간 시간표 · {stg.period_label()}")
    st.markdown(legend([("background:#1C2E5A", "확정된 시험"),
                        ("background:#EEF2FF;border:1.5px dashed #3B5BDB", "예상 시험 (교수 확정 전, 바뀔 수 있음)"),
                        ("background:#F4F4F6;border:1px solid #DDDFE5", "다른 단과대 교양 수업 시간")]),
                unsafe_allow_html=True)
    st.markdown(week_grid(stg, events, px_per_min=1.2, min_event_px=34), unsafe_allow_html=True)

    if rows:
        st.write("")
        st.markdown("".join(
            f"<div class='sg-exam-row'><span class='nm'>{html.escape(nm)}</span>"
            f"{badge('확정', 'ok') if conf else badge('예상', 'gray')}"
            f"<span class='wh{'' if conf else ' tent'}'>{html.escape(when)} · {html.escape(room)}</span></div>"
            for _d, _s, nm, conf, when, room in sorted(rows)), unsafe_allow_html=True)

# ---- 알림 (관리자가 발표하면 도착) ----
my_notis = [n for n in S.notifications if n["student_id"] == sid]
if my_notis:
    unread = sum(not n["read"] for n in my_notis)
    with st.expander(f"🔔 알림 {len(my_notis)}건" + (f" (새 알림 {unread})" if unread else "")):
        for n in reversed(my_notis[-6:]):
            lines = "".join(f"<div class='m' style='color:#171C2B;font-size:.85rem'>· {html.escape(x)}</div>"
                            for x in n.get("lines", []))
            st.markdown(
                f"<div class='sg-notice {'unread' if not n['read'] else ''}'><div class='ic'>📌</div>"
                f"<div><div class='t'>[{html.escape(n.get('title', '알림'))}] {html.escape(n['text'])}</div>{lines}"
                f"<div class='m'>{n['time']}</div></div></div>", unsafe_allow_html=True)
        if unread and st.button("모두 읽음"):
            for n in S.notifications:
                if n["student_id"] == sid:
                    n["read"] = True
            st.rerun()
