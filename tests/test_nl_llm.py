import json
from types import SimpleNamespace

import pytest

from core import llm
from core.constraints import REQUEST_SCHEMA
from core.nlparse import ParseContext, parse_request, rule_parse

CTX = ParseContext(code="X", name="역학", duration=90, enrollment=48, current=(2, 840, 930),
                   buildings=["이과대학", "과학관", "공동강의동"])


@pytest.fixture(autouse=True)
def reset_llm(monkeypatch):
    monkeypatch.setattr(llm, "_LAST_FAIL", 0.0)
    monkeypatch.setattr(llm, "LAST_ERROR", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def windows(d, key):
    return [(w["day"], w["start"], w["end"]) for w in d[key]]


@pytest.mark.parametrize("text,key,expected", [
    ("목요일 오후는 안 되고, 가능하면 오전으로", "unavailable", [("목", "12:00", "18:00")]),
    ("목요일 오후는 안 되고, 가능하면 오전으로", "preferred", [(None, "09:00", "12:00")]),
    ("수요일에만 가능해요", "allowed", [("수", "09:00", "18:00")]),
    ("금요일은 피해주세요", "avoid", [("금", "09:00", "18:00")]),
    ("화요일 2시부터 5시까지는 학회라 불가합니다", "unavailable", [("화", "14:00", "17:00")]),
    ("목, 금은 안 됩니다", "unavailable", [("목", "09:00", "18:00"), ("금", "09:00", "18:00")]),
    ("오후 1시 전에는 안 돼요", "unavailable", [(None, "09:00", "13:00")]),
    ("다른 날로 옮겨 주세요", "unavailable", [("수", "09:00", "18:00")]),
])
def test_rule_parser_windows(text, key, expected):
    assert windows(rule_parse(text, CTX), key) == expected


def test_rule_parser_duration_and_room():
    assert rule_parse("시험 시간을 120분으로 늘려줘", CTX)["duration_minutes"] == 120
    assert rule_parse("시험을 2시간 반으로 해 주세요", CTX)["duration_minutes"] == 150
    d = rule_parse("100석 이상 강의실로, 공동강의동이면 좋겠어요", CTX)
    assert d["room"]["min_capacity"] == 100 and d["room"]["building"] == "공동강의동"
    assert rule_parse("큰 강의실로 바꿔 주세요", CTX)["room"]["min_capacity"] == 80   # 48×1.5 → 80


def test_rule_parser_unsupported():
    d = rule_parse("학생들 부담이 적었으면 합니다", CTX)
    assert d["unsupported"] and not d["unavailable"] and not d["preferred"]


def test_no_key_uses_rule_mode():
    req, mode, note = parse_request("금요일 안 돼요", CTX)
    assert mode == "규칙 기반" and note is None
    assert llm.status()[1] is False


def _fake_response(text):
    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


def test_llm_result_is_used_when_valid(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    data = {"unavailable": [{"day": "목", "start": "12:00", "end": "18:00"}], "allowed": [],
            "preferred": [{"day": None, "start": "09:00", "end": "12:00"}], "avoid": [], "duration_minutes": None,
            "room": {"min_capacity": None, "building": None, "room_ids": []},
            "summary": "목요일 오후 불가, 오전 선호", "unsupported": []}
    seen = {}

    def fake_create(system, user, fmt):
        seen["system"], seen["fmt"] = system, fmt
        return _fake_response(json.dumps(data, ensure_ascii=False))
    monkeypatch.setattr(llm, "_create", fake_create)
    req, mode, note = parse_request("목요일 오후는 안 되고, 가능하면 오전으로", CTX)
    assert mode == "AI" and note is None and req.source == "AI"
    assert req.summary == "목요일 오후 불가, 오전 선호"
    assert seen["fmt"]["schema"] == REQUEST_SCHEMA
    assert "역학" in seen["system"] and "$" not in seen["system"].replace("$day", "")


def test_llm_invalid_output_falls_back(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    bad = {"unavailable": [{"day": "월", "start": "18:00", "end": "12:00"}]}   # 종료가 시작보다 빠름 → 검증 실패
    monkeypatch.setattr(llm, "_create", lambda *a: _fake_response(json.dumps(bad, ensure_ascii=False)))
    req, mode, note = parse_request("금요일 안 돼요", CTX)
    assert mode == "규칙 기반" and "규칙 기반" in note
    assert [(w.day, w.start) for w in req.unavailable] == [(4, 540)]


def test_llm_exception_falls_back_and_cools_down(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    calls = []

    def boom(*a):
        calls.append(1)
        raise ConnectionError("network down")
    monkeypatch.setattr(llm, "_create", boom)
    req, mode, note = parse_request("금요일 안 돼요", CTX)
    assert mode == "규칙 기반" and note
    assert llm.available() is False and "대체 모드" in llm.status()[0]
    parse_request("금요일 안 돼요", CTX)          # 쿨다운 중에는 다시 호출하지 않는다
    assert len(calls) == 1


def test_prompts_exist():
    for name in ("parse_constraints", "explain_assignment", "impact_analysis"):
        assert len(llm.load_prompt(name)) > 100
    assert "지어내지" in llm.load_prompt("explain_assignment")


def test_explain_numbers_come_from_data(default_data, default_result):
    from core.explain import course_facts, evaluate_slots, template_reason
    from core.settings import Settings
    from core.validator import validate
    st = Settings()
    rep = validate(default_data, default_result.schedule, st)
    for code in list(default_result.schedule.course_code)[:5]:
        f = course_facts(default_data, default_result.schedule, st, {}, rep.per_course, code)
        assert f["overload_students"] == rep.per_course[code]["overload_students"]
        txt = template_reason(f)
        assert f"수강생 {default_data.course_map[code].enrollment}명" in txt
        slots = evaluate_slots(default_data, default_result.schedule, st, {}, code)
        assert any(s["day"] == f["day"] and s["start"] == int(f["start"][:2]) * 60 + int(f["start"][3:]) for s in slots)
