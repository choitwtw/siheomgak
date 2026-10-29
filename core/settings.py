"""화면에서 바꿀 수 있는 실행 설정과 시험 기간 달력.

시험 기간은 날짜 범위(예: 12월 15일~21일)로 정한다. 내부에서는 '시험일 번호' k(0, 1, 2 …)를 쓰고,
정규 수업·교수 불가 시간처럼 요일로 적힌 정보는 각 시험일의 요일로 맞춰 본다.
예) 12/15(화)~12/21(월), 주말 제외 → 시험일 5일: 화 수 목 금 월
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import cached_property

from .config import DEFAULT_DAY_END, DEFAULT_DAY_START, DEFAULT_TIME_LIMIT_SEC, WEEKDAYS
from .priority import parse_semester
from .timeutil import hm_to_min

NOTIFY_PUBLISH = "publish"   # 모든 과목 확정 후 관리자가 일괄 발표 (기본)
NOTIFY_INSTANT = "instant"   # 교수가 확정하는 즉시 개별 알림


def default_period(sem: str) -> tuple[date, date]:
    """기말 시험 기간 기본값: 1학기 6월 15~21일, 2학기 12월 15~21일"""
    y, t = parse_semester(sem)
    start = date(2000 + y, 6 if t == 1 else 12, 15)
    return start, start + timedelta(days=6)


@dataclass
class Settings:
    semester: str = "26-2"
    day_start: int = hm_to_min(DEFAULT_DAY_START)
    day_end: int = hm_to_min(DEFAULT_DAY_END)
    time_limit: int = DEFAULT_TIME_LIMIT_SEC
    exam_start: date = field(default_factory=lambda: default_period("26-2")[0])
    exam_end: date = field(default_factory=lambda: default_period("26-2")[1])
    include_weekends: bool = False
    priority_lock: bool = True          # 우선순위가 높은 학과부터 확정
    notify_mode: str = NOTIFY_PUBLISH

    # ---- 시험 기간 달력 ----
    @cached_property
    def exam_dates(self) -> list[date]:
        out, d = [], self.exam_start
        while d <= self.exam_end:
            if self.include_weekends or d.weekday() < 5:
                out.append(d)
            d += timedelta(days=1)
        return out

    @property
    def n_days(self) -> int:
        return len(self.exam_dates)

    def date_of(self, k: int) -> date:
        return self.exam_dates[k]

    def weekday(self, k: int) -> int:
        """시험일 k 의 요일 (0=월 … 6=일)"""
        return self.exam_dates[k].weekday()

    def day_name(self, k: int) -> str:
        return WEEKDAYS[self.weekday(k)]

    def date_label(self, k: int) -> str:
        d = self.date_of(k)
        return f"{d.month}월 {d.day}일({self.day_name(k)})"

    def short_label(self, k: int) -> str:
        d = self.date_of(k)
        return f"{d.month}/{d.day}({self.day_name(k)})"

    def days_with_weekday(self, wd: int) -> list[int]:
        return [k for k, d in enumerate(self.exam_dates) if d.weekday() == wd]

    def period_label(self) -> str:
        if not self.n_days:
            return "시험일 없음"
        return f"{self.date_label(0)} ~ {self.date_label(self.n_days - 1)} · {self.n_days}일"

    # ---- 요일로 적힌 정보 → 시험일 ----
    def class_blocks(self, c) -> list[tuple[int, int, int]]:
        """과목 c 의 정규 수업 중 시험 기간에 있는 회차: (시험일, 시작, 종료)"""
        return [(k, c.start, c.end) for k in range(self.n_days) if self.weekday(k) in c.days]

    def in_class_options(self, c) -> list[tuple[int, int, int]]:
        """수업시간 시험이 가능한 회차 (정규 수업 시각·강의실 그대로)"""
        return [(k, c.start, c.start + c.in_class_exam_minutes) for k in range(self.n_days)
                if self.weekday(k) in c.days]

    def hits(self, w, k: int, s: int, e: int) -> bool:
        """요일 기준 시간대 w 가 시험일 k 의 [s, e) 와 겹치는가"""
        return w.overlaps(self.weekday(k), s, e)

    def inside(self, w, k: int, s: int, e: int) -> bool:
        return w.contains(self.weekday(k), s, e)
