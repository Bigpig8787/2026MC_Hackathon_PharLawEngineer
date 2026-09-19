"""recommend_plan 測試：Gemini 以假回應取代，不打網路也不花額度。"""
import json

import pytest

from commute_agent.skills import recommend_plan as rp
from commute_agent.skills.recommend_plan import (INSTRUCTION, MODE_FOOTPRINT,
                                                 PROMPT_FIELDS, recommend_plan)

COURSE = {"name": "數位IC設計", "day_zh": "星期一", "start_time": "09:00",
          "location": "資訊系館4264", "building": "B501 資訊工程系館"}


WEATHER = {"weather": "短暫陣雨", "rain_probability": 70, "will_rain": True,
           "temperature": "31", "apparent_temperature": "36"}


def option(mode, label, minutes, risks=()):
    return {"mode": mode, "label": label, "minutes": minutes,
            "leave_by": "2026-09-21T08:33:00+08:00", "late_by": 0,
            "risks": list(risks), "buffer_minutes": 8, "is_estimate": False,
            "weather": dict(WEATHER),
            # 這些欄位不該被塞進 prompt
            "parking": {"name": "某停車場"}, "bike": {"map_link": "http://x"}}


COMPARISON = {
    "status": "ok", "course": COURSE, "now": "2026-09-21T08:00:00+08:00",
    "class_starts_at": "2026-09-21T09:00:00+08:00",
    "options": [option("walking", "步行", 19), option("driving", "機車／開車", 7),
                option("bicycling", "自行車", None, ["附近沒有可借的車"])],
    "best": option("driving", "機車／開車", 7),
}


@pytest.fixture
def world(monkeypatch):
    state = {"answer": {"chosen_mode": "driving", "reason": "最快",
                        "warnings": ["注意路口"]},
             "raise": None, "key": "fake-key", "preference": "我怕熱",
             "sent": []}

    class FakeModels:
        def generate_content(self, model, contents, config):
            state["sent"].append(contents)
            if state["raise"]:
                raise state["raise"]
            return type("R", (), {"text": json.dumps(state["answer"],
                                                     ensure_ascii=False)})()

    class FakeClient:
        def __init__(self, api_key=None):
            self.models = FakeModels()

    monkeypatch.setattr("google.genai.Client", FakeClient)
    monkeypatch.setattr(rp, "compare_plans", lambda o, v, p="": dict(COMPARISON))
    monkeypatch.setattr(rp, "load_settings",
                        lambda: type("S", (), {
                            "gemini_api_key": state["key"],
                            "gemini_model": "gemini-3-flash-preview",
                            "commute_preference": state["preference"]})())
    return state


def test_model_choice_is_used_when_valid(world):
    result = recommend_plan()
    assert result["source"] == "gemini"
    assert result["chosen_mode"] == "driving"
    assert result["reason"] == "最快"
    assert result["warnings"] == ["注意路口"]


def test_comparison_is_returned_for_the_interface(world):
    assert recommend_plan()["comparison"]["options"][0]["mode"] == "walking"


def test_preference_is_sent_to_the_model(world):
    recommend_plan()
    payload = world["sent"][0][1]
    assert "我怕熱" in payload


def test_heavy_fields_are_not_sent_to_the_model(world):
    # 座標與連結對取捨沒有幫助，塞進 prompt 只會變貴又讓模型分心
    recommend_plan()
    sent = json.loads(world["sent"][0][1])
    assert set(sent["options"][0]) == set(PROMPT_FIELDS)


def test_weather_is_sent_to_the_model(world):
    # 沒有天氣與體感溫度，模型沒辦法在「淋雨」與「快幾分鐘」之間取捨
    recommend_plan()
    sent = json.loads(world["sent"][0][1])
    assert sent["options"][0]["weather"] == WEATHER


def test_instruction_states_the_carbon_ranking(world):
    # 各方式的碳排高低是確定的事實，要寫在 prompt 裡，不能讓模型自己想
    for mode, note in MODE_FOOTPRINT.items():
        assert f"- {mode}：{note}" in INSTRUCTION


def test_model_failure_falls_back_to_rules(world):
    # 額度用盡走這條，畫面不能因此開天窗
    world["raise"] = RuntimeError("quota exhausted")
    result = recommend_plan()
    assert result["source"] == "rules"
    assert result["chosen_mode"] == "driving"
    assert "規則排序" in result["reason"]


def test_missing_key_falls_back_without_calling_the_model(world):
    world["key"] = ""
    result = recommend_plan()
    assert result["source"] == "rules"
    assert world["sent"] == []


def test_mode_outside_the_options_is_rejected(world):
    world["answer"] = {"chosen_mode": "teleport", "reason": "瞬移最快"}
    result = recommend_plan()
    assert result["source"] == "rules"
    assert "teleport" in result["reason"]


def test_unavailable_mode_is_rejected(world):
    # 自行車的 minutes 是 None，代表附近沒車可借，模型不該選它
    world["answer"] = {"chosen_mode": "bicycling", "reason": "騎車最舒服"}
    assert recommend_plan()["source"] == "rules"


def test_malformed_json_falls_back(world, monkeypatch):
    class BadModels:
        def generate_content(self, model, contents, config):
            return type("R", (), {"text": "這不是 JSON"})()

    class BadClient:
        def __init__(self, api_key=None):
            self.models = BadModels()

    monkeypatch.setattr("google.genai.Client", BadClient)
    assert recommend_plan()["source"] == "rules"


def test_comparison_error_is_propagated(world, monkeypatch):
    monkeypatch.setattr(rp, "compare_plans",
                        lambda o, v, p="": {"status": "no_class", "options": [], "best": None})
    result = recommend_plan()
    assert result["status"] == "no_class"
    assert result["chosen_mode"] is None
