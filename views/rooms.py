"""강의실 현황: 요일별 강의실 점유 타임라인 (학과별 색상)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.config import DAYS, DEPARTMENTS, DEPT_COLORS, EXAM_NONE
from core.timeutil import min_to_hm
from ui import state
from ui.style import hero, metric_cards

S = st.session_state
ds = S.ds
state.ensure_schedule()

hero("ROOMS", "강의실 현황", "시험 주간 요일별 강의실 점유 현황입니다. 막대 색은 학과, 진한 막대는 시험, 옅은 막대는 진행 중인 정규 수업입니다.")

if S.schedule is None:
    st.warning("배정 결과가 없습니다. 관리자 대시보드에서 배정을 실행해 주세요.")
    st.stop()

cm, rm = ds.course_map, ds.room_map
items = []
for r in S.schedule.itertuples(index=False):
    c = cm[r.course_code]
    items.append(dict(day=int(r.day), start=int(r.start), end=int(r.end), room=r.room_id, code=c.code, name=c.name,
                      dept=c.dept, kind="시험", confirmed=r.course_code in S.confirmed, n=c.enrollment))
for c in cm.values():
    if c.exam_type == EXAM_NONE:
        for d, s, e in c.class_blocks():
            items.append(dict(day=d, start=s, end=e, room=c.room, code=c.code, name=c.name, dept=c.dept,
                              kind="정규 수업", confirmed=False, n=c.enrollment))
df = pd.DataFrame(items)

f1, f2 = st.columns([2, 1.2])
day = f1.segmented_control("요일", list(range(5)), default=S.get("room_day", 0),
                           format_func=lambda d: S.settings.date_label(d), key="room_day_sel")
day = 0 if day is None else day
S.room_day = day
buildings = sorted({r.building for r in rm.values()})
bsel = f2.multiselect("건물", buildings, placeholder="건물 전체")

# ---- 요약 ----
dd = df[df.day == day]
used_rooms = dd.room.nunique()
total_min = (S.settings.day_end - S.settings.day_start) * len(rm)
busy_min = int((dd.end - dd.start).sum())
metric_cards([
    dict(label=f"{DAYS[day]}요일 시험 수", value=int((dd.kind == "시험").sum()), unit="개", tone="info"),
    dict(label="사용 강의실", value=used_rooms, unit=f"/ {len(rm)}실", tone="info"),
    dict(label="강의실 시간 점유율", value=f"{100 * busy_min / total_min:.0f}" if total_min else "0", unit="%",
         tone="info", sub="전체 강의실 × 하루 시험 시간 대비"),
    dict(label="확정된 시험", value=int(dd.confirmed.sum()), unit="개", tone="ok"),
])

# ---- 타임라인 ----
rooms = [r for r in rm.values() if not bsel or r.building in bsel]
rooms.sort(key=lambda r: (r.building, -r.capacity, r.room_no))
room_labels = {r.rid: f"{r.rid} ({r.capacity}석)" for r in rooms}
show = dd[dd.room.isin(room_labels)]
only_used = st.toggle("사용 중인 강의실만 보기", value=True)
if only_used:
    rooms = [r for r in rooms if r.rid in set(show.room)]
order = [room_labels[r.rid] for r in rooms]

base = datetime(2000, 1, 1)
fig = go.Figure()
for dept in DEPARTMENTS:
    for kind in ("시험", "정규 수업"):
        sub = show[(show.dept == dept) & (show.kind == kind)]
        if sub.empty:
            continue
        fig.add_bar(
            name=f"{dept}" if kind == "시험" else f"{dept} (수업)",
            legendgroup=dept, showlegend=(kind == "시험"),
            y=[room_labels[r] for r in sub.room],
            x=[(e - s) * 60 * 1000 for s, e in zip(sub.start, sub.end)],
            base=[base + timedelta(minutes=int(s)) for s in sub.start],
            orientation="h",
            marker=dict(color=DEPT_COLORS[dept], opacity=1.0 if kind == "시험" else 0.35,
                        line=dict(color="white", width=2)),
            text=[f"{n}{' ✔' if cf else ''}" for n, cf in zip(sub.name, sub.confirmed)],
            textposition="inside", insidetextanchor="start",
            textfont=dict(color="white" if kind == "시험" else "#2A3042", size=12),
            customdata=list(zip(sub.code, sub.name, [min_to_hm(s) for s in sub.start],
                                [min_to_hm(e) for e in sub.end], sub.n, sub.kind,
                                ["확정" if c else ("미확정" if k == "시험" else "-") for c, k in zip(sub.confirmed, sub.kind)])),
            hovertemplate="<b>%{customdata[1]}</b> (%{customdata[0]})<br>%{customdata[5]} · %{customdata[2]}~%{customdata[3]}"
                          "<br>수강 %{customdata[4]}명 · %{customdata[6]}<br>%{y}<extra>" + dept + "</extra>",
        )
fig.update_layout(
    barmode="overlay", height=max(320, 34 * len(order) + 110), margin=dict(l=10, r=10, t=30, b=40),
    plot_bgcolor="white", paper_bgcolor="white", bargap=0.25,
    font=dict(family="Pretendard Variable, Pretendard, sans-serif", size=13),
    legend=dict(orientation="h", y=-0.02, yanchor="top", x=0, title_text=""),
    xaxis=dict(type="date", range=[base + timedelta(minutes=S.settings.day_start),
                                   base + timedelta(minutes=S.settings.day_end)],
               tickformat="%H:%M", dtick=3600 * 1000, gridcolor="#EEF0F5", side="top"),
    yaxis=dict(categoryorder="array", categoryarray=order[::-1], gridcolor="#F4F5F8", title=""),
    hoverlabel=dict(bgcolor="white", font_size=13),
)
with st.container(border=True):
    st.markdown(f"#### {S.settings.date_label(day)} 강의실 타임라인")
    if show.empty:
        st.info("이 날 사용 중인 강의실이 없습니다.")
    else:
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.caption("✔ 표시는 교수가 확정한 시험입니다. 막대에 마우스를 올리면 자세한 정보가 보입니다.")

# ---- 표 보기 ----
with st.expander("표로 보기"):
    t = show.sort_values(["room", "start"]).copy()
    t["시간"] = [f"{min_to_hm(s)}~{min_to_hm(e)}" for s, e in zip(t.start, t.end)]
    t["상태"] = ["확정" if c else ("미확정" if k == "시험" else "-") for c, k in zip(t.confirmed, t.kind)]
    st.dataframe(t[["room", "시간", "kind", "name", "dept", "n", "상태"]].rename(
        columns={"room": "강의실", "kind": "종류", "name": "과목", "dept": "학과", "n": "수강"}),
        hide_index=True, width="stretch")
