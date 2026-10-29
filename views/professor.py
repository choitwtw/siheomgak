"""교수 화면: 내 과목 추천 일정·이유·경고 → 자연어 수정 → 변환 확인 → 재배정 → 전/후 비교 → 확정."""
from __future__ import annotations

import html
import json
from datetime import datetime

import pandas as pd
import streamlit as st

from core import llm
from core.config import DAYS, EXAM_IN_CLASS, EXAM_NONE, EXAM_TYPE_LABEL
from core.constraints import CourseRequest, validate_request
from core.explain import (
    course_facts,
    evaluate_slots,
    impact_facts,
    llm_impact,
    llm_reason,
    template_impact,
    template_reason,
)
from core.nlparse import ParseContext, parse_request
from core.priority import dept_rank
from core.timeutil import min_to_hm, windows_to_text
from ui import state
from ui.style import badge, hero, metric_cards, reason_box, warn_box

S = st.session_state
state.ensure_schedule()
ds = S.ds
S.setdefault("llm_cache", {})

hero("PROFESSOR", "교수 화면",
     "내 과목의 추천 시험 일정과 그 이유를 확인하고, 말로 조건을 바꿔 재배정한 뒤 확정합니다.")

if S.schedule is None:
    st.warning("배정 결과가 없습니다. 관리자 대시보드에서 배정을 실행해 주세요.")
    st.stop()

# ---------------------------------------------------------------------------
# 교수 선택 (로그인 대신)
# ---------------------------------------------------------------------------
profs = ds.professors.sort_values("professor_id")
pids = list(profs["professor_id"])
rank = dept_rank(S.settings.semester)
pm = ds.prof_map
pid = st.selectbox("교수 선택", pids, index=pids.index(S.get("prof_id", pids[0])) if S.get("prof_id") in pids else 0,
                   format_func=lambda p: f"{pm[p].name} 교수 · {pm[p].dept} ({p})")
S.prof_id = pid
prof = pm[pid]
my_codes = ds.prof_courses.get(pid, [])
cm = ds.course_map

info = [f"소속 {prof.dept} (이번 학기 우선순위 {rank.get(prof.dept)}위)"]
info.append("불가 시간: " + (windows_to_text(prof.unavailable) or "없음"))
info.append("선호 시간: " + (windows_to_text(prof.preferred) or "없음"))
st.markdown("<div class='sg-muted'>" + " · ".join(html.escape(x) for x in info) + "</div>", unsafe_allow_html=True)
st.write("")

use_ai = llm.available()
if use_ai:
    use_ai = st.toggle("AI 문장으로 설명 보기", value=True,
                       help="계산된 수치만 Claude에게 넘겨 자연스러운 문장으로 바꿉니다. 끄면 템플릿 문장을 씁니다.")

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


# ---------------------------------------------------------------------------
# 내 과목 카드
# ---------------------------------------------------------------------------
st.markdown("### 내 과목 추천 일정")
for code in my_codes:
    c = cm[code]
    row = state.exam_row(code)
    confirmed = code in S.confirmed
    with st.container(border=True):
        top_l, top_r = st.columns([3.2, 1.4])
        status = badge("확정", "ok") if confirmed else (badge("시험 없음", "gray") if c.exam_type == EXAM_NONE
                                                       else badge("추천 · 미확정", ""))
        top_l.markdown(f"<div class='sg-big'>{html.escape(c.name)} <span class='sg-muted'>{code}</span></div>"
                       f"<div style='margin-top:4px'>{badge(EXAM_TYPE_LABEL[c.exam_type], 'gray')}{status}"
                       f"{badge(f'수강 {c.enrollment}명', 'gray')}{badge(f'시험 {c.exam_minutes}분', 'gray')}</div>",
                       unsafe_allow_html=True)
        if c.exam_type == EXAM_NONE or row is None:
            st.markdown("<div class='sg-muted'>시험 없음(과제 대체) 과목입니다. 시험 주간에도 정규 수업 "
                        f"({'·'.join(DAYS[d] for d in c.days)} {min_to_hm(c.start)}~{min_to_hm(c.end)}, {c.room})이 진행되어 "
                        "수강생은 이 시간에 다른 시험을 볼 수 없습니다.</div>", unsafe_allow_html=True)
            continue
        room = ds.room_map.get(row.room_id)
        top_r.markdown(f"<div style='text-align:right'><div class='sg-big'>{state.slot_text(int(row.day), int(row.start), int(row.end))}</div>"
                       f"<div class='sg-muted'>{row.room_id} · {room.capacity if room else '-'}석</div></div>",
                       unsafe_allow_html=True)
        slots = evaluate_slots(ds, S.schedule, S.settings, S.requests, code)
        facts = course_facts(ds, S.schedule, S.settings, S.requests, per_course, code, slots)
        txt, src = reason_text(facts)
        reason_box(html.escape(txt).replace("**", "") if src.startswith("AI") else
                   txt.replace("**", "<b>", 1).replace("**", "</b>", 1))
        for wmsg in facts["warnings"]:
            warn_box("⚠️ " + html.escape(wmsg))
        req = S.requests.get(code)
        if req and not req.is_empty():
            st.markdown("<div class='sg-muted'>적용 중인 추가 조건: " + " · ".join(html.escape(x) for x in req.describe())
                        + "</div>", unsafe_allow_html=True)
        st.caption(f"설명 방식: {src}")

        b1, b2, b3, _ = st.columns([1.1, 1.3, 1.2, 2])
        if not confirmed:
            if b1.button("✅ 확정", key=f"conf_{code}", type="primary", width="stretch"):
                state.confirm(code)
                st.toast(f"{c.name} 시험을 확정했습니다. 수강생 {c.enrollment}명에게 알림을 보냈습니다.", icon="📨")
                st.rerun()
            if b2.button("✏️ 조건 바꾸기", key=f"edit_{code}", width="stretch"):
                S.edit_code = code
                st.rerun()
        else:
            b1.markdown(f"<div style='padding-top:8px'>{badge('수강생 알림 발송 완료', 'ok')}</div>", unsafe_allow_html=True)
            if b3.button("확정 취소", key=f"unconf_{code}", width="stretch",
                         help="확정을 풀면 다음 재배정에서 이 시험이 바뀔 수 있습니다."):
                state.unconfirm(code)
                st.rerun()

        with st.expander("🔍 변경 영향 분석 · 대안 시간"):
            imp = impact_facts(facts, slots, S.settings)
            itxt = template_impact(imp)
            key = "impact:" + json.dumps(imp, ensure_ascii=False, sort_keys=True, default=str)
            if key in S.llm_cache:
                itxt = S.llm_cache[key]
            elif use_ai and st.button("🤖 AI로 영향 설명 듣기", key=f"imp_{code}"):
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
                if not confirmed:
                    alt_cols = st.columns(len(imp["alternatives"]))
                    for i, a in enumerate(imp["alternatives"]):
                        d, s0, e0 = a["_slot"]
                        if alt_cols[i].button(f"대안 {i + 1}로 옮기기", key=f"alt_{code}_{i}", width="stretch"):
                            S.edit_code = code
                            S.pending[code] = dict(
                                req=validate_request({"allowed": [{"day": DAYS[d], "start": min_to_hm(s0),
                                                                   "end": min_to_hm(e0)}],
                                                      "summary": f"{a['when']}로 이동"}, source="대안 선택"),
                                mode="대안 선택", note=None, text=f"대안 {i + 1}({a['when']})로 옮기기", all=False)
                            st.rerun()

# ---------------------------------------------------------------------------
# 자연어 수정 → 변환 확인 → 재배정
# ---------------------------------------------------------------------------
editable = [c for c in my_codes if cm[c].exam_type != EXAM_NONE and c not in S.confirmed]
st.markdown("### 말로 조건 바꾸기")
if not editable:
    st.info("수정할 수 있는 시험이 없습니다. (모두 확정되었거나 시험 없음 과목)")
else:
    with st.container(border=True):
        cur = S.get("edit_code")
        idx = editable.index(cur) if cur in editable else 0
        code = st.selectbox("수정할 과목", editable, index=idx, format_func=lambda x: f"{cm[x].name} ({x})")
        S.edit_code = code
        c = cm[code]
        row = state.exam_row(code)
        if c.exam_type == EXAM_IN_CLASS:
            st.info(f"수업시간 시험은 정규 수업({'·'.join(DAYS[d] for d in c.days)} {min_to_hm(c.start)}) 회차 중에서만 "
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
                               current=(int(row.day), int(row.start), int(row.end)) if row is not None else None,
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
            with st.expander("구조화된 조건(JSON) 보기"):
                st.code(json.dumps(req.to_dict(), ensure_ascii=False, indent=2), language="json")
            y, n, _ = st.columns([1.4, 1, 3])
            go_btn = y.button("✅ 이 조건으로 재배정", type="primary", disabled=req.is_empty(), width="stretch")
            if n.button("취소", width="stretch"):
                S.pending.pop(code, None)
                st.rerun()
            if go_btn:
                targets = [code] + ([x for x in editable if x != code] if pend.get("all") else [])
                new_reqs = dict(S.requests)
                new_ds = ds
                time_part = CourseRequest(unavailable=req.unavailable, allowed=req.allowed, preferred=req.preferred,
                                          avoid=req.avoid)
                for t in targets:
                    part = req if t == code else time_part
                    old = new_reqs.get(t, CourseRequest())
                    merged = old.merged_with(part)
                    merged.duration_minutes = None
                    new_reqs[t] = merged
                if req.duration_minutes:
                    new_ds = ds.with_course_update(code, exam_minutes=int(req.duration_minutes))
                before_sched = S.schedule.copy()
                before_metrics = dict(rep.metrics) if rep else {}
                before_conf = dict(S.confirmed)
                before_reqs = dict(S.requests)
                with st.spinner("조건을 반영해 다시 배정하는 중… (다른 과목 일정은 최대한 유지)"):
                    res = state.run_schedule(previous=before_sched, focus=set(targets), dataset=new_ds, requests=new_reqs)
                if res.ok:
                    after = state.current_report()
                    S.change_log.append(dict(
                        prof=pid, code=code, targets=targets, text=pend["text"], mode=pend["mode"],
                        summary=req.summary, before=before_sched, after=S.schedule.copy(),
                        before_metrics=before_metrics, after_metrics=dict(after.metrics), solve_time=res.solve_time,
                        time=datetime.now().strftime("%H:%M:%S"), confirmed=before_conf, before_reqs=before_reqs,
                        before_minutes=c.exam_minutes))
                    S.pending.pop(code, None)
                    st.toast(f"재배정 완료 · {res.solve_time:.1f}초", icon="✅")
                    st.rerun()
                else:
                    st.error(f"**재배정 실패 — {res.status}**. 기존 일정은 그대로 유지됩니다.")
                    for m in res.messages:
                        st.markdown(f"- {m}")

# ---------------------------------------------------------------------------
# 변경 전/후 비교
# ---------------------------------------------------------------------------
logs = [x for x in S.change_log if x["prof"] == pid]
if logs:
    lg = logs[-1]
    st.markdown("### 변경 전 / 후 비교")
    with st.container(border=True):
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
        if lg["code"] in a.index and lg["code"] not in S.confirmed:
            st.markdown("<div class='sg-muted'>새 일정이 마음에 들면 위의 과목 카드에서 <b>확정</b>을 눌러 주세요. "
                        "확정하면 수강생에게 알림이 갑니다.</div>", unsafe_allow_html=True)
        if st.button("↩️ 변경 전으로 되돌리기", key="undo"):
            S.schedule = lg["before"]
            S.change_log = [x for x in S.change_log if x is not lg]
            S.requests = dict(lg["before_reqs"])
            if lg.get("before_minutes") and cm[lg["code"]].exam_minutes != lg["before_minutes"]:
                S.ds = S.ds.with_course_update(lg["code"], exam_minutes=int(lg["before_minutes"]))
            S.report = None
            st.rerun()
