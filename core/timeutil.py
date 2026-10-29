"""시간 표현 변환 도우미.

내부 표현: 요일 인덱스(0=월 … 4=금) + 하루 시작 0시 기준 분(minute).
전역 시각 = 요일 * 1440 + 분  → 서로 다른 날의 구간은 절대 겹치지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import DAYS

DAY_MINUTES = 1440


def hm_to_min(s: str) -> int:
    """'09:30' -> 570"""
    s = str(s).strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if not m:
        raise ValueError(f"시각 형식이 잘못되었습니다: '{s}' (예: 09:30)")
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 24 and 0 <= mi < 60):
        raise ValueError(f"시각 범위가 잘못되었습니다: '{s}'")
    return h * 60 + mi


def min_to_hm(m: int) -> str:
    m = int(m)
    return f"{m // 60:02d}:{m % 60:02d}"


def day_index(d: str) -> int:
    d = str(d).strip().replace("요일", "")
    if d not in DAYS:
        raise ValueError(f"요일은 월~금 중 하나여야 합니다: '{d}'")
    return DAYS.index(d)


def gtime(day: int, minute: int) -> int:
    return day * DAY_MINUTES + minute


def split_g(g: int) -> tuple[int, int]:
    return g // DAY_MINUTES, g % DAY_MINUTES


def fmt_slot(day: int, start: int, end: int | None = None) -> str:
    s = f"{DAYS[day]} {min_to_hm(start)}"
    if end is not None:
        s += f"~{min_to_hm(end)}"
    return s


@dataclass(frozen=True)
class Window:
    """요일·시간 구간. day=None 이면 매일 해당 시간대."""
    day: int | None
    start: int
    end: int

    def overlaps(self, day: int, start: int, end: int) -> bool:
        if self.day is not None and self.day != day:
            return False
        return start < self.end and self.start < end

    def contains(self, day: int, start: int, end: int) -> bool:
        if self.day is not None and self.day != day:
            return False
        return self.start <= start and end <= self.end

    def to_text(self) -> str:
        d = DAYS[self.day] if self.day is not None else "매일"
        return f"{d} {min_to_hm(self.start)}-{min_to_hm(self.end)}"

    def to_dict(self) -> dict:
        return {
            "day": DAYS[self.day] if self.day is not None else None,
            "start": min_to_hm(self.start),
            "end": min_to_hm(self.end),
        }

    @staticmethod
    def from_dict(d: dict) -> "Window":
        day = d.get("day")
        di = None if day in (None, "", "매일") else day_index(day)
        w = Window(di, hm_to_min(d["start"]), hm_to_min(d["end"]))
        if w.end <= w.start:
            raise ValueError(f"종료 시각이 시작 시각보다 늦어야 합니다: {w.to_text()}")
        return w


def parse_windows(text) -> list[Window]:
    """'월 09:00-12:00; 목 13:00-18:00' -> [Window, ...]. 빈 값이면 []."""
    if text is None:
        return []
    text = str(text).strip()
    if not text or text.lower() == "nan":
        return []
    out: list[Window] = []
    for part in re.split(r"[;\n]", text):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(월|화|수|목|금|매일)(?:요일)?\s+(\d{1,2}:\d{2})\s*[-~]\s*(\d{1,2}:\d{2})", part)
        if not m:
            raise ValueError(f"시간대 형식이 잘못되었습니다: '{part}' (예: 월 09:00-12:00)")
        out.append(Window.from_dict({"day": m.group(1), "start": m.group(2), "end": m.group(3)}))
    return out


def windows_to_text(ws: list[Window]) -> str:
    return "; ".join(w.to_text() for w in ws)


def parse_days(text) -> list[int]:
    """'월,수' -> [0, 2]"""
    text = str(text).strip()
    parts = [p for p in re.split(r"[,\s/·]+", text) if p]
    if not parts:
        raise ValueError("수업 요일이 비어 있습니다")
    return [day_index(p) for p in parts]
