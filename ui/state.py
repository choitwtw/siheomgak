"""세션 상태 관리: 데이터·설정·배정 결과·확정·알림을 한곳에서 다룬다.

관리자·교수·학생 화면이 같은 브라우저 세션 안에서 상태를 공유한다 (시연용 시뮬레이션).
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from core.baseline import baseline_metrics
from core.config import EXAM_IN_CLASS, EXAM_SEPARATE
from core.constraints import CourseRequest
from core.datagen import GenConfig, generate
from core.dataset import Dataset
from core.scheduler import Assignment, SolveResult, solve
from core.settings import Settings
from core.timeutil import min_to_hm
from core.validator import Report, validate

S = st.session_state


def init_state():
    if "ds" in S:
        return
    S.ds = generate(GenConfig())
    S.gen_cfg = GenConfig()
    S.settings = Settings()
    _reset_work()


def _reset_work():
    S.requests = {}            # 과목코드 -> CourseRequest (교수 추가 조건)
    S.confirmed = {}           # 과목코드 -> Assignment
    S.schedule = None          # 현재 배정 결과 DataFrame
    S.result = None            # 마지막 SolveResult
    S.report = None            # 현재 schedule 의 검증 결과
    S.notifications = []       # 학생 알림
    S.change_log = []          # 교수 재배정 기록 (변경 전/후)
    S.baseline = None
    S.data_version = S.get("data_version", 0) + 1
    S.pending = {}             # 교수 화면: 확인 대기 중인 변환 결과


def set_dataset(ds: Dataset, cfg: GenConfig | None = None):
    S.ds = ds
    if cfg is not None:
        S.gen_cfg = cfg
    _reset_work()


def ds() -> Dataset:
    return S.ds


def settings() -> Settings:
    return S.settings


def run_schedule(previous: pd.DataFrame | None = None, focus: set[str] | None = None,
                 dataset: Dataset | None = None, requests: dict | None = None) -> SolveResult:
    """배정 실행. 성공하면 상태에 반영, 실패하면 이전 결과를 유지하고 SolveResult 만 돌려준다."""
    d = dataset or S.ds
    reqs = S.requests if requests is None else requests
    res = solve(d, S.settings, requests=reqs, confirmed=S.confirmed, previous=previous, focus=focus)
    S.result = res
    if res.ok:
        S.ds = d
        S.requests = reqs
        S.schedule = res.schedule
        S.report = validate(d, res.schedule, S.settings, reqs, S.confirmed)
    return res


def ensure_schedule():
    if S.schedule is None:
        with st.spinner("시험 일정을 처음으로 배정하고 있습니다… (최대 %d초)" % S.settings.time_limit):
            run_schedule()


def current_report() -> Report | None:
    if S.schedule is None:
        return None
    if S.report is None:
        S.report = validate(S.ds, S.schedule, S.settings, S.requests, S.confirmed)
    return S.report


def get_baseline() -> dict:
    key = (S.data_version, S.settings.day_start, S.settings.day_end)
    if S.baseline is None or S.baseline[0] != key:
        S.baseline = (key, baseline_metrics(S.ds, S.settings, runs=20))
    return S.baseline[1]


def exam_row(code: str):
    if S.schedule is None:
        return None
    s = S.schedule[S.schedule.course_code == code]
    return None if s.empty else s.iloc[0]


def slot_text(day: int, start: int, end: int | None = None, with_date: bool = True) -> str:
    st_ = S.settings
    base = st_.date_label(day) if with_date else "월화수목금"[day] + "요일"
    t = f"{base} {min_to_hm(start)}"
    if end is not None:
        t += f"~{min_to_hm(end)}"
    return t


def confirm(code: str) -> bool:
    row = exam_row(code)
    if row is None:
        return False
    S.confirmed[code] = Assignment(int(row.day), int(row.start), str(row.room_id))
    sch = S.schedule.copy()
    sch.loc[sch.course_code == code, "locked"] = True
    S.schedule = sch
    S.report = None
    c = S.ds.course_map[code]
    d = S.settings.date_of(int(row.day))
    h, m = divmod(int(row.start), 60)
    when = f"{d.month}월 {d.day}일 {h}시" + (f" {m}분" if m else "")
    room = S.ds.room_map.get(row.room_id)
    where = f"{room.building} {room.room_no}호" if room else str(row.room_id)
    text = f"{c.name} 과목 시험이 {when} {where}로 확정되었습니다. (시험 시간 {int(row.end) - int(row.start)}분)"
    now = datetime.now().strftime("%m/%d %H:%M")
    for sid in S.ds.students_of.get(code, []):
        S.notifications.append(dict(student_id=sid, course_code=code, text=text, time=now, read=False))
    return True


def unconfirm(code: str):
    S.confirmed.pop(code, None)
    if S.schedule is not None:
        sch = S.schedule.copy()
        sch.loc[sch.course_code == code, "locked"] = False
        S.schedule = sch
    S.report = None


def set_request(code: str, req: CourseRequest | None):
    reqs = dict(S.requests)
    if req is None or req.is_empty():
        reqs.pop(code, None)
    else:
        reqs[code] = req
    return reqs


def exam_courses() -> list[str]:
    return [c.code for c in S.ds.course_map.values() if c.exam_type in (EXAM_IN_CLASS, EXAM_SEPARATE)]
