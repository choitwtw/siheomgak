"""학생 화면: 학번 입력 → 시험 기간 시간표(정규 수업 + 시험) · 과목별 시험 일정 전망 · 알림함.

발표 전: 수강 과목의 정규 수업 시간을 기준으로 한 '예상 시험 일자'와 현재 추천안을 보여 준다
        (수강신청 시간표는 서로 겹치지 않으므로, 수업시간에 시험을 보면 충돌이 없다).
발표 후: 확정된 시험 일정이 시간표에 표시되고 알림함으로 전송된다 (정정 기간에 참고).
"""
from __future__ import annotations

import html

import streamlit as st

from core.config import EXAM_IN_CLASS, EXAM_NONE, GENERAL_DEPT
from core.timeutil import min_to_hm
from ui import state
from ui.calendar import legend, week_grid
from ui.style import badge, hero
from ui.tables import type_label

S = st.session_state
ds = S.ds
state.ensure_schedule()
stg = S.settings

hero("STUDENT", "학생 화면", "내 시험 기간 시간표, 과목별 예상·확정 시험 일정, 시험 확정 알림을 확인합니다.")

sids = list(ds.students["student_id"])
noti_sids = list(dict.fromkeys(n["student_id"] for n in reversed(S.notifications)))
default = S.get("student_id") or (noti_sids[0] if noti_sids else sids[0])
names = ds.students.set_index("student_id")["name"]

c1, c2 = st.columns([1, 1.3])
typed = c1.text_input("학번 입력", value=default, placeholder="예: 2025010001")
quick = c2.selectbox("또는 목록에서 선택", ["(직접 입력)"] + (noti_sids[:30] if noti_sids else []) + sids[:200],
                     format_func=lambda x: x if x == "(직접 입력)" else f"{x} · {names[x]}" + (" 🔔" if x in noti_sids else ""))
sid = quick if quick != "(직접 입력)" else typed.strip()
if sid not in ds.courses_of:
    st.error(f"학번 '{sid}'을(를) 찾을 수 없습니다. 학번을 다시 확인해 주세요.")
    st.stop()
S.student_id = sid
stu = ds.students.set_index("student_id").loc[sid]

cm = ds.course_map
codes = sorted(ds.courses_of[sid], key=lambda c: (cm[c].dept == GENERAL_DEPT, c))
sched = S.schedule.set_index("course_code") if S.schedule is not None else None
exam_codes = [c for c in codes if cm[c].exam_type != EXAM_NONE]
pub_codes = [c for c in exam_codes if state.is_published(c)]
my_notis = [n for n in S.notifications if n["student_id"] == sid]
unread = sum(not n["read"] for n in my_notis)

# ---- 발표 상태 ----
if exam_codes and len(pub_codes) == len(exam_codes):
    st.success("📢 내 시험 일정이 모두 발표되었습니다. 수강 정정 기간에 아래 확정 일정을 참고하세요.")
elif pub_codes:
    st.info(f"📢 시험 {len(exam_codes)}과목 중 {len(pub_codes)}과목의 일정이 발표되었습니다. 나머지는 아직 예상 일정입니다.")
else:
    st.info("아직 시험 일정이 발표되지 않았습니다. 아래는 정규 수업 시간을 기준으로 한 **예상 시험 일자**와 현재 추천안입니다 "
            "(교수 확정 전이라 바뀔 수 있습니다).")

# ---- 프로필 + 알림함 ----
p, nbox = st.columns([1, 1.6], gap="large")
with p:
    with st.container(border=True):
        extra = []
        if stu["double_major"]:
            extra.append(f"복수전공 {stu['double_major']}")
        if stu["minor"]:
            extra.append(f"부전공 {stu['minor']}")
        st.markdown(f"<div class='sg-big'>{html.escape(stu['name'])}</div>"
                    f"<div class='sg-muted'>{sid} · {stu['major']} {stu['grade']}학년"
                    f"{' · ' + ' · '.join(extra) if extra else ''}</div>", unsafe_allow_html=True)
        st.write("")
        n_gen = sum(cm[c].dept == GENERAL_DEPT for c in codes)
        st.markdown(f"수강 {len(codes)}과목(교양 {n_gen}) · 시험 {len(exam_codes)}과목<br>"
                    f"{badge(f'발표 {len(pub_codes)}', 'ok')}{badge(f'미발표 {len(exam_codes) - len(pub_codes)}', 'gray')}",
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
            st.markdown("<div class='sg-muted'>아직 알림이 없습니다. 시험 일정이 발표되면 개인 알림(푸시)으로 이곳에 도착합니다.</div>",
                        unsafe_allow_html=True)
        for n in reversed(my_notis[-6:]):
            lines = "".join(f"<div class='m' style='color:#171C2B;font-size:.85rem'>· {html.escape(x)}</div>"
                            for x in n.get("lines", []))
            st.markdown(
                f"<div class='sg-notice {'unread' if not n['read'] else ''}'><div class='ic'>📌</div>"
                f"<div><div class='t'>[{html.escape(n.get('title', '알림'))}] {html.escape(n['text'])}</div>{lines}"
                f"<div class='m'>{n['time']} · 시험각 푸시 알림{' · 새 알림' if not n['read'] else ''}</div></div></div>",
                unsafe_allow_html=True)


def class_time_text(c) -> str:
    sess = stg.class_blocks(c)
    if not sess:
        return "시험 기간 중 수업 없음"
    return " 또는 ".join(stg.short_label(d) for d, _s, _e in sess) + f" {min_to_hm(c.start)}~{min_to_hm(c.end)}"


# ---- 시험 기간 시간표 ----
st.write("")
with st.container(border=True):
    t1, t2 = st.columns([2.2, 1.6])
    t1.markdown(f"#### 시험 기간 시간표 · {stg.period_label()}")
    view = t2.segmented_control("미발표 과목 표시", ["추천안", "수업시간 기준 예상"], default="추천안",
                                key="stu_view", help="발표 전 과목을 어떻게 보여 줄지 고릅니다.") or "추천안"
    events = []
    for code in codes:
        c = cm[code]
        if c.exam_type == EXAM_NONE:
            label = "교양 · 정규 수업" if c.dept == GENERAL_DEPT else "정규 수업(과제 대체 과목)"
            for d, s0, e0 in stg.class_blocks(c):
                events.append(dict(day=d, start=s0, end=e0, cls="general" if c.dept == GENERAL_DEPT else "class",
                                   title=c.name, sub=f"{label} · {c.room}"))
            continue
        if state.is_published(code):
            a = S.published[code]
            r = sched.loc[code] if sched is not None and code in sched.index else None
            end = int(r.end) if r is not None else a.start + c.exam_minutes
            events.append(dict(day=a.day, start=a.start, end=end, cls="exam", title=c.name + " 시험",
                               sub=f"확정 · {min_to_hm(a.start)}~{min_to_hm(end)} · {state.room_text(a.room)}"))
        elif view == "추천안" and sched is not None and code in sched.index:
            r = sched.loc[code]
            events.append(dict(day=int(r.day), start=int(r.start), end=int(r.end), cls="tentative", title=c.name,
                               sub=f"추천안(미확정) · {min_to_hm(r.start)}~{min_to_hm(r.end)} · {r.room_id}"))
        elif view != "추천안":
            for d, s0, e0 in stg.class_blocks(c):
                events.append(dict(day=d, start=s0, end=e0, cls="expected", title=c.name,
                                   sub="예상 · 수업시간 시험" if c.exam_type == EXAM_IN_CLASS else "예상 · 수업시간(별도 시험이라 바뀔 수 있음)"))
    items = [("background:#1C2E5A", "확정(발표된) 시험")]
    items.append(("background:#EEF2FF;border:1.5px dashed #3B5BDB", "추천안(미확정)") if view == "추천안"
                 else ("background:#F1F7FF;border:1.5px dashed #74A0E8", "수업시간 기준 예상"))
    items += [("background:#E9ECF2;border:1px solid #D8DDE8", "정규 수업(과제 대체 과목)"),
              ("background:#F4F4F6;border:1px solid #DDDFE5", "교양 수업")]
    st.markdown(legend(items), unsafe_allow_html=True)
    st.markdown(week_grid(stg, events), unsafe_allow_html=True)

# ---- 과목별 시험 일정 전망 ----
with st.container(border=True):
    st.markdown("#### 과목별 시험 일정 전망")
    st.caption("수강신청 시간표는 서로 겹치지 않으므로, 정규 수업 시간에 시험을 보면 내 다른 수업과 충돌하지 않습니다. "
               "그래서 발표 전에는 수업시간을 기준으로 예상 일자를 보여 드립니다.")
    rows = []
    for code in codes:
        c = cm[code]
        if c.exam_type == EXAM_NONE:
            rows.append({"과목": c.name, "구분": type_label(c), "상태": "시험 없음" if c.dept != GENERAL_DEPT else "다른 단과대 일정",
                         "수업시간 기준 예상": "-", "현재 추천안": "-", "확정 일정": "-"})
            continue
        rec = "-"
        if sched is not None and code in sched.index:
            r = sched.loc[code]
            rec = f"{stg.short_label(int(r.day))} {min_to_hm(r.start)}~{min_to_hm(r.end)} · {r.room_id}"
        fixed = "-"
        if state.is_published(code):
            a = S.published[code]
            fixed = f"{stg.date_label(a.day)} {min_to_hm(a.start)} · {state.room_text(a.room)}"
        status = "확정·발표" if state.is_published(code) else ("교수 확정(발표 전)" if code in S.confirmed else "미확정")
        rows.append({"과목": c.name, "구분": type_label(c), "상태": status,
                     "수업시간 기준 예상": class_time_text(c) + ("" if c.exam_type == EXAM_IN_CLASS else " (별도 시험·변동 가능)"),
                     "현재 추천안": rec, "확정 일정": fixed})
    st.dataframe(rows, hide_index=True, width="stretch",
                 column_config={"수업시간 기준 예상": st.column_config.TextColumn(width="large")})
