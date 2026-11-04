"""교수 화면 — 연로한 교수님도 쉽게 쓰도록 네 단계로 나눈 화면.

① 과목 고르기 → ② 시험 시간 정하기(버튼) → ③ 시간표에서 날짜·시간 고르기 → ④ 확인하고 확정하기.
시험 시간을 바꾸면 저장 전에도 시간표의 시험 블록 길이와 초록/빨강(가능/불가) 칸이 새 길이로 바로 다시 계산된다.
말로 조건 바꾸기(AI)·영향 분석·변경 전/후 비교는 아래 '더 많은 기능'에 둔다.
"""
from __future__ import annotations

import dataclasses
import html
import json

import pandas as pd
import streamlit as st

from core import llm
from core.config import (DAYS, EXAM_DURATION_BUTTONS, EXAM_IN_CLASS, EXAM_NONE, EXAM_SEPARATE, EXAM_TYPE_LABEL,
                         GENERAL_DEPT)
from core.constraints import CourseRequest, validate_request
from core.explain import (
    busy_map,
    course_facts,
    evaluate_slots,
    impact_facts,
    llm_impact,
    llm_reason,
    slot_map,
    template_impact,
    template_reason,
)
from core.nlparse import ParseContext, parse_request
from core.priority import dept_rank
from core.settings import NOTIFY_INSTANT
from core.timeutil import min_to_hm, minutes_text, windows_to_text
from ui import state
from ui.board import exam_board
from ui.calendar import legend
from ui.style import ACCENT, MUTED, NAVY, badge, hero, metric_cards, reason_box, warn_box

S = st.session_state
state.ensure_schedule()
ds = S.ds
S.setdefault("llm_cache", {})

# 교수 화면은 글자·버튼을 크게 (이 화면에서만 적용)
st.markdown(f"""<style>
.sg-step {{ display:flex; align-items:center; gap:14px; margin: 2rem 0 .7rem; }}
.sg-step .n {{ width:44px; height:44px; border-radius:50%; background:{NAVY}; color:#fff; font-weight:800; font-size:1.35rem;
              display:flex; align-items:center; justify-content:center; flex:none; }}
.sg-step .t {{ font-size:1.5rem; font-weight:800; letter-spacing:-.02em; }}
.sg-step .d {{ color:{MUTED}; font-size:1.02rem; margin-top:2px; }}
.sg-say {{ font-size:1.12rem; line-height:1.65; margin:.3rem 0 .6rem; }}
.sg-say b {{ color:{NAVY}; }}
.sg-dur {{ font-size:1.25rem; margin:.2rem 0 .8rem; }}
.sg-dur b {{ font-size:1.6rem; color:{NAVY}; }}
.sg-dur .new {{ color:{ACCENT}; }}
.stApp [data-testid="stMarkdownContainer"] p, .stApp [data-testid="stMarkdownContainer"] li {{ font-size:1.05rem; }}
.stApp .stButton > button {{ min-height:3rem; font-size:1.05rem; padding:.6rem 1.3rem; }}
.stApp [data-testid="stWidgetLabel"] p {{ font-size:1.05rem !important; font-weight:700; }}
.stApp [data-baseweb="select"] > div {{ min-height:3rem; font-size:1.08rem; }}
.sg-reason, .sg-warn {{ font-size:1.05rem !important; }}
</style>""", unsafe_allow_html=True)


def step(n: int, title: str, desc: str = ""):
    st.markdown(f"<div class='sg-step'><div class='n'>{n}</div><div><div class='t'>{html.escape(title)}</div>"
                f"<div class='d'>{html.escape(desc)}</div></div></div>", unsafe_allow_html=True)


def say(text_html: str):
    st.markdown(f"<div class='sg-say'>{text_html}</div>", unsafe_allow_html=True)


def button_row(options: list, current, key: str, fmt, state_key: str, disabled: bool = False, per_row: int = 6):
    """큰 버튼 한 줄로 고르기. 고른 것은 진한(primary) 버튼. 누르면 S[state_key] 에 값을 넣는다."""
    for i in range(0, len(options), per_row):
        part = options[i:i + per_row]
        cols = st.columns(per_row)
        for col, o in zip(cols, part):
            col.button(fmt(o), key=f"{key}_{o}", type="primary" if o == current else "secondary", width="stretch",
                       disabled=disabled, on_click=S.__setitem__, args=(state_key, o))


hero("PROFESSOR", "교수 화면",
     "① 과목을 고르고 ② 시험 시간을 정한 뒤 ③ 시간표에서 날짜·시간을 고르고 ④ 확정하면 끝납니다.")

if S.schedule is None:
    st.warning("배정 결과가 없습니다. 관리자 대시보드에서 배정을 실행해 주세요.")
    st.stop()

# ---------------------------------------------------------------------------
# 교수 선택 (로그인 대신)
# ---------------------------------------------------------------------------
rank = dept_rank(S.settings.semester)
pm = ds.prof_map
cm = ds.course_map
# 시험이 있는 과목을 맡은 교수만 (교양 강사 제외), 학과 우선순위 순
pids = sorted([p for p, cs in ds.prof_courses.items()
               if p in pm and pm[p].dept != GENERAL_DEPT and any(cm[c].exam_type != EXAM_NONE for c in cs)],
              key=lambda p: (rank.get(pm[p].dept, 99), p))
turn = state.current_turn()
if S.get("prof_id") not in pids:
    S.prof_id = next((p for p in pids if pm[p].dept == turn), pids[0])
lock = S.settings.priority_lock
pid = st.selectbox("교수님 성함", pids, index=pids.index(S.prof_id),
                   format_func=lambda p: f"{pm[p].name} 교수 · {pm[p].dept} ({rank.get(pm[p].dept)}순위)"
                   + ("  ← 지금 확정 차례" if pm[p].dept == turn and lock else ""))
S.prof_id = pid
prof = pm[pid]
my_codes = ds.prof_courses.get(pid, [])

info = [f"소속 {prof.dept} (이번 학기 우선순위 {rank.get(prof.dept)}위)"]
info.append("불가 시간: " + (windows_to_text(prof.unavailable) or "없음"))
info.append("선호 시간: " + (windows_to_text(prof.preferred) or "없음"))
st.markdown("<div class='sg-muted'>" + " · ".join(html.escape(x) for x in info) + "</div>", unsafe_allow_html=True)
if S.settings.priority_lock:
    if turn is None:
        st.success("모든 학과의 시험 확정이 끝났습니다. 관리자가 발표하면 학생에게 알림이 갑니다.")
    elif turn == prof.dept:
        st.success(f"지금은 **{prof.dept}**의 확정 차례입니다. 아래 순서대로 일정을 확인하고 확정해 주세요.")
    else:
        st.info(f"지금은 **{rank.get(turn)}순위 {turn}**의 확정 차례입니다. {prof.dept}는 상위 학과가 확정을 마친 뒤 "
                "확정할 수 있습니다. 그동안 시험 시간과 날짜를 미리 정해 두세요.")

use_ai = llm.available()
rep = state.current_report()
per_course = rep.per_course if rep else {}


def reason_text(facts: dict) -> tuple[str, str]:
    """(문장, 출처)"""
    base = template_reason(facts)
    if not use_ai or not facts.get("has_exam"):
        return base, "템플릿"
    key = json.dumps(facts, ensure_ascii=False, sort_keys=True)
    if key in S.llm_cache:
        return S.llm_cache[key], "AI"
    try:
        with st.spinner("AI가 배정 이유를 문장으로 정리하는 중…"):
            txt = llm_reason(facts)
        S.llm_cache[key] = txt
        return txt, "AI"
    except llm.LLMError:
        return base, "템플릿(AI 실패)"


def apply_request(code: str, req: CourseRequest, text: str, mode: str, targets: list[str] | None = None,
                  course_changes: dict | None = None) -> bool:
    """교수 요청을 반영해 다시 배정하고 변경 기록을 남긴다. 성공하면 True (실패 메시지는 S.move_error).
    course_changes: 과목 자체를 바꿀 때 (예: 수업시간 시험을 빈 시간으로 옮기며 '별도 시험'으로)."""
    targets = targets or [code]
    new_reqs = dict(S.requests)
    time_part = CourseRequest(unavailable=req.unavailable, allowed=req.allowed, preferred=req.preferred, avoid=req.avoid)
    for t in targets:
        merged = new_reqs.get(t, CourseRequest()).merged_with(req if t == code else time_part)
        merged.duration_minutes = None
        new_reqs[t] = merged
    changes = dict(course_changes or {})
    if req.duration_minutes:
        changes["exam_minutes"] = int(req.duration_minutes)
    new_ds = ds.with_course_update(code, **changes) if changes else ds
    before_sched, before_reqs, before_conf = S.schedule.copy(), dict(S.requests), dict(S.confirmed)
    before_metrics = dict(rep.metrics) if rep else {}
    with st.spinner("조건을 반영해 다시 배정하는 중… (다른 과목 일정은 최대한 유지)"):
        res = state.run_schedule(previous=before_sched, focus=set(targets), dataset=new_ds, requests=new_reqs)
    if not res.ok:
        S.move_error = (res.status, res.messages)
        return False
    S.change_log.append(dict(
        prof=pid, code=code, targets=targets, text=text, mode=mode, summary=req.summary,
        before=before_sched, after=S.schedule.copy(), before_metrics=before_metrics,
        after_metrics=dict(state.current_report().metrics), solve_time=res.solve_time,
        time=state.now_text(), confirmed=before_conf, before_reqs=before_reqs, before_minutes=cm[code].exam_minutes,
        before_course=dict(exam_type=cm[code].exam_type, exam_minutes=cm[code].exam_minutes)))
    S.pending.pop(code, None)
    return True


def undo(lg: dict):
    """마지막 변경을 되돌린다 (시험 시간을 바꿨다면 시험 시간도)."""
    S.schedule = lg["before"]
    S.change_log = [x for x in S.change_log if x is not lg]
    S.requests = dict(lg["before_reqs"])
    before = lg.get("before_course") or ({"exam_minutes": int(lg["before_minutes"])} if lg.get("before_minutes") else {})
    now = S.ds.course_map[lg["code"]]
    if any(getattr(now, k) != v for k, v in before.items()):       # 시험 시간·시험 방식도 원래대로
        S.ds = S.ds.with_course_update(lg["code"], **before)
    for t in lg["targets"]:
        S.pop(f"dur_{t}", None)          # 시험 시간 버튼도 저장된 값으로 되돌린다
    S.report = None


def show_move_error():
    err = S.pop("move_error", None)
    if err:
        st.error(f"**바꾸지 못했습니다 — {err[0]}**. 기존 일정은 그대로 유지됩니다.")
        for m in err[1]:
            st.markdown(f"- {m}")


def exam_len(c, minutes: int | None = None) -> int:
    """시험이 차지하는 시간(분). 수업시간 시험은 정규 수업 길이 이상."""
    m = c.exam_minutes if minutes is None else minutes
    return max(c.class_len, m) if c.exam_type == EXAM_IN_CLASS else m


exam_codes = [x for x in my_codes if cm[x].exam_type != EXAM_NONE]
no_exam = [x for x in my_codes if cm[x].exam_type == EXAM_NONE]
if not exam_codes:
    st.info("시험이 있는 담당 과목이 없습니다.")
    st.stop()

# ---------------------------------------------------------------------------
# ① 과목 고르기
# ---------------------------------------------------------------------------
step(1, "과목 고르기", "시험 일정을 정할 과목을 누르세요.")
if S.get("avail_code") not in exam_codes:
    S.avail_code = exam_codes[0]
sel = S.avail_code
button_row(exam_codes, sel, key=f"course_{pid}", fmt=lambda x: cm[x].name + (" ✔" if x in S.confirmed else ""),
           state_key="avail_code", per_row=min(4, max(2, len(exam_codes))))
csel = cm[sel]
stg = S.settings
row_sel = state.exam_row(sel)
confirmed_sel = sel in S.confirmed
say(f"<b>{html.escape(csel.name)}</b> · 수강생 {csel.enrollment}명 · {EXAM_TYPE_LABEL[csel.exam_type]}"
    + (f" · 지금 일정: <b>{state.slot_text(int(row_sel.day), int(row_sel.start), int(row_sel.end))}</b>, {row_sel.room_id}"
       if row_sel is not None else ""))
if no_exam:
    st.caption("시험 없음(과제 대체) 과목: " + ", ".join(cm[x].name for x in no_exam)
               + " — 시험 기간에도 정규 수업이 진행되어, 수강생은 그 시간에 다른 시험을 볼 수 없습니다.")

# ---------------------------------------------------------------------------
# ② 시험 시간 정하기
# ---------------------------------------------------------------------------
step(2, "시험 시간 정하기", "시험을 몇 시간 동안 볼지 누르세요. 시간표의 시험 칸 크기가 바로 바뀝니다.")
saved = csel.exam_minutes
dkey = f"dur_{sel}"
if csel.exam_type == EXAM_IN_CLASS:
    dur_new = saved
    say(f"이 과목은 <b>수업시간 시험</b>이라 정규 수업 시간({minutes_text(exam_len(csel))}) 동안 정규 강의실에서 봅니다. "
        "수업이 없는 다른 빈 시간에 보고 싶으시면 ③ 시간표에서 <b>초록색 칸</b>을 누르세요. "
        "그 시간에 비어 있는 강의실을 고르면 <b>'별도 시험'</b>으로 바뀌고, 그다음부터는 시험 시간도 버튼으로 바꿀 수 있습니다.")
else:
    opts = sorted(set(EXAM_DURATION_BUTTONS) | {saved})
    if S.get(dkey) not in opts:
        S[dkey] = saved
    button_row(opts, S[dkey], key=f"durbtn_{sel}", fmt=minutes_text, state_key=dkey, disabled=confirmed_sel,
               per_row=len(opts) if len(opts) <= 7 else 6)
    dur_new = int(S[dkey])
    if confirmed_sel:
        st.caption("🔒 확정된 시험은 시험 시간을 바꿀 수 없습니다. 바꾸려면 ④에서 확정을 취소하세요.")
preview = dur_new != saved   # 저장하기 전 미리 보기 중

# 미리 보기: 새 시험 시간으로 바꾼 데이터로 시작 가능 시각을 다시 계산한다 (저장 전에는 실제 일정을 바꾸지 않음)
view_ds = ds.with_course_update(sel, exam_minutes=dur_new) if preview else ds
# 보드에서는 이 과목에 걸린 '이 시간에만 / 이 강의실만' 조건(직전 옮기기 결과)을 빼고 계산한다.
# 새로 옮기면 그 조건이 새 시간·강의실로 바뀌기 때문 (불가 시간·선호 등 다른 요청은 그대로 반영)
view_reqs = dict(S.requests)
if sel in view_reqs:
    view_reqs[sel] = dataclasses.replace(view_reqs[sel], allowed=[], room_ids=[])
smap = slot_map(view_ds, S.schedule, stg, view_reqs, sel)
dur_len = exam_len(csel, dur_new)
here = None
if row_sel is not None:
    here = next((x for x in smap if x["day"] == int(row_sel.day) and x["start"] == int(row_sel.start)), None)
fits_here = here is not None and here["status"] != "blocked"

# 수업시간 시험도 수업이 없는 빈 시간으로 옮길 수 있다: 그 경우 '별도 시험'으로 바뀐다.
# 정규 수업 회차는 원래 강의실 그대로(수업시간 시험), 그 밖의 빈 시간은 별도 시험 기준(시험 좌석이 충분한 빈 강의실)으로 계산
in_class = csel.exam_type == EXAM_IN_CLASS
class_ok = set()
board_map = smap
if in_class:
    class_ok = {(x["day"], x["start"]) for x in smap if x["status"] != "blocked"}
    sep_ds = view_ds.with_course_update(sel, exam_type=EXAM_SEPARATE, exam_minutes=dur_len)
    by_slot = {(x["day"], x["start"]): x for x in smap}
    board_map = [dict(by_slot[(x["day"], x["start"])], kind="class") if (x["day"], x["start"]) in class_ok
                 else dict(x, kind="separate") for x in slot_map(sep_ds, S.schedule, stg, view_reqs, sel)]
    board_map += [dict(x, kind="class") for k, x in by_slot.items()
                  if k in class_ok and not any((y["day"], y["start"]) == k for y in board_map)]
n_start = sum(x["status"] != "blocked" for x in board_map)

if csel.exam_type != EXAM_IN_CLASS:
    if not preview or row_sel is None:
        st.markdown(f"<div class='sg-dur'>현재 시험 시간: <b>{minutes_text(saved)}</b> ({saved}분)</div>",
                    unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='sg-dur'>시험 시간을 <b>{minutes_text(saved)}</b> → <b class='new'>{minutes_text(dur_new)}</b>"
                    "으로 바꾸려고 합니다. <span class='sg-muted'>아직 저장하지 않았습니다.</span></div>",
                    unsafe_allow_html=True)
        when_now = state.slot_text(int(row_sel.day), int(row_sel.start), int(row_sel.start) + dur_len)
        if fits_here:
            st.success(f"지금 날짜·시간 그대로 **{when_now}**에 볼 수 있습니다. 아래 버튼을 눌러 저장하세요.")
        else:
            why = here["reason"] if here else "하루 시험 시간이 끝나는 시각을 넘어갑니다"
            st.error(f"지금 날짜·시간(**{when_now}**)에는 {minutes_text(dur_new)}을 넣을 수 없습니다 — {why}.  \n"
                     + ("③ 시간표에서 **초록색 칸**을 눌러 새 시간을 고르시거나, '알맞은 시간 자동으로 찾기'를 누르세요."
                        if n_start else "이 시험 시간으로는 지금 시간표에 빈자리가 없습니다. '알맞은 시간 자동으로 찾기'를 누르면 "
                                        "다른 과목 일정까지 조정해 자리를 찾아봅니다."))
        b1, b2, _ = st.columns([1.5, 1.3, 1.6])
        if fits_here:
            if b1.button(f"✅ {minutes_text(dur_new)}으로 저장", type="primary", width="stretch", key=f"save_dur_{sel}"):
                rid = str(row_sel.room_id)
                rid = rid if any(r["rid"] == rid for r in here["rooms"]) else here["room"]
                spec = {"allowed": [{"day": stg.day_name(here["day"]), "start": min_to_hm(here["start"]),
                                     "end": min_to_hm(here["end"])}],
                        "room": {"min_capacity": None, "building": None, "room_ids": [rid]},
                        "duration_minutes": dur_new,
                        "summary": f"시험 시간 {minutes_text(dur_new)} · {stg.date_label(here['day'])} {min_to_hm(here['start'])} 시작"}
                req = validate_request(spec, source="시험 시간 버튼")
                if apply_request(sel, req, text=f"시험 시간을 {minutes_text(dur_new)}으로 변경", mode="시험 시간 버튼"):
                    st.toast(f"{csel.name} 시험 시간을 {minutes_text(dur_new)}으로 바꿨습니다.", icon="✅")
                    st.rerun()
        elif b1.button("🔎 알맞은 시간 자동으로 찾기", type="primary", width="stretch", key=f"auto_dur_{sel}"):
            req = validate_request({"duration_minutes": dur_new, "summary": f"시험 시간 {minutes_text(dur_new)}"},
                                   source="시험 시간 버튼")
            if apply_request(sel, req, text=f"시험 시간을 {minutes_text(dur_new)}으로 변경(자동 배치)", mode="시험 시간 버튼"):
                st.toast(f"{csel.name} 시험 시간을 {minutes_text(dur_new)}으로 바꾸고 알맞은 시간에 배치했습니다.", icon="✅")
                st.rerun()
        b2.button(f"↩️ 원래대로 ({minutes_text(saved)})", width="stretch", key=f"reset_dur_{sel}",
                  on_click=lambda k=dkey, v=saved: S.__setitem__(k, v))
        show_move_error()

# ---------------------------------------------------------------------------
# ③ 시간표에서 날짜·시간 고르기
# ---------------------------------------------------------------------------
step(3, "날짜·시간 고르기", "초록색 칸을 누르면 그 시간으로 옮길 수 있습니다. 빨간 칸의 숫자는 그 시간에 다른 일정이 있는 학생 수입니다.")
bmap = busy_map(ds, S.schedule, stg, view_reqs, sel)
cells = []
for b in bmap:
    when = f"{stg.date_label(b['day'])} {min_to_hm(b['start'])}~{min_to_hm(b['end'])}"
    if b["unavail"]:
        cells.append(dict(b, cls="prof", label="교수 불가", tip=f"{when} — 교수 불가 시간"))
    elif b["prof_busy"]:
        cells.append(dict(b, cls="prof", label="내 일정", tip=f"{when} — 교수님의 다른 수업·시험"))
    elif b["busy"]:
        cells.append(dict(b, cls="busy", label=f"{b['busy']}명",
                          tip=f"{when} — 수강생 {b['busy']}명이 다른 시험·수업 중 (이 시간에 시험 불가)"))
    else:
        cells.append(dict(b, cls="free", label="", tip=f"{when} — 수강생 전원·교수님 모두 비어 있음"))
evs = []
for oc in my_codes:
    o = cm[oc]
    if o.exam_type == EXAM_NONE:
        for d, s0, e0 in stg.class_blocks(o):
            evs.append(dict(day=d, start=s0, end=e0, cls="", title=o.name, sub="내 정규 수업(진행)"))
    r0 = state.exam_row(oc)
    if r0 is not None and oc != sel:
        conf = oc in S.confirmed
        evs.append(dict(day=int(r0.day), start=int(r0.start), end=int(r0.end), cls="other",
                        title=f"{o.name} 시험" + (" ✔" if conf else ""),
                        sub=f"{'확정' if conf else '현재 추천'} · {min_to_hm(r0.start)}~{min_to_hm(r0.end)} · {r0.room_id}"))
say(f"<b>{minutes_text(dur_len)}</b> 시험을 시작할 수 있는 시각이 <b>{n_start}개</b> 있습니다."
    if n_start else "지금 시험 시간으로 시작할 수 있는 시각이 없습니다. ②에서 시험 시간을 줄이거나 '말로 조건 바꾸기'를 이용해 주세요.")
st.markdown(legend([("background:#E3F6EE", "초록 = 수강생·교수 모두 비어 있음"),
                    ("background:#FBE4E4", "빨강 숫자 = 그 시간에 일정이 있는 학생 수"),
                    ("background:#F3F4F7", "회색 = 교수 불가·내 일정"),
                    ("background:#1C2E5A", "남색 = 이 과목 시험"),
                    ("background:#5C6B8A", "내 다른 과목 시험")]),
            unsafe_allow_html=True)
movable = not confirmed_sel
locked_reason = "확정된 시험이라 옮길 수 없습니다. 바꾸려면 ④에서 확정을 취소하세요." if not movable else ""
slots, blocked = {}, {}
for x in board_map:
    sid = f"{x['day']}-{x['start']}"
    if x["status"] == "blocked":
        blocked[sid] = x["reason"]
        continue
    info = ("수강생 전원 충돌 없음 · 하루 3과목·연속 시험 0명" if x["status"] == "ok"
            else f"수강생 충돌 없음 · 다만 하루 3과목 이상 {x['overload']}명 · 연속 시험 {x['consecutive']}명")
    if x.get("kind") == "class":
        info += " · 정규 수업 시간이라 원래 강의실에서 그대로 봅니다(수업시간 시험)"
    elif x.get("kind") == "separate":
        info += " · 수업이 없는 시간이라 '별도 시험'으로 바뀌어 고른 강의실에서 봅니다"
    slots[sid] = dict(day=x["day"], start=x["start"], end=x["end"], info=info,
                      when=f"{stg.date_label(x['day'])} {min_to_hm(x['start'])}~{min_to_hm(x['end'])}",
                      rooms=x["rooms"])
default_block = "시험이 하루 시험 시간이 끝나는 시각을 넘어갑니다"
cur_sid = f"{int(row_sel.day)}-{int(row_sel.start)}" if row_sel is not None else None
st_min = min([stg.day_start] + [e["start"] for e in evs])
en_min = max([stg.day_end] + [e["end"] for e in evs])
if row_sel is not None:
    ex_end = int(row_sel.start) + dur_len if preview else int(row_sel.end)
    board_data = dict(
        days=[dict(label=stg.day_name(k), sub=stg.short_label(k).split("(")[0]) for k in range(stg.n_days)],
        start=st_min, end=max(en_min, ex_end), ppm=1.3,
        ticks=[dict(m=m, label=min_to_hm(m)) for m in range((st_min // 60 + (st_min % 60 > 0)) * 60, en_min + 1, 60)],
        cells=cells, slots=slots, blocked=blocked, default_block=default_block,
        events=[dict(day=e["day"], start=e["start"], end=e["end"], title=e["title"], sub=e["sub"], cls=e["cls"])
                for e in evs],
        exam=dict(day=int(row_sel.day), start=int(row_sel.start), end=ex_end, room=str(row_sel.room_id),
                  slot=cur_sid, title=f"{csel.name} 시험" + (" ✔" if confirmed_sel else ""),
                  dur_label=minutes_text(dur_len), preview=preview, fits=fits_here,
                  sub=f"{min_to_hm(row_sel.start)}~{min_to_hm(ex_end)} · {row_sel.room_id}"
                      f" (시험 좌석 {ds.room_map[row_sel.room_id].exam_capacity}석)"),
        enrollment=csel.enrollment, movable=movable,
        room_fixed=False, locked_reason=locked_reason,
    )
    # 시험 시간이 바뀌면 보드도 새로 그린다 (key 에 길이 포함)
    mv = exam_board(board_data, key=f"board_{sel}_{dur_len}")
    if mv:
        d, s0 = int(mv["day"]), int(mv["start"])
        e0 = s0 + dur_len
        # 수업시간 시험을 정규 수업 회차가 아닌 시간(또는 다른 강의실)으로 옮기면 '별도 시험'으로 바꾼다
        keep_class = in_class and (d, s0) in class_ok and str(mv["room"]) == csel.room
        to_separate = in_class and not keep_class
        summary = f"{stg.date_label(d)} {min_to_hm(s0)} 시작" + ("" if keep_class else f" · {mv['room']}")
        if to_separate:
            summary += " · 별도 시험으로 변경"
        spec = {"allowed": [{"day": stg.day_name(d), "start": min_to_hm(s0), "end": min_to_hm(e0)}], "summary": summary}
        if not keep_class:
            spec["room"] = {"min_capacity": None, "building": None, "room_ids": [str(mv["room"])]}
        if preview:
            spec["duration_minutes"] = dur_new
            spec["summary"] = f"시험 시간 {minutes_text(dur_new)} · {summary}"
        req = validate_request(spec, source="시간표에서 옮기기")
        ok = apply_request(sel, req, text=f"시간표에서 {req.summary}(으)로 옮기기", mode="시간표에서 고르기",
                           course_changes={"exam_type": EXAM_SEPARATE, "exam_minutes": dur_len} if to_separate else None)
        if ok:
            st.toast(f"{csel.name} 시험을 {req.summary}(으)로 정했습니다.", icon="✅")
            st.rerun()
    show_move_error()

# ---------------------------------------------------------------------------
# ④ 확인하고 확정하기
# ---------------------------------------------------------------------------
step(4, "확인하고 확정하기", "일정이 마음에 들면 확정을 누르세요. 확정하면 학생에게 알림이 갑니다.")
c = csel
row = row_sel
with st.container(border=True):
    top_l, top_r = st.columns([3.2, 1.6])
    status = badge("확정", "ok") if confirmed_sel else badge("추천 · 미확정", "")
    top_l.markdown(f"<div class='sg-big'>{html.escape(c.name)} <span class='sg-muted'>{sel}</span></div>"
                   f"<div style='margin-top:4px'>{badge(EXAM_TYPE_LABEL[c.exam_type], 'gray')}{status}"
                   f"{badge(f'수강 {c.enrollment}명', 'gray')}{badge('시험 ' + minutes_text(exam_len(c)), 'gray')}</div>",
                   unsafe_allow_html=True)
    if row is not None:
        room = ds.room_map.get(row.room_id)
        top_r.markdown(f"<div style='text-align:right'><div class='sg-big'>{state.slot_text(int(row.day), int(row.start), int(row.end))}</div>"
                       f"<div class='sg-muted'>{row.room_id} · {room.capacity if room else '-'}석</div></div>",
                       unsafe_allow_html=True)
        if preview:
            warn_box(f"⚠️ ②에서 고른 시험 시간({minutes_text(dur_new)})이 아직 저장되지 않았습니다. "
                     "저장하거나 '원래대로'를 누른 뒤 확정해 주세요.")
        slots_e = evaluate_slots(ds, S.schedule, S.settings, S.requests, sel)
        facts = course_facts(ds, S.schedule, S.settings, S.requests, per_course, sel, slots_e)
        if use_ai:
            use_ai = st.toggle("AI 문장으로 설명 보기", value=True,
                               help="계산된 수치만 Claude에게 넘겨 자연스러운 문장으로 바꿉니다. 끄면 템플릿 문장을 씁니다.")
        txt, src = reason_text(facts)
        reason_box(html.escape(txt).replace("**", "") if src.startswith("AI") else
                   txt.replace("**", "<b>", 1).replace("**", "</b>", 1))
        for wmsg in facts["warnings"]:
            warn_box("⚠️ " + html.escape(wmsg))
        req0 = S.requests.get(sel)
        if req0 and not req0.is_empty():
            st.markdown("<div class='sg-muted'>적용 중인 추가 조건: " + " · ".join(html.escape(x) for x in req0.describe())
                        + "</div>", unsafe_allow_html=True)
        st.caption(f"설명 방식: {src}")

        b1, b2, _ = st.columns([1.4, 1.4, 2])
        if not confirmed_sel:
            ok_conf, why = state.can_confirm(sel)
            if b1.button("✅ 이 일정으로 확정", key=f"conf_{sel}", type="primary", width="stretch",
                         disabled=not ok_conf or preview):
                state.confirm(sel)
                if S.settings.notify_mode == NOTIFY_INSTANT or S.published_at:
                    st.toast(f"{c.name} 시험을 확정했습니다. 수강생 {c.enrollment}명에게 알림을 보냈습니다.", icon="📨")
                else:
                    st.toast(f"{c.name} 시험을 확정했습니다. 관리자가 전체 일정을 발표하면 수강생에게 알림이 갑니다.", icon="✅")
                st.rerun()
            mine = [x for x in S.change_log if x["prof"] == pid and x["code"] == sel]
            if mine and b2.button("↩️ 방금 바꾼 것 되돌리기", key=f"undo_{sel}", width="stretch",
                                  help=f"“{mine[-1]['text']}” 이전 일정으로 돌아갑니다."):
                undo(mine[-1])
                st.rerun()
            if not ok_conf:
                st.caption("🔒 " + why)
        else:
            published = state.is_published(sel)
            b1.markdown(f"<div style='padding-top:8px'>{badge('학생 발표 완료' if published else '확정 · 발표 대기', 'ok')}</div>",
                        unsafe_allow_html=True)
            if not published and b2.button("확정 취소", key=f"unconf_{sel}", width="stretch",
                                           help="확정을 풀면 다음 재배정에서 이 시험이 바뀔 수 있습니다."):
                state.unconfirm(sel)
                st.rerun()

# 다른 담당 과목 진행 상황 (한눈에)
if len(exam_codes) > 1:
    rows_o = []
    for oc in exam_codes:
        r0 = state.exam_row(oc)
        rows_o.append({"과목": cm[oc].name, "시험 시간": minutes_text(exam_len(cm[oc])),
                       "일정": state.slot_text(int(r0.day), int(r0.start), int(r0.end)) if r0 is not None else "-",
                       "강의실": r0.room_id if r0 is not None else "-",
                       "상태": "확정" if oc in S.confirmed else "미확정"})
    st.markdown("**내 담당 과목 전체** <span class='sg-muted'>(다른 과목은 ①에서 눌러 고르세요)</span>", unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(rows_o), hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# 더 많은 기능: 말로 조건 바꾸기(AI) · 다른 시간 추천 · 변경 전/후 비교
# ---------------------------------------------------------------------------
st.markdown("### 더 많은 기능")
st.caption("위 네 단계만으로 충분합니다. 조건이 복잡하면 아래 기능을 이용하세요.")

if row is not None:
    with st.expander("🔍 다른 시간 추천 · 바꾸면 학생에게 생기는 영향"):
        imp = impact_facts(facts, slots_e, S.settings)
        itxt = template_impact(imp)
        key = "impact:" + json.dumps(imp, ensure_ascii=False, sort_keys=True, default=str)
        if key in S.llm_cache:
            itxt = S.llm_cache[key]
        elif use_ai and st.button("🤖 AI로 영향 설명 듣기", key=f"imp_{sel}"):
            try:
                with st.spinner("AI가 영향 분석을 정리하는 중…"):
                    itxt = llm_impact(imp)
                S.llm_cache[key] = itxt
            except llm.LLMError:
                st.caption("AI 호출에 실패해 기본 문장으로 보여 드립니다.")
        st.markdown(f"<div class='sg-reason'>{html.escape(itxt)}</div>", unsafe_allow_html=True)
        if imp["alternatives"]:
            st.dataframe(pd.DataFrame([{
                "대안": a["rank"], "일시": a["when"], "강의실": a["room"], "충돌 학생": 0,
                "하루 3과목 이상": a["overload_students"], "연속 시험": a["consecutive_students"],
                "선호 반영": "-" if a["preference_met"] is None else ("예" if a["preference_met"] else "아니오")}
                for a in imp["alternatives"]]), hide_index=True, width="stretch")
            if not confirmed_sel:
                alt_cols = st.columns(len(imp["alternatives"]))
                for i, a in enumerate(imp["alternatives"]):
                    d, s0, e0 = a["_slot"]
                    if alt_cols[i].button(f"대안 {i + 1}로 옮기기", key=f"alt_{sel}_{i}", width="stretch"):
                        S.edit_code = sel
                        S.pending[sel] = dict(
                            req=validate_request({"allowed": [{"day": S.settings.day_name(d), "start": min_to_hm(s0),
                                                               "end": min_to_hm(e0)}],
                                                  "summary": f"{a['when']}로 이동"}, source="대안 선택"),
                            mode="대안 선택", note=None, text=f"대안 {i + 1}({a['when']})로 옮기기", all=False)
                        st.rerun()

editable = [x for x in my_codes if cm[x].exam_type != EXAM_NONE and x not in S.confirmed]
with st.expander("💬 말로 조건 바꾸기 (예: 목요일 오후는 안 돼요)", expanded=bool(S.pending)):
    if not editable:
        st.info("수정할 수 있는 시험이 없습니다. (모두 확정되었거나 시험 없음 과목)")
    else:
        cur = S.get("edit_code") or sel
        idx = editable.index(cur) if cur in editable else 0
        code = st.selectbox("바꿀 과목", editable, index=idx, format_func=lambda x: f"{cm[x].name} ({x})")
        S.edit_code = code
        c = cm[code]
        row = state.exam_row(code)
        if c.exam_type == EXAM_IN_CLASS:
            st.info(f"수업시간 시험은 시험 기간 중 정규 수업({'·'.join(DAYS[d] for d in c.days)} {min_to_hm(c.start)}) 회차에서만 "
                    "날짜를 고를 수 있습니다. 요일 조건은 회차 선택에 반영됩니다.")
        examples = ["목요일 오후는 안 되고, 가능하면 오전으로", "시험 시간을 120분으로 늘려줘",
                    "금요일은 피해 주시고 100석 이상 강의실로", "다른 날로 옮겨 주세요"]
        st.caption("예시 문장을 누르면 입력창에 채워집니다.")
        ex_cols = st.columns(2)
        for i, ex in enumerate(examples):
            if ex_cols[i % 2].button(ex, key=f"ex_{i}", width="stretch"):
                S[f"nl_{code}"] = ex
                st.rerun()
        text = st.text_area("요청 내용", key=f"nl_{code}", height=90,
                            placeholder="예: 목요일 오후는 안 되고, 가능하면 오전으로")
        apply_all = st.checkbox("시간 조건을 내 다른 미확정 과목에도 적용", value=False)
        if st.button("🧠 조건으로 변환하기", type="primary", disabled=not text.strip()):
            ctx = ParseContext(code=code, name=c.name, duration=c.exam_minutes, enrollment=c.enrollment,
                               exam_type=c.exam_type,
                               current=(S.settings.weekday(int(row.day)), int(row.start), int(row.end))
                               if row is not None else None,
                               day_start=S.settings.day_start, day_end=S.settings.day_end,
                               buildings=sorted({r.building for r in ds.room_map.values()}))
            with st.spinner("요청을 구조화된 조건으로 바꾸는 중…"):
                req, mode, note = parse_request(text, ctx, use_llm=llm.available())
            S.pending[code] = dict(req=req, mode=mode, note=note, text=text, all=apply_all)
            st.rerun()

        pend = S.pending.get(code)
        if pend:
            req: CourseRequest = pend["req"]
            st.markdown("#### 변환 결과 확인")
            st.markdown(f"{badge('변환: ' + pend['mode'], 'ok' if pend['mode'] == 'AI' else '')} "
                        f"<span class='sg-muted'>요청: “{html.escape(pend['text'])}”</span>", unsafe_allow_html=True)
            if pend.get("note"):
                st.warning(pend["note"])
            if req.is_empty():
                st.error("인식된 조건이 없습니다. 요일·시간(예: 목요일 오후, 10시 이후)이나 시험 시간(예: 120분)을 넣어 다시 적어 주세요.")
            else:
                reason_box("<b>해석:</b> " + html.escape(req.summary or "") + "<br>" +
                           "<br>".join(html.escape(x) for x in req.describe()))
            if req.unsupported:
                warn_box("처리하지 못한 부분: " + html.escape(" / ".join(req.unsupported)))
            if st.toggle("구조화된 조건(JSON) 보기", key=f"json_{code}"):
                st.code(json.dumps(req.to_dict(), ensure_ascii=False, indent=2), language="json")
            y, n, _ = st.columns([1.4, 1, 3])
            go_btn = y.button("✅ 이 조건으로 재배정", type="primary", disabled=req.is_empty(), width="stretch")
            if n.button("취소", width="stretch"):
                S.pending.pop(code, None)
                st.rerun()
            if go_btn:
                targets = [code] + ([x for x in editable if x != code] if pend.get("all") else [])
                if apply_request(code, req, text=pend["text"], mode=pend["mode"], targets=targets):
                    S.pop(f"dur_{code}", None)   # 시험 시간이 바뀌었을 수 있으니 버튼 값을 새로 맞춘다
                    st.toast("재배정 완료", icon="✅")
                    st.rerun()
                show_move_error()

logs = [x for x in S.change_log if x["prof"] == pid]
if logs:
    lg = logs[-1]
    with st.expander("🔁 마지막 변경 전 / 후 비교"):
        st.markdown(f"<div class='sg-muted'>{lg['time']} · 요청 “{html.escape(lg['text'])}” → "
                    f"{html.escape(lg['summary'] or '')} ({lg['mode']}) · 재배정 {lg['solve_time']:.1f}초</div>",
                    unsafe_allow_html=True)
        b, a = lg["before"].set_index("course_code"), lg["after"].set_index("course_code")
        rows = []
        for t in lg["targets"]:
            if t not in b.index or t not in a.index:
                continue
            rb, ra = b.loc[t], a.loc[t]
            rows.append({"과목": f"{cm[t].name} ({t})",
                         "변경 전": f"{state.slot_text(int(rb.day), int(rb.start), int(rb.end))} · {rb.room_id}",
                         "변경 후": f"{state.slot_text(int(ra.day), int(ra.start), int(ra.end))} · {ra.room_id}",
                         "바뀜": "예" if (rb.day, rb.start, rb.end, rb.room_id) != (ra.day, ra.start, ra.end, ra.room_id) else "아니오"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        others = [x for x in a.index if x not in lg["targets"] and x in b.index
                  and (b.loc[x, "day"], b.loc[x, "start"], b.loc[x, "room_id"]) != (a.loc[x, "day"], a.loc[x, "start"], a.loc[x, "room_id"])]
        bm, am = lg["before_metrics"], lg["after_metrics"]

        def delta(k, unit="명"):
            d = am.get(k, 0) - bm.get(k, 0)
            return f"변경 전 {bm.get(k, 0)}{unit} ({'+' if d > 0 else ''}{d:g})"
        metric_cards([
            dict(label="반드시 지킬 조건 위반", value=am.get("hard_violations", 0), unit="건",
                 tone="ok" if am.get("hard_violations", 0) == 0 else "bad", sub=delta("hard_violations", "건")),
            dict(label="하루 3과목 이상 학생", value=am.get("students_3plus", 0), unit="명", tone="info",
                 sub=delta("students_3plus")),
            dict(label="연속 시험 학생", value=am.get("consecutive_students", 0), unit="명", tone="info",
                 sub=delta("consecutive_students")),
            dict(label="함께 바뀐 다른 과목", value=len(others), unit="개", tone="info",
                 sub="확정된 시험은 바뀌지 않음"),
        ])
        if others:
            st.caption("함께 조정된 다른 과목: " + ", ".join(
                f"{cm[x].name}({state.slot_text(int(b.loc[x, 'day']), int(b.loc[x, 'start']), with_date=False)} → "
                f"{state.slot_text(int(a.loc[x, 'day']), int(a.loc[x, 'start']), with_date=False)})" for x in others))
        if st.button("↩️ 변경 전으로 되돌리기", key="undo"):
            undo(lg)
            st.rerun()
