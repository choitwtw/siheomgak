from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import DEFAULT_DAY_END, DEFAULT_DAY_START, DEFAULT_TIME_LIMIT_SEC
from .priority import parse_semester
from .timeutil import hm_to_min


def default_week_start(sem: str) -> date:
    """학기말 시험 주간 기본값: 1학기 6월 셋째 주 월요일, 2학기 12월 셋째 주 월요일"""
    y, t = parse_semester(sem)
    d = date(2000 + y, 6 if t == 1 else 12, 15)
    return d - timedelta(days=d.weekday())


@dataclass
class Settings:
    semester: str = "26-2"
    day_start: int = hm_to_min(DEFAULT_DAY_START)
    day_end: int = hm_to_min(DEFAULT_DAY_END)
    time_limit: int = DEFAULT_TIME_LIMIT_SEC
    week_start: date = field(default_factory=lambda: default_week_start("26-2"))

    def date_of(self, day: int) -> date:
        return self.week_start + timedelta(days=day)

    def date_label(self, day: int) -> str:
        d = self.date_of(day)
        return f"{d.month}월 {d.day}일({'월화수목금'[day]})"
