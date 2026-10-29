"""비교 기준: '수작업 방식(무작위 배정)'.

교수가 각자 자기 일정만 보고 시험 시간을 정하는 상황을 흉내 낸다.
- 수업시간 시험: 첫 번째 수업 요일에 시행
- 별도 시험: 교수 불가 시간·본인 수업만 피해서 무작위 시간, 그 시간에 비어 있는 강의실 중 무작위
  (수강생의 다른 시험은 확인하지 않음)
"""
from __future__ import annotations

import random

import pandas as pd

from .config import EXAM_IN_CLASS, EXAM_NONE, EXAM_SEPARATE, SLOT_MINUTES
from .dataset import Dataset
from .settings import Settings
from .validator import validate


def manual_schedule(ds: Dataset, settings: Settings, seed: int = 0) -> pd.DataFrame:
    rng = random.Random(seed)
    cm, rm = ds.course_map, ds.room_map
    room_busy: dict[str, list] = {r: [] for r in rm}
    prof_busy: dict[str, list] = {}
    rows = []
    for c in cm.values():
        if c.exam_type == EXAM_NONE:
            for b in c.class_blocks():
                room_busy.setdefault(c.room, []).append(b)
                prof_busy.setdefault(c.prof, []).append(b)
        elif c.exam_type == EXAM_IN_CLASS:
            d, s, e = c.in_class_exam_options()[0]
            room_busy.setdefault(c.room, []).append((d, s, e))
            prof_busy.setdefault(c.prof, []).append((d, s, e))
            rows.append(dict(course_code=c.code, day=d, start=s, end=e, room_id=c.room, exam_type=c.exam_type, locked=False))

    def free(lst, d, s, e):
        return all(not (d == bd and s < be and bs < e) for bd, bs, be in lst)

    seps = [c for c in cm.values() if c.exam_type == EXAM_SEPARATE]
    rng.shuffle(seps)
    for c in seps:
        prof = ds.prof_map.get(c.prof)
        dur = c.exam_minutes
        grid = [(d, m) for d in range(5) for m in range(settings.day_start, settings.day_end - dur + 1, SLOT_MINUTES)]
        ok = [(d, m) for d, m in grid
              if not (prof and any(w.overlaps(d, m, m + dur) for w in prof.unavailable))
              and free(prof_busy.get(c.prof, []), d, m, m + dur)]
        d, m = rng.choice(ok or grid)
        rooms = [r for r in rm.values() if r.capacity >= c.enrollment and r.allows(c.dept)]
        free_rooms = [r for r in rooms if free(room_busy[r.rid], d, m, m + dur)]
        room = rng.choice(free_rooms or rooms or list(rm.values()))
        room_busy[room.rid].append((d, m, m + dur))
        prof_busy.setdefault(c.prof, []).append((d, m, m + dur))
        rows.append(dict(course_code=c.code, day=d, start=m, end=m + dur, room_id=room.rid, exam_type=c.exam_type, locked=False))
    return pd.DataFrame(rows)


def baseline_metrics(ds: Dataset, settings: Settings, runs: int = 20) -> dict:
    """무작위 배정을 runs 번 반복한 평균 지표"""
    keys = ["hard_violations", "conflict_students", "students_3plus", "consecutive_students", "room_utilization"]
    acc = {k: 0.0 for k in keys}
    for i in range(runs):
        rep = validate(ds, manual_schedule(ds, settings, seed=i), settings, max_detail=10**6)
        for k in keys:
            acc[k] += rep.metrics[k]
    return {k: round(v / runs, 1) for k, v in acc.items()}
