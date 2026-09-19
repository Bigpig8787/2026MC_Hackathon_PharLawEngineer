"""campus_walk 測試：Google Routes 與 Gemini 都用假回應，不打網路也不花額度。"""
import pytest

from commute_agent.skills import campus_walk as cw
from commute_agent.skills.campus_walk import plan_campus_walk

LOT = ("三系館地下機車停車場", 22.9978, 120.2216)
DEST = ("B501 資訊工程系館", 22.9972, 120.2208)

LANDMARKS = [{"name": "三系館鋼構區", "lat": 22.9979, "lon": 120.2217},
             {"name": "資訊工程系館", "lat": 22.9972, "lon": 120.2208}]


@pytest.fixture
def world(monkeypatch):
    state = {
        "route": {"status": "ok", "minutes": 2, "distance_m": 159,
                  "points": [(22.9978, 120.2216), (22.9975, 120.2212),
                             (22.9972, 120.2208)]},
        "buildings": {"status": "ok", "buildings": list(LANDMARKS)},
        "answer": {"steps": ["從三系館鋼構區往西走。", "看到資訊工程系館就到了。"],
                   "summary": "兩分鐘的路。"},
        "raise": None, "key": "fake-key", "sent": [],
    }

    class FakeModels:
        def generate_content(self, model, contents, config):
            state["sent"].append(contents)
            if state["raise"]:
                raise state["raise"]
            import json
            return type("R", (), {"text": json.dumps(state["answer"],
                                                     ensure_ascii=False)})()

    class FakeClient:
        def __init__(self, api_key=None):
            self.models = FakeModels()

    monkeypatch.setattr("google.genai.Client", FakeClient)
    monkeypatch.setattr(cw, "compute_route",
                        lambda o, d, mode="walking", with_path=False: state["route"])
    monkeypatch.setattr(cw, "buildings_in_bbox", lambda bbox, limit=40: state["buildings"])
    monkeypatch.setattr(cw, "load_settings",
                        lambda: type("S", (), {"gemini_api_key": state["key"],
                                               "gemini_model": "gemini-3-flash-preview"})())
    return state


def walk(**kw):
    return plan_campus_walk(*LOT, *DEST, **kw)


def test_the_route_is_drawn_as_percentages_of_the_map(world):
    found = walk()
    assert found["status"] == "ok"
    assert len(found["path"]) == 3
    assert all(0 <= pt["left"] <= 100 and 0 <= pt["top"] <= 100 for pt in found["path"])


def test_the_two_ends_are_marked(world):
    found = walk()
    assert found["from_point"] == found["path"][0]
    assert found["to_point"] == found["path"][-1]


def test_a_real_google_route_is_labelled_as_such(world):
    found = walk()
    assert found["is_real_path"] is True
    assert (found["minutes"], found["distance_m"]) == (2, 159)
    assert found["note"] == ""


def test_a_failed_route_falls_back_to_a_straight_line_and_says_so(world):
    # 直線不是真的路，畫得出來不代表走得通，一定要講明
    world["route"] = {"status": "error", "error_message": "未設定 GOOGLE_MAPS_API_KEY"}
    found = walk()
    assert found["is_real_path"] is False
    assert found["minutes"] is None
    assert len(found["path"]) == 2
    assert "直線" in found["note"]


def test_directions_come_back_when_the_landmarks_are_real(world):
    found = walk()["directions"]
    assert found["source"] == "gemini"
    assert len(found["steps"]) == 2


def test_only_nearby_buildings_are_offered_to_the_model(world):
    walk()
    sent = world["sent"][0][1]
    assert "三系館鋼構區" in sent
    assert "活動中心" not in sent


def test_an_invented_landmark_throws_the_whole_answer_away(world):
    # 講錯地標會讓人走反方向，比沒有指路更糟
    world["answer"] = {"steps": ["先經過學生活動中心。"], "summary": ""}
    found = walk()["directions"]
    assert found["source"] == "none"
    assert "學生活動中心" in found["note"]


def test_a_verb_stuck_to_a_real_name_is_not_treated_as_invented(world):
    # 正規表示式會抓到「從三系館」，那仍然是清單裡那一棟
    world["answer"] = {"steps": ["從三系館鋼構區出來後往西。"], "summary": ""}
    assert walk()["directions"]["source"] == "gemini"


def test_a_short_name_for_a_real_building_is_accepted(world):
    world["answer"] = {"steps": ["走到資訊工程系館就到了。"], "summary": ""}
    assert walk()["directions"]["source"] == "gemini"


def test_model_failure_leaves_the_map_usable(world):
    world["raise"] = RuntimeError("quota exhausted")
    found = walk()
    assert found["status"] == "ok"
    assert found["path"]
    assert found["directions"]["source"] == "none"


def test_no_key_means_no_model_call(world):
    world["key"] = ""
    assert walk()["directions"]["source"] == "none"
    assert world["sent"] == []


def test_missing_coordinates_are_refused():
    found = plan_campus_walk("某停車場", None, None, "某大樓", 22.9, 120.2)
    assert found["status"] == "error"
    assert "座標" in found["error_message"]
