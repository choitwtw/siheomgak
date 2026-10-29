"""배정 결과 독립 검증기.

최적화 엔진(scheduler.py)의 코드를 전혀 쓰지 않고, 데이터와 결과표만 보고
① 반드시 지킬 조건 위반 건수(0이어야 함) 와 ② 품질 지표를 계산한다.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd

from .config import CONSECUTIVE_GAP_MIN, EXAM_IN_CLASS, EXAM_NONE, EXAM_SEPARATE, MAX_EXAMS_PER_DAY
from .constraints import CourseRequest
from .dataset import Dataset
from .priority import dept_rank
from .settings import Settings
from .timeutil import min_to_hm

HARD_RULES = {
    "H1": "학생 시험·수업 시간 겹침",
    "H2": "교수 불가 시간·교수 일정 겹침",
    "H3": "강의실 수용인원·중복 사용",
    "H4": "확정 시험 변경",
    "H0": "배정 누락·시험 기간 이탈",
}


@dataclass
class Item:
    """시험 주간의 한 일정 (시험 또는 진행 중인 정규 수업)"""
    code: str
    kind: str        # "시험" / "수업"
    day: int
    start: int
    end: int
    room: str


@dataclass
class Report:
    violations: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    per_course: dict[str, dict] = field(default_factory=dict)
    student_items: dict[str, list[Item]] = field(default_factory=dict)

    @property
    def hard_count(self) -> int:
        return len(self.violations)

    def by_rule(self) -> dict[str, int]:
        out = {k: 0 for k in HARD_RULES}
        for v in self.violations:
            out[v["rule"]] += 1
        return out

    def violations_df(self) -> pd.DataFrame:
        if not self.violations:
            return pd.DataFrame(columns=["규칙", "내용"])
        return pd.DataFrame([{"규칙": HARD_RULES[v["rule"]], "내용": v["detail"]} for v in self.violations])


def _ov(a: Item, b: Item) -> bool:
    return a.day == b.day and a.start < b.end and b.start < a.end


def week_items(ds: Dataset, schedule: pd.DataFrame, settings: Settings) -> dict[str, list[Item]]:
    """과목별 시험 기간 일정 목록 (결과표 + 시험 없음·교양 과목의 정규 수업). day = 시험일 번호"""
    out: dict[str, list[Item]] = defaultdict(list)
    for r in schedule.itertuples(index=False):
        out[r.course_code].append(Item(r.course_code, "시험", int(r.day), int(r.start), int(r.end), str(r.room_id)))
    for c in ds.course_map.values():
        if c.exam_type == EXAM_NONE:
            for d, s, e in settings.class_blocks(c):
                out[c.code].append(Item(c.code, "수업", d, s, e, c.room))
    return out


def validate(ds: Dataset, schedule: pd.DataFrame, settings: Settings,
             requests: dict[str, CourseRequest] | None = None,
             confirmed: dict | None = None, max_detail: int = 200) -> Report:
    requests = requests or {}
    confirmed = confirmed or {}
    rep = Report()
    cm, pm, rm = ds.course_map, ds.prof_map, ds.room_map
    viol = rep.violations

    def add(rule, detail):
        if len(viol) < max_detail:
            viol.append({"rule": rule, "detail": detail})
        else:
            viol.append({"rule": rule, "detail": "(이하 생략)"})

    items = week_items(ds, schedule, settings)

    def fmt_slot(d, s, e=None):
        t = f"{settings.short_label(d) if 0 <= d < settings.n_days else f'{d + 1}일차'} {min_to_hm(s)}"
        return t + (f"~{min_to_hm(e)}" if e is not None else "")
    exams = {code: [i for i in its if i.kind == "시험"] for code, its in items.items()}

    # ---- H0: 누락·중복·기간 이탈·수업시간 시험 위치 ----
    for c in cm.values():
        n = len(exams.get(c.code, []))
        if c.exam_type in (EXAM_IN_CLASS, EXAM_SEPARATE) and n != 1:
            add("H0", f"{c.code} {c.name}: 시험이 {n}번 배정되었습니다 (1번이어야 함).")
        if c.exam_type == EXAM_NONE and n:
            add("H0", f"{c.code} {c.name}: 시험 없음 과목에 시험이 배정되었습니다.")
        for e in exams.get(c.code, []):
            if c.exam_type == EXAM_SEPARATE:
                if e.end - e.start != c.exam_minutes:
                    add("H0", f"{c.code} {c.name}: 시험 길이 {e.end - e.start}분 ≠ 교수가 정한 {c.exam_minutes}분.")
                if not (settings.day_start <= e.start and e.end <= settings.day_end) or not 0 <= e.day < settings.n_days:
                    add("H0", f"{c.code} {c.name}: 시험 기간·시간({fmt_slot(e.day, e.start, e.end)})을 벗어났습니다.")
            if c.exam_type == EXAM_IN_CLASS:
                if (e.day, e.start, e.end) not in settings.in_class_options(c) or e.room != c.room:
                    add("H0", f"{c.code} {c.name}: 수업시간 시험이 정규 수업 시간·강의실이 아닙니다.")

    # ---- H1: 학생별 겹침 ----
    conflict_students = set()
    for sid, codes in ds.courses_of.items():
        its = [i for c in codes for i in items.get(c, [])]
        rep.student_items[sid] = its
        for a in range(len(its)):
            for b in range(a + 1, len(its)):
                x, y = its[a], its[b]
                if x.code != y.code and _ov(x, y):
                    conflict_students.add(sid)
                    add("H1", f"학생 {sid}: {x.code}({x.kind} {fmt_slot(x.day, x.start, x.end)})과 "
                              f"{y.code}({y.kind} {fmt_slot(y.day, y.start, y.end)})이 겹칩니다.")

    # ---- H2: 교수 ----
    for pid, codes in ds.prof_courses.items():
        p = pm.get(pid)
        its = [i for c in codes for i in items.get(c, [])]
        for e in its:
            if e.kind != "시험":
                continue
            if p and cm[e.code].exam_type == EXAM_SEPARATE:
                for w in p.unavailable:
                    if settings.hits(w, e.day, e.start, e.end):
                        add("H2", f"{e.code}: 교수({p.name}) 불가 시간 {w.to_text()}에 배정되었습니다.")
            req = requests.get(e.code)
            if req:
                for w in req.unavailable:
                    if settings.hits(w, e.day, e.start, e.end):
                        add("H2", f"{e.code}: 교수 요청 불가 시간 {w.to_text()}에 배정되었습니다.")
                if req.allowed and not any(settings.inside(w, e.day, e.start, e.end) for w in req.allowed):
                    add("H2", f"{e.code}: 교수 요청 '이 시간에만' 조건을 벗어났습니다.")
        for a in range(len(its)):
            for b in range(a + 1, len(its)):
                x, y = its[a], its[b]
                if x.code != y.code and _ov(x, y):
                    add("H2", f"교수 {pid}: {x.code}과 {y.code} 일정이 {fmt_slot(x.day, max(x.start, y.start))}에 겹칩니다.")

    # ---- H3: 강의실 ----
    by_room: dict[str, list[Item]] = defaultdict(list)
    for code, its in items.items():
        for i in its:
            by_room[i.room].append(i)
    for code, its in exams.items():
        c = cm[code]
        for e in its:
            r = rm.get(e.room)
            if r is None:
                add("H3", f"{code}: 강의실 '{e.room}'이(가) 존재하지 않습니다.")
                continue
            if c.exam_type == EXAM_SEPARATE and r.exam_capacity < c.enrollment:
                add("H3", f"{code}: 강의실 {r.rid} 시험 좌석 {r.exam_capacity}석 < 수강인원 {c.enrollment}명.")
            elif r.capacity < c.enrollment:
                add("H3", f"{code}: 강의실 {r.rid} 수용인원 {r.capacity}석 < 수강인원 {c.enrollment}명.")
            if c.exam_type == EXAM_SEPARATE:
                if not r.allows(c.dept):
                    add("H3", f"{code}: 강의실 {r.rid}은(는) {c.dept} 사용 강의실이 아닙니다.")
                req = requests.get(code)
                if req:
                    if req.min_capacity and r.capacity < req.min_capacity:
                        add("H3", f"{code}: 요청한 최소 {req.min_capacity}석보다 작은 강의실입니다.")
                    if req.building and req.building not in r.building:
                        add("H3", f"{code}: 요청한 건물({req.building})이 아닙니다.")
                    if req.room_ids and r.rid not in req.room_ids:
                        add("H3", f"{code}: 요청한 강의실이 아닙니다.")
    for rid, its in by_room.items():
        for a in range(len(its)):
            for b in range(a + 1, len(its)):
                x, y = its[a], its[b]
                if x.code != y.code and _ov(x, y):
                    add("H3", f"강의실 {rid}: {x.code}과 {y.code}이 {fmt_slot(x.day, max(x.start, y.start))}에 동시에 사용합니다.")

    # ---- H4: 확정 시험 ----
    for code, a in confirmed.items():
        es = exams.get(code, [])
        if not es or (es[0].day, es[0].start, es[0].room) != (a.day, a.start, a.room):
            add("H4", f"{code}: 확정된 일정({fmt_slot(a.day, a.start)} {a.room})이 바뀌었습니다.")

    # ---- 품질 지표 ----
    rep.metrics, rep.per_course = quality(ds, schedule, settings, requests, items)
    rep.metrics["hard_violations"] = len(viol)
    rep.metrics["conflict_students"] = len(conflict_students)
    return rep


def quality(ds: Dataset, schedule: pd.DataFrame, settings: Settings, requests, items=None):
    cm, rm = ds.course_map, ds.room_map
    items = items or week_items(ds, schedule, settings)
    exam_of = {}
    for r in schedule.itertuples(index=False):
        exam_of[r.course_code] = Item(r.course_code, "시험", int(r.day), int(r.start), int(r.end), str(r.room_id))
    per_course = {code: dict(overload_students=0, consecutive_students=0, max_same_day=0)
                  for code in exam_of}
    stu_overload, stu_consec, overload_days, consec_pairs = 0, 0, 0, 0
    max_per_day = 0
    for sid, codes in ds.courses_of.items():
        es = [exam_of[c] for c in codes if c in exam_of]
        by_day: dict[int, list[Item]] = defaultdict(list)
        for e in es:
            by_day[e.day].append(e)
        over, consec = False, False
        for d, lst in by_day.items():
            max_per_day = max(max_per_day, len(lst))
            for e in lst:
                pc = per_course[e.code]
                pc["max_same_day"] = max(pc["max_same_day"], len(lst))
            if len(lst) > MAX_EXAMS_PER_DAY:
                over = True
                overload_days += 1
                for e in lst:
                    per_course[e.code]["overload_students"] += 1
            lst = sorted(lst, key=lambda e: e.start)
            hit = set()
            for a, b in zip(lst, lst[1:]):
                if 0 <= b.start - a.end < CONSECUTIVE_GAP_MIN:
                    consec = True
                    consec_pairs += 1
                    hit |= {a.code, b.code}
            for code in hit:
                per_course[code]["consecutive_students"] += 1
        stu_overload += over
        stu_consec += consec

    # 선호 시간 반영률 (별도 시험 과목 중 선호 시간이 있는 과목)
    pref_total = pref_met = 0
    seats_used = seats_alloc = 0
    rank = dept_rank(settings.semester)
    dept_stats: dict[str, dict] = defaultdict(lambda: dict(pref_total=0, pref_met=0, waste=0, exams=0, seats=0))
    for code, e in exam_of.items():
        c = cm[code]
        pc = per_course[code]
        r = rm.get(e.room)
        pc["room_capacity"] = r.capacity if r else 0
        pc["room_exam_capacity"] = r.exam_capacity if r else 0
        pc["waste"] = (r.exam_capacity - c.enrollment) if r else 0
        prefs = preferences_for(ds, code, requests)
        pc["has_pref"] = bool(prefs)
        pc["pref_met"] = bool(prefs) and any(settings.inside(p, e.day, e.start, e.end) for p in prefs)
        req = requests.get(code)
        pc["in_avoid"] = bool(req and any(settings.hits(w, e.day, e.start, e.end) for w in req.avoid))
        if c.exam_type != EXAM_SEPARATE:
            continue
        ds_ = dept_stats[c.dept]
        ds_["exams"] += 1
        if r:
            seats_used += c.enrollment
            seats_alloc += r.exam_capacity
            ds_["waste"] += r.exam_capacity - c.enrollment
            ds_["seats"] += r.exam_capacity
        if prefs:
            pref_total += 1
            ds_["pref_total"] += 1
            if pc["pref_met"]:
                pref_met += 1
                ds_["pref_met"] += 1
    dept_rows = []
    for d, v in sorted(dept_stats.items(), key=lambda kv: rank.get(kv[0], 99)):
        dept_rows.append(dict(학과=d, 순위=rank.get(d), 별도시험=v["exams"],
                              선호반영=f"{v['pref_met']}/{v['pref_total']}" if v["pref_total"] else "-",
                              남는좌석=v["waste"],
                              좌석활용률=round(100 * (1 - v["waste"] / v["seats"]), 1) if v["seats"] else None))
    metrics = dict(
        students_3plus=stu_overload,
        overload_student_days=overload_days,
        consecutive_students=stu_consec,
        consecutive_pairs=consec_pairs,
        max_exams_per_day=max_per_day,
        pref_total=pref_total,
        pref_met=pref_met,
        room_utilization=round(100 * seats_used / seats_alloc, 1) if seats_alloc else 0.0,
        wasted_seats=seats_alloc - seats_used,
        dept_table=dept_rows,
    )
    return metrics, per_course


def preferences_for(ds: Dataset, code: str, requests: dict[str, CourseRequest]):
    """적용되는 선호 시간: 교수 요청 선호가 있으면 그것, 없으면 교수 기본 선호(별도 시험만)"""
    req = requests.get(code)
    if req and req.preferred:
        return list(req.preferred)
    c = ds.course_map[code]
    if c.exam_type != EXAM_SEPARATE:
        return []
    p = ds.prof_map.get(c.prof)
    return list(p.preferred) if p else []
