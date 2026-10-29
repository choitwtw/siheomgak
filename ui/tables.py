"""화면 표시용 표 변환."""
from __future__ import annotations

import pandas as pd

from core.config import EXAM_TYPE_LABEL
from core.dataset import Dataset, korean_labels
from core.priority import dept_rank
from core.settings import Settings
from core.timeutil import min_to_hm


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
            "방식": EXAM_TYPE_LABEL[c.exam_type],
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
                        day="월화수목금"[int(r.day)], start=min_to_hm(r.start), end=min_to_hm(r.end),
                        minutes=int(r.end) - int(r.start), room_id=r.room_id,
                        room_capacity=rm[r.room_id].capacity if r.room_id in rm else None,
                        enrollment=c.enrollment, confirmed=bool(r.locked)))
    return pd.DataFrame(out)


def korean(df: pd.DataFrame, table: str) -> pd.DataFrame:
    return df.rename(columns=korean_labels(table))
