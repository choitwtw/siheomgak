"""학생 화면: 학번 입력 → 시험 주간 캘린더(정규 수업 + 시험) + 알림함."""
from __future__ import annotations

import html

import streamlit as st

from core.config import DAYS, EXAM_NONE, EXAM_TYPE_LABEL
from core.timeutil import min_to_hm
from ui import state
from ui.style import badge, hero

S = st.session_state
ds = S.ds
state.ensure_schedule()

hero("STUDENT", "학생 화면", "내 시험 주간 시간표와 시험 확정 알림을 확인합니다.")

sids = list(ds.students["student_id"])
# 알림이 있는 학생을 먼저 보여 주면 시연이 편하다
noti_sids = list(dict.fromkeys(n["student_id"] for n in reversed(S.notifications)))
default = S.get("student_id") or (noti_sids[0] if noti_sids else sids[0])

c1, c2 = st.columns([1, 1.3])
typed = c1.text_input("학번 입력", value=default, placeholder="예: 2025010001")
quick = c2.selectbox("또는 목록에서 선택", ["(직접 입력)"] + (noti_sids[:30] if noti_sids else []) + sids[:200],
                     format_func=lambda x: x if x == "(직접 입력)" else
                     f"{x} · {ds.students.set_index('student_id').loc[x, 'name']}"
                     + (" 🔔" if x in noti_sids else ""))
sid = quick if quick != "(직접 입력)" else typed.strip()
if sid not in ds.courses_of:
    st.error(f"학번 '{sid}'을(를) 찾을 수 없습니다. 학번을 다시 확인해 주세요.")
    st.stop()
S.student_id = sid
stu = ds.students.set_index("student_id").loc[sid]

cm, rm = ds.course_map, ds.room_map
codes = ds.courses_of[sid]
sched = S.schedule.set_index("course_code") if S.schedule is not None else None
my_notis = [n for n in S.notifications if n["student_id"] == sid]
unread = sum(not n["read"] for n in my_notis)

# ---- 프로필 + 알림함 ----
p, nbox = st.columns([1, 1.6], gap="large")
with p:
    with st.container(border=True):
        extra = []
        if stu["double_major"]:
            extra.append(f"복수전공 {stu['double_major']}")
        if stu["minor"]:
            extra.append(f"부전공 {stu['minor']}")
        st.markdown(
            f"<div class='sg-big'>{html.escape(stu['name'])}</div>"
            f"<div class='sg-muted'>{sid} · {stu['major']} {stu['grade']}학년"
            f"{' · ' + ' · '.join(extra) if extra else ''}</div>", unsafe_allow_html=True)
        st.write("")
        n_exam = sum(cm[c].exam_type != EXAM_NONE for c in codes)
        n_conf = sum(c in S.confirmed for c in codes)
        st.markdown(f"수강 {len(codes)}과목 · 시험 {n_exam}과목 · "
                    f"{badge(f'확정 {n_conf}', 'ok')}{badge(f'미확정 {n_exam - n_conf}', 'gray')}",
                    unsafe_allow_html=True)
with nbox:
    with st.container(border=True):
        h1, h2 = st.columns([3, 1])
        h1.markdown(f"#### 🔔 알림함 {badge(f'새 알림 {unread}', 'danger') if unread else ''}", unsafe_allow_html=True)
        if unread and h2.button("모두 읽음", width="stretch"):
            for n in S.notifications:
                if n["student_id"] == sid:
                    n["read"] = True
            st.rerun()
        if not my_notis:
            st.markdown("<div class='sg-muted'>아직 알림이 없습니다. 교수가 시험을 확정하면 여기에 알림이 옵니다.</div>",
                        unsafe_allow_html=True)
        for n in reversed(my_notis[-8:]):
            st.markdown(
                f"<div class='sg-notice {'unread' if not n['read'] else ''}'><div class='ic'>📌</div>"
                f"<div><div class='t'>{html.escape(n['text'])}</div><div class='m'>{n['time']} · 시험각 알림"
                f"{' · 새 알림' if not n['read'] else ''}</div></div></div>", unsafe_allow_html=True)

# ---- 주간 캘린더 ----
st.write("")
with st.container(border=True):
    t1, t2 = st.columns([3, 1.3])
    t1.markdown(f"#### 시험 주간 시간표 · {S.settings.date_label(0)} ~ {S.settings.date_label(4)}")
    show_tent = t2.toggle("미확정 시험도 보기", value=True, help="교수가 아직 확정하지 않은 추천 일정을 점선으로 표시합니다.")

    events = []   # (day, start, end, kind, title, sub)
    for code in codes:
        c = cm[code]
        if c.exam_type == EXAM_NONE:
            for d, s, e in c.class_blocks():
                events.append((d, s, e, "class", c.name, f"정규 수업 · {c.room}"))
        elif sched is not None and code in sched.index:
            r = sched.loc[code]
            confirmed = code in S.confirmed
            if not confirmed and not show_tent:
                continue
            kind = "exam" if confirmed else "tentative"
            label = "확정" if confirmed else "미확정"
            events.append((int(r.day), int(r.start), int(r.end), kind, c.name,
                           f"{label} · {min_to_hm(r.start)}~{min_to_hm(r.end)} · {r.room_id}"))

    st_, en_ = S.settings.day_start, S.settings.day_end
    st_ = min([st_] + [e[1] for e in events])
    en_ = max([en_] + [e[2] for e in events])
    px_per_min = 1.15
    height = int((en_ - st_) * px_per_min) + 12
    ticks = "".join(
        f"<div class='tick' style='top:{int((m - st_) * px_per_min)}px'>{min_to_hm(m)}</div>"
        for m in range((st_ // 60 + (st_ % 60 > 0)) * 60, en_ + 1, 60))
    lines = "".join(f"<div class='line' style='top:{int((m - st_) * px_per_min)}px'></div>"
                    for m in range((st_ // 60 + (st_ % 60 > 0)) * 60, en_ + 1, 60))
    cols_html = []
    for d in range(5):
        evs = []
        for (dd, s, e, kind, title, sub) in events:
            if dd != d:
                continue
            top = int((s - st_) * px_per_min)
            h = max(int((e - s) * px_per_min) - 3, 26)
            evs.append(f"<div class='ev {kind}' style='top:{top}px;height:{h}px'><b>{html.escape(title)}</b>"
                       f"{html.escape(sub)}</div>")
        cols_html.append(f"<div class='col' style='height:{height}px'>{lines}{''.join(evs)}</div>")
    head = "<div class='hd'></div>" + "".join(
        f"<div class='hd'>{DAYS[d]}<small>{S.settings.date_of(d).month}/{S.settings.date_of(d).day}</small></div>"
        for d in range(5))
    st.markdown(
        f"<div class='sg-legend' style='margin-bottom:10px'>"
        f"<span><i style='background:#1C2E5A'></i>확정 시험</span>"
        f"<span><i style='background:#EEF2FF;border:1.5px dashed #3B5BDB'></i>미확정(추천) 시험</span>"
        f"<span><i style='background:#E9ECF2;border:1px solid #D8DDE8'></i>정규 수업(시험 없음 과목)</span></div>"
        f"<div class='sg-cal'>{head}<div class='times' style='height:{height}px'>{ticks}</div>{''.join(cols_html)}</div>",
        unsafe_allow_html=True)

# ---- 목록 ----
with st.expander("내 과목별 시험 정보", expanded=False):
    rows = []
    for code in codes:
        c = cm[code]
        if c.exam_type == EXAM_NONE:
            rows.append({"과목": c.name, "방식": EXAM_TYPE_LABEL[c.exam_type], "일시": "-", "강의실": "-", "상태": "시험 없음"})
            continue
        if sched is None or code not in sched.index:
            continue
        r = sched.loc[code]
        rows.append({"과목": c.name, "방식": EXAM_TYPE_LABEL[c.exam_type],
                     "일시": state.slot_text(int(r.day), int(r.start), int(r.end)),
                     "강의실": r.room_id, "상태": "확정" if code in S.confirmed else "미확정"})
    st.dataframe(rows, hide_index=True, width="stretch")
