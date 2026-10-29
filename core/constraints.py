"""교수 추가 조건 (자연어 → 구조화된 조건) 의 스키마와 검증.

LLM 이 만든 JSON 이든 규칙 기반 파서 결과든, 반드시 `validate_request()` 를 통과한 것만 사용한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import DAYS
from .timeutil import Window

# LLM 에게 주는 JSON 스키마 (prompts/parse_constraints.md 에도 동일하게 설명)
WINDOW_SCHEMA = {
    "type": "object",
    "properties": {
        "day": {"anyOf": [{"type": "string", "enum": DAYS}, {"type": "null"}],
                "description": "요일(월~금). 모든 요일이면 null"},
        "start": {"type": "string", "description": "HH:MM"},
        "end": {"type": "string", "description": "HH:MM"},
    },
    "required": ["day", "start", "end"],
    "additionalProperties": False,
}
REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "unavailable": {"type": "array", "items": WINDOW_SCHEMA, "description": "절대 안 되는 시간 (반드시 지킴)"},
        "allowed": {"type": "array", "items": WINDOW_SCHEMA, "description": "이 시간 안에서만 가능 (반드시 지킴). 제한 없으면 []"},
        "preferred": {"type": "array", "items": WINDOW_SCHEMA, "description": "되도록 이 시간 (선호)"},
        "avoid": {"type": "array", "items": WINDOW_SCHEMA, "description": "되도록 피할 시간"},
        "duration_minutes": {"anyOf": [{"type": "integer"}, {"type": "null"}],
                             "description": "시험 시간 변경(분). 변경 없으면 null"},
        "room": {
            "type": "object",
            "properties": {
                "min_capacity": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "building": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "room_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["min_capacity", "building", "room_ids"],
            "additionalProperties": False,
        },
        "summary": {"type": "string", "description": "해석 결과를 한국어 한 문장으로"},
        "unsupported": {"type": "array", "items": {"type": "string"},
                        "description": "시스템이 처리할 수 없는 요청 문구"},
    },
    "required": ["unavailable", "allowed", "preferred", "avoid", "duration_minutes", "room", "summary", "unsupported"],
    "additionalProperties": False,
}


@dataclass
class CourseRequest:
    """한 과목에 대한 교수 추가 조건"""
    unavailable: list[Window] = field(default_factory=list)
    allowed: list[Window] = field(default_factory=list)
    preferred: list[Window] = field(default_factory=list)
    avoid: list[Window] = field(default_factory=list)
    duration_minutes: int | None = None
    min_capacity: int | None = None
    building: str | None = None
    room_ids: list[str] = field(default_factory=list)
    summary: str = ""
    unsupported: list[str] = field(default_factory=list)
    source: str = ""          # "AI" / "규칙 기반"
    raw_text: str = ""

    def is_empty(self) -> bool:
        return not (self.unavailable or self.allowed or self.preferred or self.avoid or self.duration_minutes
                    or self.min_capacity or self.building or self.room_ids)

    def to_dict(self) -> dict:
        return {
            "unavailable": [w.to_dict() for w in self.unavailable],
            "allowed": [w.to_dict() for w in self.allowed],
            "preferred": [w.to_dict() for w in self.preferred],
            "avoid": [w.to_dict() for w in self.avoid],
            "duration_minutes": self.duration_minutes,
            "room": {"min_capacity": self.min_capacity, "building": self.building, "room_ids": list(self.room_ids)},
            "summary": self.summary,
            "unsupported": list(self.unsupported),
        }

    def merged_with(self, other: "CourseRequest") -> "CourseRequest":
        """기존 조건 + 새 조건 (새 값 우선)"""
        def uniq(a, b):
            out = list(a)
            for w in b:
                if w not in out:
                    out.append(w)
            return out
        return CourseRequest(
            unavailable=uniq(self.unavailable, other.unavailable),
            allowed=list(other.allowed) if other.allowed else list(self.allowed),
            preferred=list(other.preferred) if other.preferred else list(self.preferred),
            avoid=uniq(self.avoid, other.avoid),
            duration_minutes=other.duration_minutes or self.duration_minutes,
            min_capacity=other.min_capacity or self.min_capacity,
            building=other.building or self.building,
            room_ids=list(other.room_ids) if other.room_ids else list(self.room_ids),
            summary=other.summary or self.summary,
            unsupported=list(other.unsupported),
            source=other.source,
            raw_text=other.raw_text,
        )

    def describe(self) -> list[str]:
        """사람이 읽는 조건 목록"""
        out = []
        for w in self.unavailable:
            out.append(f"🚫 불가: {w.to_text()}")
        if self.allowed:
            out.append("🔒 이 시간에만: " + ", ".join(w.to_text() for w in self.allowed))
        for w in self.preferred:
            out.append(f"⭐ 선호: {w.to_text()}")
        for w in self.avoid:
            out.append(f"↪️ 되도록 피함: {w.to_text()}")
        if self.duration_minutes:
            out.append(f"⏱️ 시험 시간: {self.duration_minutes}분")
        if self.min_capacity:
            out.append(f"🏫 강의실 최소 {self.min_capacity}석")
        if self.building:
            out.append(f"🏢 건물: {self.building}")
        if self.room_ids:
            out.append("🚪 강의실 지정: " + ", ".join(self.room_ids))
        return out


class RequestError(ValueError):
    pass


def validate_request(data: dict, source: str = "", raw_text: str = "") -> CourseRequest:
    """스키마 검증. 통과 못 하면 RequestError (한국어 메시지)."""
    if not isinstance(data, dict):
        raise RequestError("조건 형식이 객체(JSON)가 아닙니다.")

    def windows(key) -> list[Window]:
        v = data.get(key) or []
        if not isinstance(v, list):
            raise RequestError(f"'{key}'는 목록이어야 합니다.")
        out = []
        for item in v:
            if not isinstance(item, dict) or "start" not in item or "end" not in item:
                raise RequestError(f"'{key}'의 시간대 형식이 잘못되었습니다: {item}")
            try:
                w = Window.from_dict(item)
            except (ValueError, KeyError) as e:
                raise RequestError(f"'{key}' 시간대 오류: {e}") from e
            out.append(w)
        return out

    dur = data.get("duration_minutes")
    if dur is not None:
        try:
            dur = int(dur)
        except (TypeError, ValueError) as e:
            raise RequestError(f"시험 시간은 정수(분)여야 합니다: {dur}") from e
        if not 30 <= dur <= 240 or dur % 15:
            raise RequestError(f"시험 시간은 30~240분, 15분 단위여야 합니다: {dur}분")
    room = data.get("room") or {}
    if not isinstance(room, dict):
        raise RequestError("'room'은 객체여야 합니다.")
    mc = room.get("min_capacity")
    if mc is not None:
        try:
            mc = int(mc)
        except (TypeError, ValueError) as e:
            raise RequestError(f"최소 좌석 수는 정수여야 합니다: {mc}") from e
        if mc <= 0:
            mc = None
    rids = room.get("room_ids") or []
    if not isinstance(rids, list):
        raise RequestError("'room_ids'는 목록이어야 합니다.")
    unsupported = data.get("unsupported") or []
    if not isinstance(unsupported, list):
        unsupported = [str(unsupported)]
    return CourseRequest(
        unavailable=windows("unavailable"),
        allowed=windows("allowed"),
        preferred=windows("preferred"),
        avoid=windows("avoid"),
        duration_minutes=dur,
        min_capacity=mc,
        building=(room.get("building") or None),
        room_ids=[str(r) for r in rids],
        summary=str(data.get("summary") or ""),
        unsupported=[str(u) for u in unsupported],
        source=source,
        raw_text=raw_text,
    )
