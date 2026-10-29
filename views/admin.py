"""관리자 대시보드: 학기·우선순위, 데이터 준비, 전체 배정, 핵심 지표, 무작위 배정 대비 비교."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.config import DEPT_COLORS, DEPARTMENTS
from core.csvio import (
    CheckResult,
    assemble,
    dataset_zip_bytes,
    parse_table,
    read_zip,
    template_csv,
    to_csv_bytes,
)
from core.datagen import GenConfig, generate
from core.dataset import SCHEMAS, TABLE_LABELS
from core.priority import dept_weights, priority_order, semester_label, semester_options
from core.settings import Settings, default_week_start
from core.timeutil import hm_to_min, min_to_hm
from ui import state
from ui.style import BORDER, MUTED, NAVY, badge, hero, metric_cards
from ui.tables import korean, schedule_export, schedule_table

S = st.session_state
ds = S.ds

hero("ADMIN", "관리자 대시보드",
     "수강신청이 끝난 학생 시간표와 교수 일정을 대조해, 충돌 없는 시험 일정과 강의실을 자동으로 배정합니다.")

# ---------------------------------------------------------------------------
# 학기 설정 + 우선순위
# ---------------------------------------------------------------------------
left, right = st.columns([1.05, 1], gap="large")
with left:
    with st.container(border=True):
        st.markdown("#### 학기 · 시험 기간")
        opts = semester_options()
        c1, c2 = st.columns(2)
        sem = c1.selectbox("학기", opts, index=opts.index(S.settings.semester),
                           format_func=lambda x: f"{x}학기 ({semester_label(x)})")
        week = c2.date_input("시험 주간 시작일(월요일)",
                             value=S.settings.week_start if sem == S.settings.semester else default_week_start(sem))
        times = [min_to_hm(m) for m in range(7 * 60, 22 * 60 + 1, 30)]
        c3, c4, c5 = st.columns(3)
        ds_start = c3.selectbox("하루 시작", times, index=times.index(min_to_hm(S.settings.day_start)))
        ds_end = c4.selectbox("하루 종료", times, index=times.index(min_to_hm(S.settings.day_end)))
        limit = c5.number_input("풀이 시간 제한(초)", 5, 120, S.settings.time_limit, step=5)
        week = week - timedelta(days=week.weekday())
        new = Settings(semester=sem, day_start=hm_to_min(ds_start), day_end=hm_to_min(ds_end),
                       time_limit=int(limit), week_start=week)
        if hm_to_min(ds_end) - hm_to_min(ds_start) < 120:
            st.error("하루 시험 시간은 2시간 이상이어야 합니다.")
        elif new != S.settings:
            changed_rules = (new.semester, new.day_start, new.day_end) != (
                S.settings.semester, S.settings.day_start, S.settings.day_end)
            S.settings = new
            if changed_rules and S.schedule is not None:
                S.stale = True
            S.report = None
            st.rerun()

with right:
    with st.container(border=True):
        st.markdown(f"#### {semester_label(S.settings.semester)} 학과 우선순위")
        st.caption("기준 순서(물리→수학→생물→지리→정보디스플레이→화학)를 학기마다 한 칸씩 순환합니다. "
                   "순위가 높을수록 '되도록 지킬 조건'에 큰 가중치를 받아, 같은 시간대·강의실을 먼저 가져갑니다.")
        w = dept_weights(S.settings.semester)
        cnt = ds.courses["department"].value_counts()
        rows = []
        for i, d in enumerate(priority_order(S.settings.semester)):
            dot = f'<span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:{DEPT_COLORS[d]};margin-right:8px"></span>'
            first = badge("이번 학기 1순위", "ok") if i == 0 else ""
            rows.append(f"<tr><td style='padding:7px 10px;font-weight:800;color:{NAVY}'>{i + 1}</td>"
                        f"<td style='padding:7px 10px'>{dot}{d} {first}</td>"
                        f"<td style='padding:7px 10px;text-align:right'>{w[d]}배</td>"
                        f"<td style='padding:7px 10px;text-align:right;color:{MUTED}'>{int(cnt.get(d, 0))}과목</td></tr>")
        st.markdown(
            f"<table style='width:100%;border-collapse:collapse;font-size:.92rem'>"
            f"<thead><tr style='color:{MUTED};font-size:.78rem;border-bottom:1px solid {BORDER}'>"
            f"<th style='text-align:left;padding:4px 10px'>순위</th><th style='text-align:left;padding:4px 10px'>학과</th>"
            f"<th style='text-align:right;padding:4px 10px'>가중치</th><th style='text-align:right;padding:4px 10px'>과목 수</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>", unsafe_allow_html=True)

st.write("")
tab_run, tab_data = st.tabs(["📊 배정 실행 · 결과", "🗂️ 데이터 준비"])

# ---------------------------------------------------------------------------
# 배정 실행 · 결과
# ---------------------------------------------------------------------------
with tab_run:
    b1, b2, b3 = st.columns([1.3, 1.3, 3])
    run = b1.button("⚡ 전체 배정 실행", type="primary", width="stretch")
    if b2.button("확정·요청 초기화", width="stretch",
                 help="교수 확정, 자연어 요청, 알림을 모두 지우고 처음 상태로 돌립니다."):
        S.requests, S.confirmed, S.notifications, S.change_log = {}, {}, [], []
        S.schedule, S.report = None, None
        run = True
    if S.get("stale") and S.schedule is not None:
        b3.warning("학기·시간 설정이 바뀌었습니다. 전체 배정을 다시 실행해 주세요.")
    if run:
        with st.spinner(f"CP-SAT으로 최적 일정을 찾는 중… (최대 {S.settings.time_limit}초)"):
            res = state.run_schedule()
        S.stale = False
        if res.ok:
            st.toast(f"배정 완료 · {res.status} · {res.solve_time:.1f}초", icon="✅")
    state.ensure_schedule()
    res = S.result
    if res is not None and not res.ok:
        st.error(f"**배정 실패 — {res.status}**")
        for m in res.messages:
            st.markdown(f"- {m}")
        if S.schedule is not None:
            st.info("아래는 마지막으로 성공한 배정 결과입니다.")

    rep = state.current_report()
    if rep is not None:
        m = rep.metrics
        base = state.get_baseline()
        hv = rep.hard_count
        solve_t = res.solve_time if (res and res.ok) else None
        metric_cards([
            dict(label="반드시 지킬 조건 위반", value=hv, unit="건", tone="ok" if hv == 0 else "bad",
                 sub=f"무작위 배정 평균 {base['hard_violations']:.0f}건"),
            dict(label="하루 3과목 이상 학생", value=m["students_3plus"], unit="명", tone="info",
                 sub=f"무작위 배정 평균 {base['students_3plus']:.0f}명"),
            dict(label="연속 시험 학생", value=m["consecutive_students"], unit="명", tone="info",
                 sub=f"간격 30분 미만 · 무작위 {base['consecutive_students']:.0f}명"),
            dict(label="강의실 좌석 활용률", value=f"{m['room_utilization']:.0f}", unit="%", tone="info",
                 sub=f"별도 시험 기준 · 무작위 {base['room_utilization']:.0f}%"),
            dict(label="풀이 시간", value=f"{solve_t:.1f}" if solve_t else "-", unit="초", tone="info",
                 sub=f"{res.status} · 제한 {S.settings.time_limit}초" if res and res.ok else ""),
        ])

        cA, cB = st.columns([1.25, 1], gap="large")
        with cA:
            with st.container(border=True):
                st.markdown("#### 수작업 방식(무작위 배정) 대비 개선")
                st.caption("교수가 각자 자기 일정만 보고 시험 시간을 정했다고 가정한 무작위 배정 20회 평균과 비교")
                labels = ["시간 충돌 학생", "하루 3과목 이상 학생", "연속 시험 학생"]
                bvals = [base["conflict_students"], base["students_3plus"], base["consecutive_students"]]
                ovals = [m["conflict_students"], m["students_3plus"], m["consecutive_students"]]
                fig = go.Figure()
                fig.add_bar(name="수작업(무작위) 평균", y=labels, x=bvals, orientation="h", marker_color="#B8C0D6",
                            text=[f"{v:.0f}명" for v in bvals], textposition="outside",
                            hovertemplate="%{y}<br>수작업 평균 %{x:.1f}명<extra></extra>")
                fig.add_bar(name="시험각", y=labels, x=ovals, orientation="h", marker_color=NAVY,
                            text=[f"{v}명" for v in ovals], textposition="outside",
                            hovertemplate="%{y}<br>시험각 %{x}명<extra></extra>")
                fig.update_layout(barmode="group", height=270, margin=dict(l=10, r=40, t=10, b=10),
                                  bargap=0.35, bargroupgap=0.12, plot_bgcolor="white", paper_bgcolor="white",
                                  legend=dict(orientation="h", y=1.12, x=0),
                                  font=dict(family="Pretendard Variable, Pretendard, sans-serif", size=13),
                                  xaxis=dict(showgrid=True, gridcolor="#EEF0F5", zeroline=False, title="학생 수(명)"),
                                  yaxis=dict(autorange="reversed"))
                fig.update_traces(marker_line_width=0, cliponaxis=False)
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                saved = base["conflict_students"] - m["conflict_students"]
                st.markdown(f"<div class='sg-muted'>시간이 겹치는 학생 <b>{saved:.0f}명</b>을 0명으로, "
                            f"하루 3과목 이상 학생을 <b>{base['students_3plus']:.0f}명 → {m['students_3plus']}명</b>으로 줄였습니다.</div>",
                            unsafe_allow_html=True)
        with cB:
            with st.container(border=True):
                st.markdown("#### 반드시 지킬 조건 검증")
                st.caption("최적화 코드와 별도로 작성한 검증기(validator)가 결과를 다시 검사합니다.")
                from core.validator import HARD_RULES
                br = rep.by_rule()
                for k in ("H1", "H2", "H3", "H4", "H0"):
                    ok = br[k] == 0
                    st.markdown(f"{'✅' if ok else '❌'} {HARD_RULES[k]} — **{br[k]}건**")
                if hv:
                    st.dataframe(rep.violations_df(), hide_index=True, width="stretch")
                st.markdown("#### 학과별 결과")
                st.dataframe(pd.DataFrame(m["dept_table"]), hide_index=True, width="stretch",
                             column_config={"좌석활용률": st.column_config.NumberColumn(format="%.1f%%")})

        with st.container(border=True):
            st.markdown("#### 시험 일정표")
            tbl = schedule_table(ds, S.schedule, S.settings)
            f1, f2, f3 = st.columns([1.2, 1, 1])
            q = f1.text_input("검색", placeholder="과목명·교수·강의실", label_visibility="collapsed")
            dsel = f2.multiselect("학과", DEPARTMENTS, placeholder="학과 전체", label_visibility="collapsed")
            ssel = f3.multiselect("상태", ["추천", "확정"], placeholder="상태 전체", label_visibility="collapsed")
            if q:
                mask = tbl.apply(lambda r: q in " ".join(map(str, r.values)), axis=1)
                tbl = tbl[mask]
            if dsel:
                tbl = tbl[tbl["학과"].isin(dsel)]
            if ssel:
                tbl = tbl[tbl["상태"].isin(ssel)]
            st.dataframe(tbl, hide_index=True, width="stretch", height=420,
                         column_config={"순위": st.column_config.NumberColumn(width="small"),
                                        "수용": st.column_config.NumberColumn(width="small"),
                                        "수강": st.column_config.NumberColumn(width="small")})
            e1, e2, _ = st.columns([1, 1, 3])
            exp = schedule_export(ds, S.schedule, S.settings)
            e1.download_button("일정표 CSV 다운로드", to_csv_bytes(exp), "exam_schedule.csv", "text/csv",
                               width="stretch")
            e2.download_button("데이터+일정 ZIP", dataset_zip_bytes(ds, {"exam_schedule": exp}),
                               "siheomgak_export.zip", "application/zip", width="stretch")

# ---------------------------------------------------------------------------
# 데이터 준비
# ---------------------------------------------------------------------------
with tab_data:
    summ = ds.summary()
    metric_cards([dict(label=k, value=v, tone="info") for k, v in list(summ.items())[:5]])
    st.caption(f"현재 데이터: {ds.meta.get('source')}" + (f" (시드 {ds.meta['seed']})" if "seed" in ds.meta else "")
               + f" · 시험 방식: 수업시간 {summ['수업시간 시험']} / 별도 {summ['별도 시험']} / 없음 {summ['시험 없음']}")

    g, u = st.columns(2, gap="large")
    with g:
        with st.container(border=True):
            st.markdown("#### 가상 데이터 생성")
            st.caption("랜덤 시드가 같으면 항상 같은 데이터가 만들어집니다.")
            cfg = S.gen_cfg
            with st.form("gen"):
                a1, a2 = st.columns(2)
                seed = a1.number_input("랜덤 시드", 0, 99999, cfg.seed)
                n_st = a2.number_input("학생 수", 50, 3000, cfg.n_students, step=50)
                a3, a4, a5 = st.columns(3)
                n_co = a3.number_input("과목 수", 6, 60, cfg.n_courses)
                n_pr = a4.number_input("교수 수", 6, 60, cfg.n_professors)
                n_ro = a5.number_input("강의실 수", 10, 120, cfg.n_rooms)
                go_gen = st.form_submit_button("가상 데이터 생성", type="primary", width="stretch")
            if go_gen:
                new_cfg = GenConfig(seed=int(seed), n_students=int(n_st), n_courses=int(n_co),
                                    n_professors=int(n_pr), n_rooms=int(n_ro))
                try:
                    state.set_dataset(generate(new_cfg), new_cfg)
                    st.success("새 가상 데이터를 만들었습니다. '배정 실행' 탭에서 배정을 실행하세요.")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(f"데이터 생성 실패: {e}")
    with u:
        with st.container(border=True):
            st.markdown("#### CSV 업로드")
            st.caption("5개 CSV를 ZIP으로 묶거나, 바꾸고 싶은 표만 골라 올리세요. 올리지 않은 표는 현재 데이터를 유지합니다.")
            files = st.file_uploader("CSV 또는 ZIP", type=["csv", "zip"], accept_multiple_files=True,
                                     label_visibility="collapsed")
            if files and st.button("업로드한 데이터 적용", type="primary", width="stretch"):
                res = CheckResult()
                tables = dict(ds.tables())
                for f in files:
                    raw = f.getvalue()
                    name = f.name.lower()
                    if name.endswith(".zip"):
                        t, r = read_zip(raw)
                        tables.update(t)
                        res.extend(r)
                        continue
                    key = next((t for t in SCHEMAS if name.startswith(t)), None)
                    if key is None:
                        res.errors.append(f"'{f.name}': 파일 이름으로 어떤 표인지 알 수 없습니다. "
                                          "students / courses / professors / rooms / enrollments 중 하나로 시작해야 합니다.")
                        continue
                    df, r = parse_table(key, raw)
                    res.extend(r)
                    if df is not None:
                        tables[key] = df
                if res.ok:
                    new_ds, r2 = assemble(tables)
                    res.extend(r2)
                    if new_ds is not None and r2.ok:
                        state.set_dataset(new_ds)
                        S.upload_msgs = ("ok", res.warnings)
                        st.rerun()
                for e in res.errors:
                    st.error(e)
                for wmsg in res.warnings:
                    st.warning(wmsg)
            msgs = S.pop("upload_msgs", None)
            if msgs:
                st.success("업로드한 데이터를 적용했습니다. '배정 실행' 탭에서 배정을 실행하세요.")
                for wmsg in msgs[1]:
                    st.warning(wmsg)

    with st.container(border=True):
        st.markdown("#### 다운로드 · 템플릿")
        st.download_button("현재 데이터 전체 ZIP 다운로드", dataset_zip_bytes(ds), "siheomgak_data.zip",
                           "application/zip", type="primary")
        st.caption("빈 템플릿(헤더만 있는 CSV) — 다른 AI 도구로 데이터를 만들 때 이 형식을 쓰세요.")
        cols = st.columns(5)
        for i, t in enumerate(SCHEMAS):
            cols[i].download_button(f"📄 {TABLE_LABELS[t]}", template_csv(t), f"{t}.csv", "text/csv",
                                    width="stretch", key=f"tpl_{t}")
        with st.expander("CSV 컬럼 설명"):
            for t, sch in SCHEMAS.items():
                st.markdown(f"**{t}.csv — {TABLE_LABELS[t]}**")
                st.dataframe(pd.DataFrame([{"컬럼": c, "한국어": k, "필수": "필수" if r else "선택", "설명": d, "예시": ex}
                                           for c, k, _t, r, d, ex in sch]), hide_index=True, width="stretch")

    with st.container(border=True):
        st.markdown("#### 데이터 미리보기")
        t = st.segmented_control("표", list(SCHEMAS), default="courses", format_func=lambda x: TABLE_LABELS[x],
                                 label_visibility="collapsed")
        t = t or "courses"
        df = ds.tables()[t]
        st.dataframe(korean(df, t), hide_index=True, width="stretch", height=360)
        st.download_button(f"{TABLE_LABELS[t]} CSV 다운로드", to_csv_bytes(df), f"{t}.csv", "text/csv", key=f"dl_{t}")
