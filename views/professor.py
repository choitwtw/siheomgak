"""교수 화면: 시험 가능 시간표 확인 → 추천 일정·이유·경고 → 자연어 수정 → 재배정 → 전/후 비교 → (우선순위 차례에) 확정."""
from __future__ import annotations

import html
import json
from datetime import datetime

import pandas as pd
import streamlit as st

from core import llm
from core.config import DAYS, EXAM_IN_CLASS, EXAM_NONE, EXAM_TYPE_LABEL, GENERAL_DEPT
from core.constraints import CourseRequest, validate_request
from core.explain import (
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
from core.timeutil import min_to_hm, windows_to_text
from ui import state
from ui.calendar import legend, week_grid
from ui.style import badge, hero, metric_cards, reason_box, warn_box

S = st.session_state
state.ensure_schedule()
ds = S.ds
S.setdefault("llm_cache", {})

hero("PROFESSOR", "교수 화면",
     "수강생 시간표를 대조한 시험 가능 시간을 확인하고, 추천 일정을 조정해 우선순위 차례에 확정합니다.")

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
pid = st.selectbox("교수 선택", pids, index=pids.index(S.prof_id),
                   format_func=lambda p: f"{rank.get(pm[p].dept)}순위 {pm[p].dept} · {pm[p].name} 교수 ({p})"
                   + ("  ← 확정 차례" if pm[p].dept == turn and S.settings.priority_lock else ""))
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
        st.success(f"지금은 **{rank.get(turn)}순위 {turn}**의 확정 차례입니다. 아래 일정을 확인하고 확정해 주세요.")
    else:
        st.info(f"지금은 **{rank.get(turn)}순위 {turn}**의 확정 차례입니다. {prof.dept}는 상위 학과가 확정을 마친 뒤 "
                "확정할 수 있습니다. 그동안 시험 가능 시간을 확인하고 조건을 조정해 두세요.")
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
# 내 시간표 + 시험 가능 시간 (수강생 전원의 시간표 대조)
# ---------------------------------------------------------------------------
exam_codes = [x for x in my_codes if cm[x].exam_type != EXAM_NONE]
st.markdown("### 📅 내 시간표와 시험 가능 시간")
if exam_codes:
    with st.container(border=True):
        stg = S.settings
        sel = st.segmented_control("과목", exam_codes, default=S.get("avail_code") if S.get("avail_code") in exam_codes
                                   else exam_codes[0], format_func=lambda x: f"{cm[x].name}", key=f"avail_{pid}")
        sel = sel or exam_codes[0]
        S.avail_code = sel
        csel = cm[sel]
        st.caption(f"{csel.name} 수강생 {csel.enrollment}명의 시험 기간 시간표(진행 중인 수업, 교양 수업, 다른 시험)와 "
                   "교수님 일정·강의실을 대조해, 시험을 **시작할 수 있는 시각**을 칸마다 표시했습니다. 칸에 마우스를 올리면 자세히 보입니다.")
        basis = st.radio("기준", ["확정된 일정 기준", "현재 추천안 기준"], horizontal=True, key="avail_basis",
                         help="확정된 일정 기준: 상위 학과가 확정한 시험과 바뀌지 않는 수업(진행 수업·교양·수업시간 시험 회차)만 막고 봅니다. "
                              "현재 추천안 기준: 아직 확정 안 된 다른 과목의 추천 시간까지 막고 봅니다.")
        smap = slot_map(ds, S.schedule, stg, S.requests, sel, fixed_only=basis == "확정된 일정 기준")
        bgs = []
        cell = 30 if csel.exam_type != EXAM_IN_CLASS else None
        for x in smap:
            when = f"{stg.date_label(x['day'])} {min_to_hm(x['start'])} 시작"
            end = x["start"] + cell if cell else x["end"]
            if x["status"] == "ok":
                bgs.append(dict(day=x["day"], start=x["start"], end=end, cls="ok", label="가능",
                                tip=f"{when} — 가능 · 수강생 전원 충돌 없음 · 하루 3과목·연속 시험 0명 · {x['room']}"))
            elif x["status"] == "burden":
                bgs.append(dict(day=x["day"], start=x["start"], end=end, cls="burden", label="△",
                                tip=f"{when} — 가능하지만 하루 3과목 이상 {x['overload']}명 · 연속 시험 {x['consecutive']}명 · {x['room']}"))
            else:
                n = x.get("conflicts", 0)
                heavy = n and n >= max(3, csel.enrollment * 0.1)
                short = f"{n}명" if n else {"교수 불가 시간": "불가", "교수 요청 불가 시간": "요청",
                                            "'이 시간에만' 요청 밖": "–", "교수 본인의 다른 수업·시험": "내일정",
                                            "빈 강의실 없음": "실 없음"}.get(x["reason"], "×")
                bgs.append(dict(day=x["day"], start=x["start"], end=end, cls="heavy" if heavy else "blocked",
                                label=short, tip=f"{when} — 불가: {x['reason']}"))
        evs = []
        for oc in my_codes:
            o = cm[oc]
            if o.exam_type == EXAM_NONE:
                for d, s0, e0 in stg.class_blocks(o):
                    evs.append(dict(day=d, start=s0, end=e0, cls="mine", title=o.name, sub="내 정규 수업(진행)"))
            r0 = state.exam_row(oc)
            if r0 is not None:
                conf = oc in S.confirmed
                evs.append(dict(day=int(r0.day), start=int(r0.start), end=int(r0.end),
                                cls="current" if oc == sel else "dept", color=None if oc == sel else "#5C6B8A",
                                title=f"{o.name} 시험" + (" ✔" if conf else ""),
                                sub=f"{'확정' if conf else '현재 추천'} · {min_to_hm(r0.start)}~{min_to_hm(r0.end)} · {r0.room_id}"))
        n_ok = sum(x["status"] == "ok" for x in smap)
        n_bur = sum(x["status"] == "burden" for x in smap)
        n_stu = sum(bool(x.get("conflicts")) for x in smap)
        metric_cards([
            dict(label="시작 가능한 시각", value=n_ok + n_bur, unit="개", tone="ok",
                 sub=f"부담 없음 {n_ok} · 학생 부담 있음 {n_bur}"),
            dict(label="수강생 시간이 겹치는 시각", value=n_stu, unit="개", tone="info", sub="칸의 숫자 = 겹치는 학생 수"),
            dict(label="시험 시간", value=csel.in_class_exam_minutes if csel.exam_type == EXAM_IN_CLASS else csel.exam_minutes,
                 unit="분", tone="info", sub=EXAM_TYPE_LABEL[csel.exam_type]),
        ])
        st.markdown(legend([("background:#E3F6EE", "가능 (학생 부담 없음)"), ("background:#FFF1DC", "△ 가능 (하루 3과목·연속 시험 발생)"),
                            ("background:#FBE4E4", "N명 = 수강생 시간 겹침"), ("background:#F3F4F7", "교수·강의실 사정으로 불가"),
                            ("background:#1C2E5A", "이 과목 현재 일정"), ("background:#E9ECF2;border:1px solid #D8DDE8", "내 수업")]),
                    unsafe_allow_html=True)
        st.markdown(week_grid(stg, evs, bgs, px_per_min=1.05), unsafe_allow_html=True)
        feas = [x for x in smap if x["status"] != "blocked"]
        if sel in S.confirmed:
            st.caption("확정된 시험입니다. 바꾸려면 아래 과목 카드에서 확정을 취소하세요.")
        elif feas:
            feas.sort(key=lambda x: (x["status"] != "ok", x["day"], x["start"]))
            def feas_label(i: int) -> str:
                x = feas[i]
                burden = "부담 없음" if x["status"] == "ok" else f"하루 3과목 {x['overload']}명·연속 {x['consecutive']}명"
                return (f"{stg.date_label(x['day'])} {min_to_hm(x['start'])}~{min_to_hm(x['end'])} · {burden}"
                        f" · {x['room']}")

            m1, m2 = st.columns([3, 1])
            pick = m1.selectbox("이 시각으로 옮기기", range(len(feas)), label_visibility="collapsed", format_func=feas_label)
            if m2.button("이 시각으로 옮기기", width="stretch", key=f"move_{sel}"):
                x = feas[pick]
                S.edit_code = sel
                S.pending[sel] = dict(
                    req=validate_request({"allowed": [{"day": stg.day_name(x["day"]), "start": min_to_hm(x["start"]),
                                                       "end": min_to_hm(x["end"])}],
                                          "summary": f"{stg.date_label(x['day'])} {min_to_hm(x['start'])} 시작으로 이동"},
                                         source="시간표에서 선택"),
                    mode="시간표에서 선택", note=None, text=f"{stg.date_label(x['day'])} {min_to_hm(x['start'])}로 옮기기",
                    all=False)
                st.rerun()
else:
    st.info("시험이 있는 담당 과목이 없습니다.")

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
            ok_conf, why = state.can_confirm(code)
            if b1.button("✅ 확정", key=f"conf_{code}", type="primary", width="stretch", disabled=not ok_conf):
                state.confirm(code)
                if S.settings.notify_mode == NOTIFY_INSTANT or S.published_at:
                    st.toast(f"{c.name} 시험을 확정했습니다. 수강생 {c.enrollment}명에게 알림을 보냈습니다.", icon="📨")
                else:
                    st.toast(f"{c.name} 시험을 확정했습니다. 관리자가 전체 일정을 발표하면 수강생에게 알림이 갑니다.", icon="✅")
                st.rerun()
            if b2.button("✏️ 조건 바꾸기", key=f"edit_{code}", width="stretch"):
                S.edit_code = code
                st.rerun()
            if not ok_conf:
                st.caption("🔒 " + why)
        else:
            published = state.is_published(code)
            b1.markdown(f"<div style='padding-top:8px'>{badge('학생 발표 완료' if published else '확정 · 발표 대기', 'ok')}</div>",
                        unsafe_allow_html=True)
            if not published and b3.button("확정 취소", key=f"unconf_{code}", width="stretch",
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
                                req=validate_request({"allowed": [{"day": S.settings.day_name(d), "start": min_to_hm(s0),
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
