"""배정 이유·경고·대안 계산.

여기서 만드는 숫자는 모두 데이터와 배정 결과에서 직접 센 값이다.
LLM 은 이 숫자를 문장으로 다듬기만 한다 (prompts/explain_assignment.md).
"""
from __future__ import annotations

import json
from collections import defaultdict

import pandas as pd

from . import llm
from .config import (
    CONSECUTIVE_GAP_MIN,
    DAYS,
    EXAM_IN_CLASS,
    EXAM_SEPARATE,
    MAX_EXAMS_PER_DAY,
    SLOT_MINUTES,
    W_AVOID,
    W_CONSECUTIVE,
    W_OVERLOAD,
    W_PREFERENCE,
    W_ROOM_WASTE,
)
from .constraints import CourseRequest
from .dataset import Dataset
from .priority import dept_rank
from .settings import Settings
from .timeutil import min_to_hm, windows_to_text
from .validator import Item, preferences_for, week_items


def _ov(d1, s1, e1, d2, s2, e2):
    return d1 == d2 and s1 < e2 and s2 < e1


def _dur(c) -> int:
    return c.in_class_exam_minutes if c.exam_type == EXAM_IN_CLASS else c.exam_minutes


def evaluate_slots(ds: Dataset, schedule: pd.DataFrame, settings: Settings,
                   requests: dict[str, CourseRequest], code: str) -> list[dict]:
    """다른 시험을 그대로 둔 채, code 과목을 각 후보 시각에 놓았을 때의 결과 (반드시 지킬 조건 통과 후보만, 좋은 순)."""
    out = [x for x in slot_map(ds, schedule, settings, requests, code) if x["status"] != "blocked"]
    out.sort(key=lambda x: (x["score"], x["day"], x["start"]))
    return out


def slot_map(ds: Dataset, schedule: pd.DataFrame, settings: Settings,
             requests: dict[str, CourseRequest], code: str, fixed_only: bool = False) -> list[dict]:
    """모든 후보 시작 시각의 상태.
    status: ok(가능·학생 부담 없음) / burden(가능하지만 하루 3과목·연속 시험 발생) / blocked(불가)
    blocked 이면 reason 과 (수강생 충돌이면) conflicts 인원.

    fixed_only=True: 다른 과목은 '확정된 시험'과 '바뀌지 않는 수업'만 고려한다 (교수가 처음 시간표를 볼 때).
      아직 확정 안 된 수업시간 시험은 어느 회차에 볼지 모르므로 그 과목의 정규 수업 회차를 모두 막아 둔다.
    fixed_only=False: 다른 과목의 현재 추천안까지 모두 고정된 것으로 보고 계산한다."""
    cm, rm = ds.course_map, ds.room_map
    c = cm[code]
    dur = _dur(c)
    others = schedule[schedule.course_code != code]
    if fixed_only:
        others = others[others["locked"].astype(bool)]
    items = week_items(ds, others, settings)
    if fixed_only:
        done = set(others.course_code)
        for oc in cm.values():
            if oc.code != code and oc.exam_type == EXAM_IN_CLASS and oc.code not in done:
                for d, s0, e0 in settings.in_class_options(oc):
                    items[oc.code].append(Item(oc.code, "수업", d, s0, e0, oc.room))
    req = requests.get(code)
    prof = ds.prof_map.get(c.prof)
    prefs = preferences_for(ds, code, requests)
    students = ds.students_of.get(code, [])
    stu_items = {sid: [i for oc in ds.courses_of[sid] if oc != code for i in items.get(oc, [])] for sid in students}
    prof_items = [i for oc in ds.prof_courses.get(c.prof, []) if oc != code for i in items.get(oc, [])]
    room_items: dict[str, list[Item]] = defaultdict(list)
    for its in items.values():
        for i in its:
            room_items[i.room].append(i)

    if c.exam_type == EXAM_IN_CLASS:
        grid = [(d, s) for d, s, _e in settings.in_class_options(c)]
        rooms = [rm[c.room]] if c.room in rm else []
    else:
        grid = [(d, m) for d in range(settings.n_days)
                for m in range(settings.day_start, settings.day_end - dur + 1, SLOT_MINUTES)]
        rooms = [r for r in rm.values() if r.capacity >= c.enrollment and r.allows(c.dept)
                 and not (req and req.min_capacity and r.capacity < req.min_capacity)
                 and not (req and req.building and req.building not in r.building)
                 and not (req and req.room_ids and r.rid not in req.room_ids)]
        rooms.sort(key=lambda r: r.capacity)
    out = []
    for d, m in grid:
        e = m + dur
        base = dict(day=d, start=m, end=e)
        if c.exam_type == EXAM_SEPARATE and prof and any(settings.hits(w, d, m, e) for w in prof.unavailable):
            out.append(dict(base, status="blocked", reason="교수 불가 시간"))
            continue
        if req and any(settings.hits(w, d, m, e) for w in req.unavailable):
            out.append(dict(base, status="blocked", reason="교수 요청 불가 시간"))
            continue
        if req and req.allowed and not any(settings.inside(w, d, m, e) for w in req.allowed):
            out.append(dict(base, status="blocked", reason="'이 시간에만' 요청 밖"))
            continue
        if any(_ov(d, m, e, i.day, i.start, i.end) for i in prof_items):
            out.append(dict(base, status="blocked", reason="교수 본인의 다른 수업·시험"))
            continue
        busy = [sid for sid, its in stu_items.items() if any(_ov(d, m, e, i.day, i.start, i.end) for i in its)]
        if busy:
            out.append(dict(base, status="blocked", reason=f"수강생 {len(busy)}명 시간 겹침", conflicts=len(busy)))
            continue
        room = next((r for r in rooms if not any(_ov(d, m, e, i.day, i.start, i.end) for i in room_items[r.rid])), None)
        if room is None:
            out.append(dict(base, status="blocked", reason="빈 강의실 없음"))
            continue
        overload = consec = 0
        for its in stu_items.values():
            same = [i for i in its if i.kind == "시험" and i.day == d]
            if len(same) + 1 > MAX_EXAMS_PER_DAY:
                overload += 1
            if any(0 <= m - i.end < CONSECUTIVE_GAP_MIN or 0 <= i.start - e < CONSECUTIVE_GAP_MIN for i in same):
                consec += 1
        pref_met = (not prefs) or any(settings.inside(p, d, m, e) for p in prefs)
        avoid = bool(req and any(settings.hits(w, d, m, e) for w in req.avoid))
        score = (W_OVERLOAD * overload + W_CONSECUTIVE * consec + (0 if pref_met else W_PREFERENCE)
                 + (W_AVOID if avoid else 0) + W_ROOM_WASTE * ((room.capacity - c.enrollment + 5) // 10))
        out.append(dict(base, status="burden" if (overload or consec) else "ok", room=room.rid,
                        capacity=room.capacity, overload=overload, consecutive=consec, pref_met=pref_met,
                        has_pref=bool(prefs), avoid=avoid, score=score, conflicts=0))
    return out


def course_facts(ds: Dataset, schedule: pd.DataFrame, settings: Settings, requests: dict[str, CourseRequest],
                 per_course: dict, code: str, slots: list[dict] | None = None) -> dict:
    c = ds.course_map[code]
    row = schedule[schedule.course_code == code]
    if row.empty:
        return {"code": code, "name": c.name, "has_exam": False}
    r = row.iloc[0]
    d, s, e = int(r.day), int(r.start), int(r.end)
    room = ds.room_map.get(r.room_id)
    pc = per_course.get(code, {})
    prefs = preferences_for(ds, code, requests)
    slots = slots if slots is not None else evaluate_slots(ds, schedule, settings, requests, code)
    pref_slots = [x for x in slots if x["has_pref"] and x["pref_met"]]
    rank = dept_rank(settings.semester).get(c.dept)
    facts = {
        "code": code, "name": c.name, "dept": c.dept, "priority_rank": rank, "has_exam": True,
        "exam_type": c.exam_type, "day": d, "day_name": settings.date_label(d), "date": settings.date_label(d),
        "start": min_to_hm(s), "end": min_to_hm(e), "minutes": e - s,
        "room": r.room_id, "room_capacity": room.capacity if room else None,
        "enrollment": c.enrollment, "student_conflicts": 0,
        "overload_students": int(pc.get("overload_students", 0)),
        "consecutive_students": int(pc.get("consecutive_students", 0)),
        "feasible_slots": len(slots),
        "locked": bool(r.locked),
    }
    if c.exam_type == EXAM_IN_CLASS:
        facts["class_time"] = f"{'·'.join(DAYS[x] for x in c.days)} {min_to_hm(c.start)}~{min_to_hm(c.end)}"
    if prefs:
        facts["preference"] = {"text": windows_to_text(prefs), "met": bool(pc.get("pref_met")),
                               "conflict_free_pref_slots": len(pref_slots)}
        if pref_slots and not pc.get("pref_met"):
            b = pref_slots[0]
            facts["preference"]["best_pref_slot"] = {
                "when": f"{settings.date_label(b['day'])} {min_to_hm(b['start'])}",
                "overload_students": b["overload"], "consecutive_students": b["consecutive"]}
    if room:
        facts["empty_seats"] = room.capacity - c.enrollment
    if pc.get("in_avoid"):
        facts["in_avoid_window"] = True
    facts["warnings"] = warnings_for(facts)
    return facts


def warnings_for(f: dict) -> list[str]:
    w = []
    if not f.get("has_exam"):
        return w
    if f["consecutive_students"]:
        w.append(f"경고 — {f['day_name']}에 이 과목 수강생 {f['consecutive_students']}명이 연속 시험(앞뒤 간격 30분 미만)")
    if f["overload_students"]:
        w.append(f"경고 — {f['day_name']}에 이 과목 수강생 {f['overload_students']}명이 하루 3과목 이상 시험")
    p = f.get("preference")
    if p and not p["met"]:
        if p["conflict_free_pref_slots"] == 0:
            w.append(f"선호 시간({p['text']})에는 수강생 충돌 없이 배정할 수 있는 시간이 없어 반영하지 못했습니다")
        elif p.get("best_pref_slot"):
            b = p["best_pref_slot"]
            w.append(f"선호 시간({p['text']})을 반영하지 못했습니다 — 선호 시간대에서 가장 나은 {b['when']}에 두면 "
                     f"하루 3과목 이상 학생 {b['overload_students']}명, 연속 시험 학생 {b['consecutive_students']}명이 생깁니다")
        else:
            w.append(f"선호 시간({p['text']})을 반영하지 못했습니다 — 학생 부담·강의실·학과 우선순위를 함께 고려한 결과")
    if f.get("in_avoid_window"):
        w.append("요청하신 '되도록 피할 시간'에 배정되었습니다 — 다른 시간대에는 충돌 없는 배정이 어렵습니다")
    if f.get("room_capacity") and f.get("empty_seats", 0) > max(30, f["room_capacity"] * 0.5):
        w.append(f"강의실 여유 좌석이 {f['empty_seats']}석으로 큽니다 (그 시간에 더 알맞은 강의실이 비어 있지 않음)")
    return w


def template_reason(f: dict) -> str:
    if not f.get("has_exam"):
        return "시험이 없는 과목입니다(과제 대체). 시험 주간에도 정규 수업이 진행됩니다."
    when = f"{f['date']} {f['start']}"
    bits = [f"수강생 {f['enrollment']}명 전원 이 시간 충돌 없음",
            f"하루 3과목 이상 학생 {f['overload_students']}명",
            f"연속 시험 학생 {f['consecutive_students']}명"]
    if f.get("room_capacity"):
        bits.append(f"수용인원 {f['room_capacity']}석 강의실({f['room']}) 배정")
    p = f.get("preference")
    if p and p["met"]:
        bits.append(f"교수 선호 시간({p['text']}) 반영")
    if f["exam_type"] == EXAM_IN_CLASS:
        head = f"**{when} 추천** (수업시간 시험 — 정규 수업 {f['class_time']} 중 {f['day_name']} 회차)"
    else:
        head = f"**{when} 추천** — 충돌 없는 후보 {f['feasible_slots']}개 중 선택"
    return head + " — " + ", ".join(bits)


def llm_reason(f: dict) -> str:
    """LLM 문장 (실패하면 LLMError → 호출 측에서 template_reason 사용)"""
    facts = {k: v for k, v in f.items() if k not in ("day",)}
    return llm.call_text(llm.load_prompt("explain_assignment"),
                         "다음 배정 결과를 설명해 주세요.\n" + json.dumps(facts, ensure_ascii=False, indent=1))


def impact_facts(f: dict, slots: list[dict], settings: Settings, k: int = 3) -> dict:
    # 서로 충분히 다른 대안만 고른다 (같은 날이면 90분 이상 떨어진 시각)
    taken = [(f["day"], f["start"])] if f.get("has_exam") else []
    alts = []
    for x in slots:
        if any(x["day"] == d and abs(x["start"] - (int(t[:2]) * 60 + int(t[3:]) if isinstance(t, str) else t)) < 90
               for d, t in taken):
            continue
        alts.append(x)
        taken.append((x["day"], x["start"]))
        if len(alts) >= k:
            break
    if not alts:   # 충분히 떨어진 대안이 없으면 가까운 시각이라도 보여 준다
        alts = [x for x in slots if not (f.get("has_exam") and x["day"] == f["day"]
                                         and min_to_hm(x["start"]) == f["start"])][:k]
    return {
        "course": f"{f['code']} {f['name']}",
        "current": f"{f.get('date')} {f.get('start')}~{f.get('end')} {f.get('room')}",
        "affected_students": f.get("enrollment"),
        "alternatives": [
            {"rank": i + 1, "when": f"{settings.date_label(a['day'])} {min_to_hm(a['start'])}~{min_to_hm(a['end'])}",
             "room": a["room"], "student_conflicts": 0, "overload_students": a["overload"],
             "consecutive_students": a["consecutive"], "preference_met": a["pref_met"] if a["has_pref"] else None,
             "_slot": (a["day"], a["start"], a["end"])}
            for i, a in enumerate(alts)
        ],
    }


def template_impact(imp: dict) -> str:
    if not imp["alternatives"]:
        return (f"현재 일정({imp['current']})을 바꾸면 수강생 {imp['affected_students']}명이 영향을 받습니다. "
                "다른 시험을 그대로 둔 상태에서는 충돌 없이 옮길 수 있는 시간이 없습니다.")
    a = imp["alternatives"][0]
    txt = (f"현재 일정({imp['current']})을 바꾸면 수강생 {imp['affected_students']}명의 시간표가 달라집니다. "
           f"가장 나은 대안은 {a['when']}({a['room']})로, 충돌 0명·하루 3과목 이상 {a['overload_students']}명·"
           f"연속 시험 {a['consecutive_students']}명입니다.")
    if len(imp["alternatives"]) > 1:
        txt += " 다른 대안: " + ", ".join(f"{x['when']}" for x in imp["alternatives"][1:]) + "."
    return txt


def llm_impact(imp: dict) -> str:
    clean = dict(imp, alternatives=[{k: v for k, v in a.items() if not k.startswith("_")} for a in imp["alternatives"]])
    return llm.call_text(llm.load_prompt("impact_analysis"),
                         "다음 변경 영향을 설명해 주세요.\n" + json.dumps(clean, ensure_ascii=False, indent=1))
