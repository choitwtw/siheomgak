"""자연어 조건 → 구조화된 조건.

1순위: Claude API (prompts/parse_constraints.md, JSON 스키마 강제)
대체:  규칙 기반 파서 (요일·오전/오후·시각 숫자·시험 시간·좌석 수 패턴 인식)
어느 쪽이든 constraints.validate_request() 를 통과한 결과만 돌려준다.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

from . import llm
from .config import DAYS, WEEKDAYS
from .constraints import REQUEST_SCHEMA, CourseRequest, RequestError, validate_request
from .timeutil import min_to_hm


@dataclass
class ParseContext:
    code: str = ""
    name: str = ""
    duration: int = 90
    enrollment: int = 50
    exam_type: str = "별도"
    current: tuple[int, int, int] | None = None   # 현재 배정 (요일 0=월…, 시작, 종료)
    day_start: int = 540
    day_end: int = 1080
    buildings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 규칙 기반 파서
# ---------------------------------------------------------------------------
NEG = re.compile(r"안\s*(?:돼|되|됨|될|됩)|불가|못\s|못해|못 해|어렵|어려|빼|제외|말고|곤란|힘들|피해|피하|싫|금지|않")
SOFT = re.compile(r"가능하면|되도록|웬만하면|가급적|될\s*수\s*있으면|선호|좋겠|좋아|원해|원합|희망|바람|부탁|면\s*좋")
ONLY = re.compile(r"에만|만\s*(?:가능|돼|되|됩|봐|볼)|로\s*고정|으로\s*고정|외에는\s*안|빼고는?\s*안")
AVOID_WORD = re.compile(r"피해|피하|가능하면.*(?:말고|빼)|되도록.*(?:말고|빼)")
POLITE = re.compile(r"^(?:부탁(?:드립니다|해요|합니다)?|감사합니다|고맙습니다|그리고|또|요|네)$")

PARTS = [  # (패턴, 시작, 종료)  긴 표현 먼저
    (r"늦은\s*오후", 900, 1080),
    (r"이른\s*오전|아침", 540, 630),
    (r"오전", 540, 720),
    (r"점심", 720, 780),
    (r"오후", 720, 1080),
    (r"저녁", 1020, 1080),
    (r"하루\s*종일|종일|하루\s*전체|온종일", 540, 1080),
]
DAY_RE = re.compile(r"(월|화|수|목|금)(?:요일)?")
H = r"(오전|오후)?\s*(\d{1,2})\s*(?:시(?!간)\s*(반|\d{1,2}\s*분)?|:(\d{2}))"


def _hour(ampm, h, half, mm) -> int:
    h = int(h)
    if ampm == "오후" and h < 12:
        h += 12
    elif ampm is None and 1 <= h <= 7:
        h += 12
    m = 0
    if half:
        m = 30 if "반" in half else int(re.sub(r"\D", "", half) or 0)
    if mm:
        m = int(mm)
    return h * 60 + m


def _split(text: str) -> list[str]:
    text = text.replace("\n", " ")
    # '목, 금은 안 돼' 처럼 요일 나열의 쉼표는 절 구분이 아니다
    text = re.sub(r"(월|화|수|목|금)(요일)?\s*,\s*(?=(?:월|화|수|목|금))", r"\1\2·", text)
    parts = re.split(r"(?<=되고)|(?<=하고)|(?<=지만)|(?<=는데)|(?<=이고)|(?<=으며)|(?<=하며)|[,.;!?]|그리고|그리구|또한", text)
    return [p.strip() for p in parts if p and p.strip()]


def _days(clause: str) -> list[int] | None:
    if re.search(r"주\s*초반|주초", clause):
        return [0, 1]
    if re.search(r"주\s*후반|주말\s*전|주\s*막바지", clause):
        return [3, 4]
    m = re.search(r"(월|화|수|목|금)(?:요일)?\s*(?:~|-|부터|에서)\s*(월|화|수|목|금)(?:요일)?", clause)
    if m:
        a, b = DAYS.index(m.group(1)), DAYS.index(m.group(2))
        return list(range(min(a, b), max(a, b) + 1))
    found = []
    # '월요일', '수', '목·금' 처럼 한 글자 요일도 인식 (단, '수강', '금지' 같은 단어는 제외)
    for m in re.finditer(r"(월|화|수|목|금)(요일|[,·/\s]|이랑|와|과|하고|은|는|에|이나|도|$)", clause):
        tail = clause[m.end(1):m.end(1) + 2]
        if m.group(1) == "수" and tail.startswith("강"):
            continue
        if m.group(1) == "금" and tail.startswith("지"):
            continue
        d = DAYS.index(m.group(1))
        if d not in found:
            found.append(d)
    return found or None


def _times(clause: str, ctx: ParseContext) -> list[tuple[int, int]] | None:
    m = re.search(H + r"\s*(?:~|-|부터|에서)\s*" + H + r"?\s*(?:까지|사이)?", clause)
    if m:
        s = _hour(m.group(1), m.group(2), m.group(3), m.group(4))
        if m.group(6):
            e = _hour(m.group(5) or m.group(1), m.group(6), m.group(7), m.group(8))
            if e <= s and e + 720 <= 1440:
                e += 720
            return [(s, e)]
    m = re.search(H + r"\s*(?:이후|부터|넘어서|지나서|넘어|후에|후로|이후로)", clause)
    if m:
        return [(_hour(*m.groups()), ctx.day_end)]
    m = re.search(H + r"\s*(?:이전|전에|전까지|까지|전)", clause)
    if m:
        return [(ctx.day_start, _hour(*m.groups()))]
    m = re.search(H, clause)
    if m:
        s = _hour(*m.groups())
        return [(s, s + ctx.duration)]
    out = []
    for pat, s, e in PARTS:
        if re.search(pat, clause):
            out.append((s, e))
            break
    return out or None


def _duration(text: str) -> int | None:
    m = re.search(r"(\d{2,3})\s*분", text)
    if m and re.search(r"시험|늘|줄|으로|로|짜리|동안", text):
        return int(m.group(1))
    m = re.search(r"(\d)\s*시간\s*(반)?", text)
    if m and re.search(r"시험\s*시간|늘|줄|으로|로|짜리|동안", text):
        return int(m.group(1)) * 60 + (30 if m.group(2) else 0)
    m = re.search(r"한\s*시간\s*(반)?", text)
    if m:
        return 60 + (30 if m.group(1) else 0)
    m = re.search(r"두\s*시간", text)
    if m:
        return 120
    return None


def rule_parse(text: str, ctx: ParseContext) -> dict:
    out = {"unavailable": [], "allowed": [], "preferred": [], "avoid": [], "duration_minutes": None,
           "room": {"min_capacity": None, "building": None, "room_ids": []}, "summary": "", "unsupported": []}

    def win(day, s, e):
        s, e = max(s, ctx.day_start), min(e, ctx.day_end)
        if e <= s:
            return None
        return {"day": WEEKDAYS[day] if day is not None else None, "start": min_to_hm(s), "end": min_to_hm(e)}

    for clause in _split(text):
        parsed = False
        # 시험 시간
        dur = _duration(clause)
        if dur:
            out["duration_minutes"] = int(round(dur / 15) * 15)
            parsed = True
        # 강의실
        m = re.search(r"(\d{2,3})\s*(?:석|명|인)\s*(?:이상|넘는|넘게|짜리|규모)?", clause)
        if m and re.search(r"강의실|석|교실|방|규모|자리", clause):
            out["room"]["min_capacity"] = int(m.group(1))
            parsed = True
        elif re.search(r"(큰|넓은|대형)\s*(강의실|교실|방)", clause):
            out["room"]["min_capacity"] = int(math.ceil(ctx.enrollment * 1.5 / 10) * 10)
            parsed = True
        for b in ctx.buildings:
            if b and b in clause:
                out["room"]["building"] = b
                parsed = True
        # '다른 날 / 지금 시간 말고'
        if ctx.current and re.search(r"다른\s*날|지금\s*(?:날|요일)\s*말고|그\s*날\s*말고|이\s*날\s*말고", clause):
            d, _s, _e = ctx.current
            out["unavailable"].append(win(d, ctx.day_start, ctx.day_end))
            parsed = True
            continue
        if ctx.current and re.search(r"(?:지금|현재|그|이)\s*시간\s*(?:말고|은\s*안|는\s*안|빼)|다른\s*시간", clause):
            d, s, e = ctx.current
            out["unavailable"].append(win(d, s, e))
            parsed = True
            continue
        # 요일·시간대
        days = _days(clause)
        times = None if (dur and not re.search(r"오전|오후|\d+\s*시(?!간)", clause)) else _times(clause, ctx)
        if days or times:
            wins = []
            for d in (days or [None]):
                for s, e in (times or [(ctx.day_start, ctx.day_end)]):
                    w = win(d, s, e)
                    if w:
                        wins.append(w)
            if ONLY.search(clause):
                kind = "allowed"
            elif NEG.search(clause):
                kind = "avoid" if (SOFT.search(clause) or AVOID_WORD.search(clause)) else "unavailable"
            else:
                kind = "preferred"
            for w in wins:
                if w not in out[kind]:
                    out[kind].append(w)
            parsed = True
        if not parsed and len(clause) > 3 and not POLITE.match(clause) and not re.fullmatch(r"[가-힣\s]{0,6}(주세요|해요|합니다|요)", clause):
            out["unsupported"].append(clause)
    out["unavailable"] = [w for w in out["unavailable"] if w]
    out["summary"] = summarize(out)
    return out


def summarize(d: dict) -> str:
    def wt(w):
        day = (w["day"] + "요일") if w["day"] else "매일"
        return f"{day} {w['start']}~{w['end']}"
    parts = []
    if d["unavailable"]:
        parts.append(", ".join(wt(w) for w in d["unavailable"]) + " 불가")
    if d["allowed"]:
        parts.append(", ".join(wt(w) for w in d["allowed"]) + "에만 가능")
    if d["preferred"]:
        parts.append("가능하면 " + ", ".join(wt(w) for w in d["preferred"]))
    if d["avoid"]:
        parts.append("되도록 " + ", ".join(wt(w) for w in d["avoid"]) + " 피함")
    if d["duration_minutes"]:
        parts.append(f"시험 시간 {d['duration_minutes']}분")
    r = d["room"]
    if r.get("min_capacity"):
        parts.append(f"{r['min_capacity']}석 이상 강의실")
    if r.get("building"):
        parts.append(f"{r['building']} 건물")
    return " / ".join(parts) if parts else "인식된 조건이 없습니다"


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------
def parse_request(text: str, ctx: ParseContext, use_llm: bool = True) -> tuple[CourseRequest, str, str | None]:
    """(조건, 사용한 방식 'AI'/'규칙 기반', 안내 메시지)"""
    text = (text or "").strip()
    note = None
    if use_llm and llm.available():
        try:
            info = {
                "과목": f"{ctx.code} {ctx.name}",
                "시험 방식": ctx.exam_type,
                "현재 시험 시간(분)": ctx.duration,
                "수강인원": ctx.enrollment,
                "현재 배정": (f"{WEEKDAYS[ctx.current[0]]}요일 {min_to_hm(ctx.current[1])}~{min_to_hm(ctx.current[2])}"
                          if ctx.current else "없음"),
            }
            system = llm.load_prompt("parse_constraints", day_start=min_to_hm(ctx.day_start),
                                     day_end=min_to_hm(ctx.day_end),
                                     course_info=json.dumps(info, ensure_ascii=False, indent=1),
                                     buildings=", ".join(ctx.buildings) or "(정보 없음)")
            data = llm.call_json(system, f"교수 요청: {text}", REQUEST_SCHEMA)
            req = validate_request(data, source="AI", raw_text=text)
            return req, "AI", None
        except (llm.LLMError, RequestError) as e:
            note = f"AI 변환에 실패해 규칙 기반 파서로 대신 처리했습니다. ({e})"
    data = rule_parse(text, ctx)
    req = validate_request(data, source="규칙 기반", raw_text=text)
    return req, "규칙 기반", note
