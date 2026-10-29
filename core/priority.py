"""학기별 학과 우선순위 순환.

기준 순서: 물리학과 → 수학과 → 생물학과 → 지리학과 → 정보디스플레이학과 → 화학과
26-1학기 물리학과 1순위, 26-2학기 수학과 1순위, 27-1학기 생물학과 1순위 … 매 학기 한 칸씩 순환.
"""
from __future__ import annotations

import re

from .config import DEPARTMENTS

BASE_SEMESTER = (26, 1)


def semester_options(first_year: int = 25, last_year: int = 30) -> list[str]:
    return [f"{y}-{t}" for y in range(first_year, last_year + 1) for t in (1, 2)]


def parse_semester(sem: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{2})-([12])", sem.strip())
    if not m:
        raise ValueError(f"학기 형식이 잘못되었습니다: '{sem}' (예: 26-2)")
    return int(m.group(1)), int(m.group(2))


def semester_offset(sem: str) -> int:
    y, t = parse_semester(sem)
    by, bt = BASE_SEMESTER
    return (y - by) * 2 + (t - bt)


def priority_order(sem: str) -> list[str]:
    """해당 학기의 학과 순위 (0번째가 1순위)"""
    k = semester_offset(sem) % len(DEPARTMENTS)
    return DEPARTMENTS[k:] + DEPARTMENTS[:k]


def dept_weights(sem: str) -> dict[str, int]:
    """1순위 6배 … 6순위 1배"""
    order = priority_order(sem)
    n = len(order)
    return {d: n - i for i, d in enumerate(order)}


def dept_rank(sem: str) -> dict[str, int]:
    return {d: i + 1 for i, d in enumerate(priority_order(sem))}


def semester_label(sem: str) -> str:
    y, t = parse_semester(sem)
    return f"20{y}학년도 {t}학기"
