"""시험 일정·강의실 배정 엔진 (Google OR-Tools CP-SAT).

모델 개요
- 시험이 있는 과목 c 마다 후보 시작 시각 t 에 대한 0/1 변수 x[c,t], 강의실 r 에 대한 0/1 변수 y[c,r].
  · 별도 시험: 시험 기간 전체에서 30분 단위 후보, 조건에 맞는 모든 강의실 후보
  · 수업시간 시험: 시험 주간의 정규 수업 회차(예: 월·수 10:30)만 후보, 강의실은 정규 강의실로 고정
- 시작 변수 s_c = Σ t·x[c,t] 로 interval 변수를 만들고 NoOverlap 으로 겹침을 금지한다.
  · 수강생을 공유하는 과목 쌍, 같은 교수 과목 쌍 → NoOverlap
  · 강의실별 → 선택적(optional) interval NoOverlap (+ 시험 없음 과목 정규 수업의 고정 점유)
- 시험 없음 과목의 정규 수업(학생·교수·강의실 점유)과 교수 불가 시간은 후보를 만들 때 미리 걸러 낸다.
- 되도록 지킬 조건은 벌점(기본 가중치 × 학과 우선순위 배수)의 합을 최소화한다.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd
from ortools.sat.python import cp_model

from .config import (
    CONSECUTIVE_GAP_MIN,
    EXAM_IN_CLASS,
    EXAM_NONE,
    EXAM_SEPARATE,
    MAX_EXAMS_PER_DAY,
    SLOT_MINUTES,
    STALL_SEC,
    W_AVOID,
    W_CONSECUTIVE,
    W_OVERLOAD,
    W_PREFERENCE,
    W_ROOM_WASTE,
    W_STABILITY,
)
from .constraints import CourseRequest
from .dataset import Course, Dataset
from .priority import dept_weights
from .settings import Settings
from .timeutil import DAY_MINUTES, min_to_hm

SCHEDULE_COLUMNS = ["course_code", "day", "start", "end", "room_id", "exam_type", "locked"]


@dataclass
class Assignment:
    day: int
    start: int
    room: str


@dataclass
class SolveResult:
    ok: bool
    status: str                         # "최적해" / "실행 가능해" / "해 없음" / "시간 초과"
    schedule: pd.DataFrame | None
    solve_time: float
    objective: float | None = None
    messages: list[str] = field(default_factory=list)   # 해가 없을 때 원인 (한국어)
    stats: dict = field(default_factory=dict)


def _overlap(d1, s1, e1, d2, s2, e2) -> bool:
    return d1 == d2 and s1 < e2 and s2 < e1


def exam_duration(c: Course) -> int:
    return c.in_class_exam_minutes if c.exam_type == EXAM_IN_CLASS else c.exam_minutes


def class_items(ds: Dataset, settings: Settings) -> dict[str, list[tuple[int, int, int]]]:
    """시험 없음(교양 포함) 과목의 시험 기간 정규 수업: (시험일, 시작, 종료). 학생·교수·강의실을 고정 점유"""
    return {c.code: settings.class_blocks(c) if c.exam_type == EXAM_NONE else [] for c in ds.course_map.values()}


@dataclass
class _Flags:
    use_requests: bool = True
    use_confirmed: bool = True
    use_prof_unavail: bool = True
    use_rooms: bool = True
    use_students: bool = True
    objective: bool = True


class _Builder:
    def __init__(self, ds: Dataset, settings: Settings, requests: dict[str, CourseRequest],
                 confirmed: dict[str, Assignment], previous: pd.DataFrame | None,
                 focus: set[str], flags: _Flags):
        self.ds, self.st, self.req, self.conf = ds, settings, requests, confirmed
        self.prev, self.focus, self.f = previous, focus, flags
        self.cm = ds.course_map
        self.weights = dept_weights(settings.semester)
        self.fixed = class_items(ds, settings)
        self.exam_courses = [c for c in self.cm.values() if c.exam_type in (EXAM_IN_CLASS, EXAM_SEPARATE)]
        self.diag: list[str] = []

    # ---- 후보 시각 ----
    def _busy(self, c: Course):
        """c 의 교수·수강생이 시험 없음 과목 정규 수업으로 묶여 있는 시간"""
        prof_fixed = [b for code in self.ds.prof_courses.get(c.prof, []) if code != c.code for b in self.fixed[code]]
        stu_fixed = set()
        if self.f.use_students:
            for sid in self.ds.students_of.get(c.code, []):
                for code in self.ds.courses_of[sid]:
                    if code != c.code:
                        stu_fixed.update(self.fixed[code])
        return prof_fixed, stu_fixed

    def candidate_times(self, c: Course, explain: bool = False):
        st = self.st
        dur = exam_duration(c)
        prof = self.ds.prof_map.get(c.prof)
        req = self.req.get(c.code) if self.f.use_requests else None
        prof_fixed, stu_fixed = self._busy(c)
        if c.exam_type == EXAM_IN_CLASS:
            grid = [(d, s) for d, s, _e in st.in_class_options(c)]
        else:
            grid = [(d, m) for d in range(st.n_days) for m in range(st.day_start, st.day_end - dur + 1, SLOT_MINUTES)]
        out = []
        reasons: dict[str, int] = defaultdict(int)
        for d, m in grid:
            e = m + dur
            # 교수 기본 불가 시간은 별도 시험에만 (수업시간 시험은 원래 수업 시간이므로)
            if (c.exam_type == EXAM_SEPARATE and self.f.use_prof_unavail and prof
                    and any(st.hits(w, d, m, e) for w in prof.unavailable)):
                reasons["교수 불가 시간"] += 1
                continue
            if req and any(st.hits(w, d, m, e) for w in req.unavailable):
                reasons["교수님이 추가한 불가 조건"] += 1
                continue
            if req and req.allowed and not any(st.inside(w, d, m, e) for w in req.allowed):
                reasons["'이 시간에만' 조건"] += 1
                continue
            if any(_overlap(d, m, e, fd, fs, fe) for fd, fs, fe in prof_fixed):
                reasons["교수 본인의 다른 수업"] += 1
                continue
            if any(_overlap(d, m, e, fd, fs, fe) for (fd, fs, fe) in stu_fixed):
                reasons["수강생의 정규 수업(시험 없음·교양 과목)"] += 1
                continue
            out.append((d, m))
        if explain:
            return out, len(grid), dict(reasons)
        return out

    def candidate_rooms(self, c: Course):
        if c.exam_type == EXAM_IN_CLASS:
            return [c.room]
        req = self.req.get(c.code) if self.f.use_requests else None
        out = []
        for r in self.ds.room_map.values():
            if r.capacity < c.enrollment or not r.allows(c.dept):
                continue
            if req:
                if req.min_capacity and r.capacity < req.min_capacity:
                    continue
                if req.building and req.building not in r.building:
                    continue
                if req.room_ids and r.rid not in req.room_ids:
                    continue
            out.append(r.rid)
        return out

    # ---- 모델 ----
    def build(self):
        m = cp_model.CpModel()
        self.m = m
        cm, ds = self.cm, self.ds
        obj = []
        self.x: dict[str, dict[tuple[int, int], cp_model.IntVar]] = {}
        self.y: dict[str, dict[str, cp_model.IntVar]] = {}
        self.iv: dict[str, cp_model.IntervalVar] = {}
        self.svar: dict[str, cp_model.IntVar] = {}
        self.ok_build = True

        for c in self.exam_courses:
            conf = self.conf.get(c.code) if self.f.use_confirmed else None
            if conf:
                times, rooms = [(conf.day, conf.start)], [conf.room]
            else:
                times = self.candidate_times(c)
                rooms = self.candidate_rooms(c)
            if not self.f.use_rooms:
                rooms = []
            if not times:
                self.ok_build = False
                _, total, reasons = self.candidate_times(c, explain=True)
                rs = ", ".join(f"{k} {v}개" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]))
                self.diag.append(f"**{c.code} {c.name}** ({exam_duration(c)}분): 가능한 시험 시간이 하나도 없습니다. "
                                 f"후보 {total}개가 모두 제외됨 — {rs}.")
                continue
            if self.f.use_rooms and not rooms:
                self.ok_build = False
                req = self.req.get(c.code)
                extra = f" (추가 조건: {', '.join(req.describe())})" if req and not req.is_empty() else ""
                self.diag.append(f"**{c.code} {c.name}**: 수강인원 {c.enrollment}명을 수용하면서 {c.dept}가 쓸 수 있는 "
                                 f"강의실이 없습니다{extra}.")
                continue
            xs = {(d, t): m.NewBoolVar(f"x_{c.code}_{d}_{t}") for (d, t) in times}
            m.AddExactlyOne(xs.values())
            self.x[c.code] = xs
            gvals = sorted({d * DAY_MINUTES + t for d, t in times})
            s = m.NewIntVarFromDomain(cp_model.Domain.FromValues(gvals), f"s_{c.code}")
            m.Add(s == sum((d * DAY_MINUTES + t) * v for (d, t), v in xs.items()))
            dur = exam_duration(c)
            self.iv[c.code] = m.NewIntervalVar(s, dur, s + dur, f"iv_{c.code}")
            self.svar[c.code] = s
            if rooms:
                ys = {r: m.NewBoolVar(f"y_{c.code}_{r}") for r in rooms}
                m.AddExactlyOne(ys.values())
                self.y[c.code] = ys
        if not self.ok_build:
            return

        codes = [c.code for c in self.exam_courses]
        # ---- 반드시: 학생 공유 / 같은 교수 과목끼리 겹침 금지 ----
        shared: dict[tuple[str, str], int] = defaultdict(int)
        for sid, cs in ds.courses_of.items():
            vs = sorted(c for c in cs if c in self.x)
            for i in range(len(vs)):
                for j in range(i + 1, len(vs)):
                    shared[(vs[i], vs[j])] += 1
        self.shared = shared
        pairs = set(shared) if self.f.use_students else set()
        for i, a in enumerate(codes):
            for b in codes[i + 1:]:
                if cm[a].prof == cm[b].prof:
                    pairs.add(tuple(sorted((a, b))))
        for a, b in pairs:
            m.AddNoOverlap([self.iv[a], self.iv[b]])

        # ---- 반드시: 강의실 같은 시간 중복 금지 (수용인원은 후보에서 이미 거름) ----
        if self.f.use_rooms:
            by_room: dict[str, list] = defaultdict(list)
            for code in codes:
                dur = exam_duration(cm[code])
                for r, yv in self.y[code].items():
                    by_room[r].append(m.NewOptionalIntervalVar(self.svar[code], dur, self.svar[code] + dur, yv,
                                                                f"o_{code}_{r}"))
            for code, blocks in self.fixed.items():
                room = cm[code].room
                for d, s0, e0 in blocks:
                    if room in by_room:
                        by_room[room].append(m.NewFixedSizeIntervalVar(d * DAY_MINUTES + s0, e0 - s0, f"f_{code}_{d}"))
            for ivs in by_room.values():
                if len(ivs) > 1:
                    m.AddNoOverlap(ivs)

        if not self.f.objective:
            return

        w = {code: self.weights.get(cm[code].dept, 1) for code in cm}
        # ---- 되도록 1: 학생 하루 최대 2과목 (같은 과목 조합 학생은 묶어서 계산) ----
        groups: dict[tuple, int] = defaultdict(int)
        for sid, cs in ds.courses_of.items():
            vs = tuple(sorted(c for c in cs if c in self.x))
            if len(vs) > MAX_EXAMS_PER_DAY:
                groups[vs] += 1
        for k, (vs, n) in enumerate(groups.items()):
            gw = max(w[c] for c in vs)
            for d in range(self.st.n_days):
                possible = [c for c in vs if any(dd == d for dd, _t in self.x[c])]
                if len(possible) <= MAX_EXAMS_PER_DAY:
                    continue
                terms = [v for c in possible for (dd, _t), v in self.x[c].items() if dd == d]
                o = m.NewIntVar(0, 7, f"over_{k}_{d}")
                m.Add(sum(terms) <= MAX_EXAMS_PER_DAY + o)
                obj.append(W_OVERLOAD * gw * n * o)

        # ---- 되도록 2: 연속 시험 (같은 날 간격 30분 미만) ----
        def adjacent(d1, s1, e1, d2, s2, e2) -> bool:
            return d1 == d2 and (0 <= s2 - e1 < CONSECUTIVE_GAP_MIN or 0 <= s1 - e2 < CONSECUTIVE_GAP_MIN)

        for (a, b), n in shared.items():
            da, db = exam_duration(cm[a]), exam_duration(cm[b])
            xb = self.x[b]
            cons = []
            for (d1, t1), v1 in self.x[a].items():
                nb = [v2 for (d2, t2), v2 in xb.items() if adjacent(d1, t1, t1 + da, d2, t2, t2 + db)]
                if nb:
                    cons.append((v1, nb))
            if not cons:
                continue
            adj = m.NewBoolVar(f"adj_{a}_{b}")
            for v1, nb in cons:
                m.Add(adj >= v1 + sum(nb) - 1)
            obj.append(W_CONSECUTIVE * n * max(w[a], w[b]) * adj)

        # ---- 되도록 3: 교수 선호 시간 / 피할 시간 ----
        #  (수업시간 시험은 교수 기본 선호는 적용하지 않고, 교수가 추가로 요청한 선호만 적용)
        for code in codes:
            c = cm[code]
            prof = ds.prof_map.get(c.prof)
            req = self.req.get(code) if self.f.use_requests else None
            if req and req.preferred:
                pref = list(req.preferred)
            elif c.exam_type == EXAM_SEPARATE and prof:
                pref = list(prof.preferred)
            else:
                pref = []
            avoid = list(req.avoid) if req else []
            dur = exam_duration(c)
            # 교수가 직접 요청한 선호는 기본 선호보다 2배 강하게
            wp = W_PREFERENCE * w[code] * (2 if (req and req.preferred) else 1)
            for (d, t), v in self.x[code].items():
                if pref and not any(self.st.inside(p, d, t, t + dur) for p in pref):
                    obj.append(wp * v)
                if avoid and any(self.st.hits(a, d, t, t + dur) for a in avoid):
                    obj.append(W_AVOID * w[code] * v)

        # ---- 되도록 4: 강의실 크기 적정화 (남는 좌석 10석 단위) ----
        if self.f.use_rooms:
            rm = ds.room_map
            for code in codes:
                if len(self.y[code]) < 2:
                    continue
                c = cm[code]
                for r, yv in self.y[code].items():
                    waste = rm[r].capacity - c.enrollment
                    if waste > 0:
                        obj.append(W_ROOM_WASTE * w[code] * ((waste + 5) // 10) * yv)

        # ---- 재배정 안정성: 직전 일정 유지 선호 + 힌트 ----
        if self.prev is not None and len(self.prev):
            prev = {r.course_code: r for r in self.prev.itertuples(index=False)}
            for code in codes:
                p = prev.get(code)
                if p is None:
                    continue
                key = (int(p.day), int(p.start))
                xs = self.x[code]
                if key in xs:
                    m.AddHint(xs[key], 1)
                    if len(xs) > 1:
                        # 수정 대상 과목도 이유 없이 움직이지 않도록 작은 벌점
                        ws = W_STABILITY if code not in self.focus else W_STABILITY // 6
                        obj.append(ws * (1 - xs[key]))
                ys = self.y.get(code, {})
                if p.room_id in ys:
                    m.AddHint(ys[p.room_id], 1)
                    if code not in self.focus and len(ys) > 1:
                        obj.append((W_STABILITY // 3) * (1 - ys[p.room_id]))

        if obj:
            m.Minimize(sum(obj))

    def extract(self, solver: cp_model.CpSolver) -> pd.DataFrame:
        rows = []
        for c in self.exam_courses:
            (d, t) = next(k for k, v in self.x[c.code].items() if solver.Value(v))
            ys = self.y.get(c.code, {})
            r = next((k for k, v in ys.items() if solver.Value(v)), c.room)
            rows.append(dict(course_code=c.code, day=d, start=t, end=t + exam_duration(c), room_id=r,
                             exam_type=c.exam_type, locked=c.code in self.conf))
        return pd.DataFrame(rows, columns=SCHEDULE_COLUMNS)


class _StallWatch(cp_model.CpSolverSolutionCallback):
    """더 좋은 해가 stall_sec 동안 안 나오면 탐색을 멈춘다 (시연 중 대기 시간 단축).
    반드시 지킬 조건은 모든 해에서 지켜지므로, 멈춰도 결과는 항상 유효하다."""

    def __init__(self, solver: cp_model.CpSolver, stall_sec: float):
        super().__init__()
        self.solver, self.stall_sec = solver, stall_sec
        self.last = time.time()
        self.found = 0
        self.stopped_early = False
        self._done = threading.Event()

    def on_solution_callback(self):
        self.found += 1
        self.last = time.time()

    def _watch(self):
        while not self._done.wait(0.2):
            if self.found and time.time() - self.last > self.stall_sec:
                self.stopped_early = True
                self.solver.StopSearch()
                return

    def run(self, model):
        t = threading.Thread(target=self._watch, daemon=True)
        t.start()
        try:
            return self.solver.Solve(model, self)
        finally:
            self._done.set()


def _solver(time_limit: float) -> cp_model.CpSolver:
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = float(time_limit)
    s.parameters.num_workers = max(4, min(8, os.cpu_count() or 4))
    s.parameters.random_seed = 7
    return s


def solve(ds: Dataset, settings: Settings, requests: dict[str, CourseRequest] | None = None,
          confirmed: dict[str, Assignment] | None = None, previous: pd.DataFrame | None = None,
          focus: set[str] | None = None, diagnose: bool = True) -> SolveResult:
    """전체 배정. previous 를 주면 직전 일정을 최대한 유지하며 재배정한다 (focus 과목은 예외)."""
    requests = requests or {}
    confirmed = confirmed or {}
    t0 = time.time()
    if settings.n_days == 0:
        return SolveResult(False, "해 없음", None, 0.0, messages=["시험 기간에 시험 가능한 날이 없습니다. 기간을 다시 설정해 주세요."])
    b = _Builder(ds, settings, requests, confirmed, previous, focus or set(), _Flags())
    b.build()
    if not b.ok_build:
        msgs = ["반드시 지킬 조건을 모두 만족하는 일정이 없습니다."] + b.diag
        return SolveResult(False, "해 없음", None, time.time() - t0, messages=msgs)
    solver = _solver(settings.time_limit)
    watch = _StallWatch(solver, STALL_SEC)
    status = watch.run(b.m)
    el = time.time() - t0
    stats = dict(num_exams=len(b.exam_courses),
                 num_bool=sum(len(v) for v in b.x.values()) + sum(len(v) for v in b.y.values()),
                 wall=round(solver.WallTime(), 2))
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        sched = b.extract(solver)
        if status == cp_model.OPTIMAL:
            label = "최적해"
        elif watch.stopped_early:
            label = f"근사 최적해({STALL_SEC:g}초간 개선 없음)"
        else:
            label = "실행 가능해(시간 제한 도달)"
        return SolveResult(True, label, sched, el, solver.ObjectiveValue(), stats=stats)
    if status == cp_model.INFEASIBLE:
        msgs = ["반드시 지킬 조건을 모두 만족하는 일정이 없습니다."]
        if diagnose:
            msgs += diagnose_infeasible(ds, settings, requests, confirmed)
        return SolveResult(False, "해 없음", None, time.time() - t0, messages=msgs, stats=stats)
    return SolveResult(False, "시간 초과", None, el,
                       messages=[f"{settings.time_limit}초 안에 조건을 만족하는 일정을 찾지 못했습니다. "
                                 "관리자 화면에서 풀이 시간 제한을 늘려 다시 시도해 보세요."], stats=stats)


def _feasible(ds, settings, requests, confirmed, flags: _Flags, limit=5.0) -> bool | None:
    b = _Builder(ds, settings, requests, confirmed, None, set(), flags)
    b.build()
    if not b.ok_build:
        return False
    st = _solver(limit).Solve(b.m)
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return True
    if st == cp_model.INFEASIBLE:
        return False
    return None


def diagnose_infeasible(ds: Dataset, settings: Settings, requests: dict[str, CourseRequest],
                        confirmed: dict[str, Assignment]) -> list[str]:
    """조건 묶음을 하나씩 빼 보면서 어떤 조건 때문에 해가 없는지 찾는다."""
    msgs = []
    cm = ds.course_map
    items = [(k, v) for k, v in confirmed.items() if k in cm]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            (a, x), (b, y) = items[i], items[j]
            ea, eb = x.start + exam_duration(cm[a]), y.start + exam_duration(cm[b])
            if _overlap(x.day, x.start, ea, y.day, y.start, eb):
                common = len(set(ds.students_of[a]) & set(ds.students_of[b]))
                if common or x.room == y.room or cm[a].prof == cm[b].prof:
                    msgs.append(f"확정된 **{a} {cm[a].name}**({settings.date_label(x.day)} {min_to_hm(x.start)})과 "
                                f"**{b} {cm[b].name}**({settings.date_label(y.day)} {min_to_hm(y.start)})이 서로 겹칩니다.")
    tests = [
        ("교수님이 추가한 조건(자연어 요청)", _Flags(use_requests=False, objective=False),
         any(not r.is_empty() for r in requests.values())),
        ("이미 확정된 시험", _Flags(use_confirmed=False, objective=False), bool(confirmed)),
        ("교수 불가 시간", _Flags(use_prof_unavail=False, objective=False), True),
        ("강의실 수·수용인원", _Flags(use_rooms=False, objective=False), True),
    ]
    found = [label for label, fl, applicable in tests
             if applicable and _feasible(ds, settings, requests, confirmed, fl)]
    if found:
        msgs.append("원인 분석: 다음 조건을 빼면 일정이 만들어집니다 → " + ", ".join(f"**{f}**" for f in found)
                    + ". 이 조건을 완화해 보세요.")
    else:
        msgs.append("원인 분석: 특정 조건 하나의 문제가 아니라 학생 시간표 충돌이 많고 시험 기간이 짧은 것이 원인입니다. "
                    "하루 시험 시간대를 늘리거나 일부 과목의 시험 방식을 바꿔 보세요.")
    return msgs
