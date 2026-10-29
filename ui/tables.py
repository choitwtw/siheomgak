"""화면 표시·내보내기용 표 변환."""
from __future__ import annotations

import html

import pandas as pd

from core.config import DEPT_COLORS, EXAM_NONE, EXAM_TYPE_LABEL, GENERAL_DEPT
from core.dataset import Dataset, korean_labels
from core.priority import dept_rank
from core.settings import Settings
from core.timeutil import min_to_hm


def type_label(c) -> str:
    if c.dept == GENERAL_DEPT:
        return "교양(외부 과목)"
    return EXAM_TYPE_LABEL[c.exam_type]


def schedule_table(ds: Dataset, schedule: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    cm, pm, rm = ds.course_map, ds.prof_map, ds.room_map
    rank = dept_rank(settings.semester)
    rows = []
    for r in schedule.sort_values(["day", "start", "room_id"]).itertuples(index=False):
        c = cm[r.course_code]
        room = rm.get(r.room_id)
        rows.append({
            "과목코드": c.code, "과목명": c.name, "학과": c.dept, "순위": rank.get(c.dept),
            "교수": pm[c.prof].name if c.prof in pm else c.prof,
            "방식": type_label(c),
            "날짜": settings.date_label(int(r.day)),
            "시간": f"{min_to_hm(r.start)}~{min_to_hm(r.end)}",
            "강의실": r.room_id, "수용": room.capacity if room else None, "수강": c.enrollment,
            "상태": "확정" if r.locked else "추천",
        })
    return pd.DataFrame(rows)


def schedule_export(ds: Dataset, schedule: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """CSV 내보내기용 (영문 컬럼 + 사람이 읽는 값)"""
    cm, rm = ds.course_map, ds.room_map
    out = []
    for r in schedule.sort_values(["day", "start"]).itertuples(index=False):
        c = cm[r.course_code]
        out.append(dict(course_code=c.code, course_name=c.name, department=c.dept, professor_id=c.prof,
                        exam_type=c.exam_type, date=settings.date_of(int(r.day)).isoformat(),
                        day=settings.day_name(int(r.day)), start=min_to_hm(r.start), end=min_to_hm(r.end),
                        minutes=int(r.end) - int(r.start), room_id=r.room_id,
                        room_capacity=rm[r.room_id].capacity if r.room_id in rm else None,
                        enrollment=c.enrollment, confirmed=bool(r.locked)))
    return pd.DataFrame(out)


def room_timetable(ds: Dataset, schedule: pd.DataFrame, settings: Settings, confirmed: dict) -> pd.DataFrame:
    """강의실별 시험 기간 시간표: 시험 + 진행 중인 정규 수업(시험 없음 과목, 교양 제외).
    day_idx·start_min·end_min 컬럼은 화면 계산용."""
    cm, pm, rm = ds.course_map, ds.prof_map, ds.room_map
    rows = []

    def add(rid, day, s, e, c, kind, status):
        room = rm.get(rid)
        rows.append({
            "건물": room.building if room else "", "강의실": rid, "수용": room.capacity if room else None,
            "날짜": settings.date_of(day).isoformat(), "요일": settings.day_name(day),
            "시작": min_to_hm(s), "종료": min_to_hm(e), "종류": kind,
            "과목코드": c.code, "과목": c.name, "학과": c.dept,
            "교수": pm[c.prof].name if c.prof in pm else c.prof, "수강": c.enrollment, "상태": status,
            "day_idx": day, "start_min": s, "end_min": e,
        })

    for r in schedule.itertuples(index=False):
        c = cm[r.course_code]
        add(r.room_id, int(r.day), int(r.start), int(r.end), c, "시험", "확정" if r.course_code in confirmed else "추천")
    for c in cm.values():
        if c.exam_type == EXAM_NONE and c.dept != GENERAL_DEPT:
            for d, s, e in settings.class_blocks(c):
                add(c.room, d, s, e, c, "정규 수업", "-")
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(["건물", "강의실", "day_idx", "start_min"]).reset_index(drop=True)


def room_timetable_html(ds: Dataset, rt: pd.DataFrame, settings: Settings) -> str:
    """인쇄용 HTML — 시험이 있는 강의실마다 한 쪽."""
    exam = rt[rt["종류"] == "시험"]
    rooms = list(dict.fromkeys(exam["강의실"]))
    pages = []
    for rid in rooms:
        rows = rt[rt["강의실"] == rid]
        head = "".join(f"<th>{settings.short_label(k)}</th>" for k in range(settings.n_days))
        cells = []
        for k in range(settings.n_days):
            items = rows[rows["day_idx"] == k]
            parts = []
            for r in items.itertuples(index=False):
                color = DEPT_COLORS.get(r.학과, "#868E96")
                tag = "" if r.종류 == "시험" else " <i>(정규 수업)</i>"
                mark = " ✔" if r.상태 == "확정" else (" (추천)" if r.종류 == "시험" else "")
                parts.append(f"<div class='it' style='border-left-color:{color}'><b>{r.시작}–{r.종료}</b><br>"
                             f"{html.escape(r.과목)}{mark}{tag}<br><span>{html.escape(r.교수)} · {r.수강}명</span></div>")
            cells.append(f"<td>{''.join(parts) or '–'}</td>")
        cap = int(rows["수용"].iloc[0]) if len(rows) else ""
        pages.append(f"<section><h2>{html.escape(rid)} <small>{cap}석</small></h2>"
                     f"<table><thead><tr>{head}</tr></thead><tbody><tr>{''.join(cells)}</tr></tbody></table></section>")
    title = f"시험 기간 강의실별 시간표 ({settings.period_label()})"
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body{{font-family:"Pretendard","Apple SD Gothic Neo","Malgun Gothic",sans-serif;color:#171C2B;margin:24px}}
h1{{font-size:20px}} h2{{font-size:17px;margin:0 0 8px}} h2 small{{color:#6B7385;font-weight:500}}
section{{page-break-after:always;margin-bottom:28px}}
table{{border-collapse:collapse;width:100%;table-layout:fixed}}
th,td{{border:1px solid #D8DDE8;padding:6px;vertical-align:top;font-size:12px}}
th{{background:#F1F3F8}}
.it{{border-left:4px solid;padding:3px 6px;margin-bottom:6px;background:#F8F9FC}}
.it span{{color:#6B7385}}
</style></head><body><h1>{html.escape(title)}</h1>
<p>✔ = 교수 확정 · (추천) = 아직 확정 전 · 생성: 시험각</p>{''.join(pages)}</body></html>"""


def korean(df: pd.DataFrame, table: str) -> pd.DataFrame:
    return df.rename(columns=korean_labels(table))
