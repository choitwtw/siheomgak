"""세션 상태 관리: 데이터·설정·배정 결과·확정·발표·알림을 한곳에서 다룬다.

관리자·교수·학생 화면이 같은 브라우저 세션 안에서 상태를 공유한다 (시연용 시뮬레이션).

진행 흐름
1) 교수: 수강생 시간표를 대조한 '시험 가능 시간'을 보고 일정을 고른다.
2) 학과 우선순위가 높은 학과부터 시험 일정을 확정한다 (Settings.priority_lock).
3) 관리자: 강의실별 시험 시간표를 확인·출력한다.
4) 관리자: 전체 일정을 발표하면 학생에게 알림이 가고 시간표에 '확정'으로 표시된다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from core.baseline import baseline_metrics
from core.config import EXAM_IN_CLASS, EXAM_SEPARATE, GENERAL_DEPT
from core.constraints import CourseRequest
from core.csvio import CheckResult, assemble, parse_table
from core.datagen import GenConfig, generate
from core.dataset import SCHEMAS, TABLE_LABELS, Dataset
from core.priority import dept_rank, priority_order
from core.scheduler import Assignment, SolveResult, solve
from core.settings import NOTIFY_INSTANT, Settings
from core.timeutil import min_to_hm
from core.validator import Report, validate

S = st.session_state
KST = ZoneInfo("Asia/Seoul")


def now_text() -> str:
    return datetime.now(KST).strftime("%m/%d %H:%M")


STATE_VERSION = 4   # 세션 상태 구조가 바뀌면 올린다


def init_state():
    """앱을 처음 열었을 때, 또는 새 버전이 배포되어 열려 있던 탭의 상태가 옛 구조일 때 새로 만든다."""
    if ("ds" in S and S.get("state_version") == STATE_VERSION
            and isinstance(S.get("settings"), Settings) and isinstance(S.get("ds"), Dataset)):
        return
    S.ds, S.data_load_msgs = load_default_dataset()
    S.gen_cfg = GenConfig()
    S.settings = Settings()
    S.state_version = STATE_VERSION
    _reset_work()


CUSTOM_DIR = Path(__file__).resolve().parent.parent / "data" / "custom"


@st.cache_resource(show_spinner=False)
def _load_custom(signature: tuple):
    """data/custom 폴더의 CSV(있는 것만)를 가상 데이터 위에 덮어써서 기본 데이터로 만든다."""
    base = generate(GenConfig())
    tables = dict(base.tables())
    res = CheckResult()
    used = []
    for t in SCHEMAS:
        f = CUSTOM_DIR / f"{t}.csv"
        if f.exists():
            df, r = parse_table(t, f.read_bytes())
            res.extend(r)
            if df is not None:
                tables[t] = df
                used.append(TABLE_LABELS[t])
    if not used or not res.ok:
        return None, res, used
    ds, r2 = assemble(tables, source="사용자 데이터 (" + ", ".join(used) + ")")
    res.extend(r2)
    return ds, res, used


def load_default_dataset():
    """기본 데이터: data/custom 에 CSV 가 있으면 그것, 없으면 시드 고정 가상 데이터.
    사용자 데이터에 오류가 있으면 앱이 멈추지 않도록 가상 데이터로 시작하고 오류를 관리자 화면에 보여 준다."""
    files = sorted(CUSTOM_DIR.glob("*.csv")) if CUSTOM_DIR.exists() else []
    if not files:
        return generate(GenConfig()), None
    sig = tuple((f.name, f.stat().st_size, f.stat().st_mtime) for f in files)
    ds, res, used = _load_custom(sig)
    if ds is None:
        return generate(GenConfig()), ("error", res.errors[:20])
    return ds, ("ok", res.warnings[:20])


def _reset_work():
    S.requests = {}            # 과목코드 -> CourseRequest (교수 추가 조건)
    S.confirmed = {}           # 과목코드 -> Assignment
    S.published = {}           # 과목코드 -> Assignment (학생에게 발표된 일정)
    S.published_at = None
    S.schedule = None          # 현재 배정 결과 DataFrame
    S.result = None            # 마지막 SolveResult
    S.report = None            # 현재 schedule 의 검증 결과
    S.notifications = []       # 학생 알림
    S.change_log = []          # 교수 재배정 기록 (변경 전/후)
    S.baseline = None
    S.data_version = S.get("data_version", 0) + 1
    S.pending = {}             # 교수 화면: 확인 대기 중인 변환 결과


def reset_work():
    _reset_work()


def set_dataset(ds: Dataset, cfg: GenConfig | None = None):
    S.ds = ds
    if cfg is not None:
        S.gen_cfg = cfg
    _reset_work()


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
        with st.spinner("수강생 시간표와 교수 일정을 대조해 시험 일정을 처음으로 배정하고 있습니다… (최대 %d초)"
                        % S.settings.time_limit):
            run_schedule()


def current_report() -> Report | None:
    if S.schedule is None:
        return None
    if S.report is None:
        S.report = validate(S.ds, S.schedule, S.settings, S.requests, S.confirmed)
    return S.report


def get_baseline() -> dict:
    st_ = S.settings
    key = (S.data_version, st_.day_start, st_.day_end, tuple(st_.exam_dates))
    if S.baseline is None or S.baseline[0] != key:
        S.baseline = (key, baseline_metrics(S.ds, st_, runs=20))
    return S.baseline[1]


def exam_row(code: str):
    if S.schedule is None:
        return None
    s = S.schedule[S.schedule.course_code == code]
    return None if s.empty else s.iloc[0]


def slot_text(day: int, start: int, end: int | None = None, with_date: bool = True) -> str:
    st_ = S.settings
    base = st_.date_label(day) if with_date else st_.day_name(day) + "요일"
    t = f"{base} {min_to_hm(start)}"
    if end is not None:
        t += f"~{min_to_hm(end)}"
    return t


def room_text(rid: str) -> str:
    room = S.ds.room_map.get(rid)
    return f"{room.building} {room.room_no}호" if room else str(rid)


# ---------------------------------------------------------------------------
# 확정 (학과 우선순위 순서)
# ---------------------------------------------------------------------------
def exam_courses() -> list[str]:
    return [c.code for c in S.ds.course_map.values() if c.exam_type in (EXAM_IN_CLASS, EXAM_SEPARATE)]


def dept_progress() -> list[dict]:
    """학과별 확정 현황 (우선순위 순)"""
    cm = S.ds.course_map
    rows = []
    for i, d in enumerate(priority_order(S.settings.semester)):
        codes = [c for c in exam_courses() if cm[c].dept == d]
        done = [c for c in codes if c in S.confirmed]
        rows.append(dict(rank=i + 1, dept=d, codes=codes, done=done, complete=len(done) == len(codes)))
    return rows


def current_turn() -> str | None:
    """지금 확정 차례인 학과 (모두 끝났으면 None)"""
    for r in dept_progress():
        if not r["complete"]:
            return r["dept"]
    return None


def can_confirm(code: str) -> tuple[bool, str]:
    c = S.ds.course_map[code]
    if code in S.confirmed:
        return False, "이미 확정된 시험입니다."
    if not S.settings.priority_lock or c.dept == GENERAL_DEPT:
        return True, ""
    my_rank = dept_rank(S.settings.semester).get(c.dept, 99)
    waiting = [r for r in dept_progress() if r["rank"] < my_rank and not r["complete"]]
    if waiting:
        r = waiting[0]
        left = len(r["codes"]) - len(r["done"])
        return False, (f"우선순위 {r['rank']}위 {r['dept']}의 확정이 끝나야 확정할 수 있습니다 "
                       f"(남은 시험 {left}개). 그동안 시험 가능 시간을 확인하고 조건을 조정해 두세요.")
    return True, ""


def _notice_line(code: str, a: Assignment) -> str:
    c = S.ds.course_map[code]
    d = S.settings.date_of(a.day)
    h, m = divmod(a.start, 60)
    when = f"{d.month}월 {d.day}일({S.settings.day_name(a.day)}) {h}시" + (f" {m}분" if m else "")
    return f"{c.name} — {when}, {room_text(a.room)}"


def confirm(code: str, force: bool = False) -> bool:
    row = exam_row(code)
    if row is None:
        return False
    if not force and not can_confirm(code)[0]:
        return False
    a = Assignment(int(row.day), int(row.start), str(row.room_id))
    S.confirmed[code] = a
    sch = S.schedule.copy()
    sch.loc[sch.course_code == code, "locked"] = True
    S.schedule = sch
    S.report = None
    # 즉시 알림 모드이거나 이미 전체 발표가 끝난 뒤의 추가 확정이면 개별 알림
    if S.settings.notify_mode == NOTIFY_INSTANT or S.published_at:
        _publish_codes([code], title="시험 일정 확정")
    return True


def confirm_dept(dept: str) -> int:
    """학과의 미확정 시험을 현재 추천안으로 모두 확정 (관리자 일괄 확정)"""
    n = 0
    for code in exam_courses():
        if S.ds.course_map[code].dept == dept and code not in S.confirmed:
            if confirm(code, force=True):
                n += 1
    return n


def unconfirm(code: str):
    S.confirmed.pop(code, None)
    if S.schedule is not None:
        sch = S.schedule.copy()
        sch.loc[sch.course_code == code, "locked"] = False
        S.schedule = sch
    S.report = None


# ---------------------------------------------------------------------------
# 발표 · 학생 알림
# ---------------------------------------------------------------------------
def _publish_codes(codes: list[str], title: str):
    cm = S.ds.course_map
    per_student: dict[str, list[str]] = {}
    for code in codes:
        a = S.confirmed[code]
        S.published[code] = a
        for sid in S.ds.students_of.get(code, []):
            per_student.setdefault(sid, []).append(code)
    t = now_text()
    for sid, cs in per_student.items():
        cs = sorted(cs, key=lambda c: (S.confirmed[c].day, S.confirmed[c].start))
        lines = [_notice_line(c, S.confirmed[c]) for c in cs]
        if len(cs) == 1:
            text = f"{cm[cs[0]].name} 과목 시험이 {lines[0].split(' — ')[1]}로 확정되었습니다."
        else:
            text = f"시험 {len(cs)}과목의 일정이 확정·발표되었습니다."
        S.notifications.append(dict(student_id=sid, title=title, text=text, lines=lines, time=t, read=False))


def publish_all() -> tuple[int, int]:
    """확정된 시험 중 아직 발표하지 않은 것을 모두 발표. (과목 수, 알림 받은 학생 수)"""
    codes = [c for c in S.confirmed if c not in S.published]
    before = len(S.notifications)
    if codes:
        _publish_codes(codes, title=f"{S.settings.semester}학기 기말 시험 일정 발표")
    S.published_at = S.published_at or now_text()
    return len(codes), len(S.notifications) - before


def is_published(code: str) -> bool:
    return code in S.published


def set_request(code: str, req: CourseRequest | None):
    reqs = dict(S.requests)
    if req is None or req.is_empty():
        reqs.pop(code, None)
    else:
        reqs[code] = req
    return reqs
