"""scan_room_sign 測試：Gemini 與成大 GIS 都換成假的，只驗「讀到的字一律回 GIS 驗證」。"""
import pytest

from commute_agent.skills import scan_room_sign as srs

PNG = b"\x89PNG\r\n\x1a\nfake"


def room(code, building_id, building_name, floor, exact=True):
    return {"room_code": code, "room_name": "", "floor": floor, "building_id": building_id,
            "building_name": building_name, "exact_match": exact}


TABLE = {
    "4264": room("4264", "B501", "B501 資訊工程系館", "2F"),
    "4364": room("4364", "B501", "B501 資訊工程系館", "3F"),
    "4164": room("4164", "B501", "B501 資訊工程系館", "1F"),
    "27103": room("27103", "A004", "A004 雲平大樓東棟", "1F"),
    "4999": room("4999", "B501", "B501 資訊工程系館", "", exact=True),
    "fuzzy": room("4265", "B501", "B501 資訊工程系館", "2F", exact=False),
}


@pytest.fixture
def world(monkeypatch):
    state = {"reads": {"room_codes": ["4264"], "building_text": "", "floor_text": "",
                       "confidence": "high", "note": ""}, "asked": 0}

    def ask(image_bytes, mime_type):
        state["asked"] += 1
        if isinstance(state["reads"], Exception):
            raise state["reads"]
        return state["reads"]

    def lookup(code):
        row = TABLE.get(code)
        return ({"status": "ok", "candidates": [row]} if row
                else {"status": "not_found", "candidates": []})

    monkeypatch.setattr(srs, "_ask_gemini", ask)
    monkeypatch.setattr(srs, "lookup_room", lookup)
    return state


# ---- 讀照片 ----

def test_unsupported_image_type_is_refused_before_asking_the_model(world):
    result = srs.read_room_sign(PNG, "application/pdf")
    assert result["status"] == "error" and world["asked"] == 0


def test_empty_image_is_refused(world):
    assert srs.read_room_sign(b"", "image/png")["status"] == "error"


def test_oversized_image_is_refused(world):
    big = b"x" * (srs.MAX_IMAGE_BYTES + 1)
    assert "上限" in srs.read_room_sign(big, "image/png")["error_message"]


def test_codes_are_cleaned_deduplicated_and_capped(world):
    world["reads"] = {"room_codes": [" 4264 ", "4264", "", "27103", "x" * 40, "a", "b"],
                      "confidence": "weird"}
    result = srs.read_room_sign(PNG, "image/png")
    assert result["room_codes"] == ["4264", "27103", "a"]
    assert result["confidence"] == "low"          # 不認得的信心值當作最低


def test_model_failure_is_reported_not_raised(world):
    world["reads"] = srs.SignError("Gemini 預付額度已用盡（HTTP 402）")
    result = srs.read_room_sign(PNG, "image/png")
    assert result["status"] == "error" and "402" in result["error_message"]


# ---- 驗證與定位 ----

def test_a_code_the_gis_confirms_becomes_the_current_location(world):
    result = srs.scan_room_sign(PNG, "image/png")
    assert result["status"] == "ok"
    assert result["here"]["building_name"] == "B501 資訊工程系館"
    assert result["here"]["floor"] == "2F"
    assert result["target"] is None and result["relation"] is None


def test_a_code_the_gis_does_not_know_is_not_believed(world):
    # 模型讀錯一個數字不能把人帶到別間：查不到就承認沒認出來
    world["reads"] = {"room_codes": ["9999"], "confidence": "high"}
    result = srs.scan_room_sign(PNG, "image/png", "4264")
    assert result["status"] == "not_recognized"
    assert result["here"] is None and "9999" in result["note"]


def test_fuzzy_matches_are_not_accepted(world):
    world["reads"] = {"room_codes": ["fuzzy"], "confidence": "high"}
    assert srs.scan_room_sign(PNG, "image/png")["status"] == "not_recognized"


def test_the_first_verified_code_wins(world):
    world["reads"] = {"room_codes": ["9999", "27103", "4264"], "confidence": "medium"}
    assert srs.scan_room_sign(PNG, "image/png")["here"]["room_code"] == "27103"


def test_nothing_readable_gives_a_helpful_retry_hint(world):
    world["reads"] = {"room_codes": [], "confidence": "low"}
    result = srs.scan_room_sign(PNG, "image/png")
    assert result["status"] == "not_recognized" and "再拍一次" in result["note"]


def test_model_failure_surfaces_as_an_error(world):
    world["reads"] = srs.SignError("Gemini 請求太頻繁，已達速率上限（HTTP 429）")
    result = srs.scan_room_sign(PNG, "image/png", "4264")
    assert result["status"] == "error" and "429" in result["error_message"]


# ---- 目標相對位置 ----

def relation(here_code, target_code, world):
    world["reads"] = {"room_codes": [here_code], "confidence": "high"}
    return srs.scan_room_sign(PNG, "image/png", target_code)["relation"]


def test_same_floor(world):
    r = relation("4264", "4264", world)
    assert r["kind"] == "same_floor" and "這一層" in r["text"]


def test_target_upstairs(world):
    r = relation("4264", "4364", world)
    assert r["kind"] == "up" and r["floors"] == 1 and "往上 1 層" in r["text"]


def test_target_downstairs(world):
    r = relation("4264", "4164", world)
    assert r["kind"] == "down" and r["floors"] == -1 and "往下 1 層" in r["text"]


def test_target_in_another_building(world):
    r = relation("4264", "27103", world)
    assert r["kind"] == "other_building" and "雲平大樓東棟" in r["text"]


def test_missing_floor_data_is_admitted(world):
    r = relation("4264", "4999", world)
    assert r["kind"] == "unknown" and "樓層資料不全" in r["text"]


def test_unknown_target_room_gives_no_relation(world):
    result = srs.scan_room_sign(PNG, "image/png", "0000")
    assert result["status"] == "ok" and result["target"] is None and result["relation"] is None


# ---- 樓層字串 ----

@pytest.mark.parametrize("text,level", [
    ("3F", 3), ("3f", 3), ("12F", 12), ("2", 2), ("B1", -1), ("B1F", -1), ("B2", -2),
    ("RF", None), ("", None), (None, None), ("大廳", None),
])
def test_floor_levels(text, level):
    assert srs.floor_level(text) == level


# ---- 讀錯一個字：找 GIS 裡相近的教室給使用者確認 ----
# 真實案例：門牌其實是 A1302（B406 三系館鋼構區 3F 的演講廳），Gemini 讀成 A1301、A1308。
# GIS 裡有 A1302、A1305、A1306、A1307，但沒有 A1301 與 A1308。

ROOMS = [
    room("A1302", "B103", "B406 三系館鋼構區", "3F"),
    room("A1305", "B101", "B404 資源工程系大樓", "3F"),
    room("A1306", "B103", "B406 三系館鋼構區", "3F"),
    room("65A13", "B502", "B502 資訊工程系大樓", "10F"),      # 含 A13 但差很多，不該被建議
    {**room("", "B103", "B406 三系館鋼構區", "3F"), "room_code": ""},   # 沒有代碼的空間
]


def substring_lookup(query):
    """跟成大 GIS 一樣做子字串比對；exact_match 只有代碼完全相同才為真。"""
    q = query.upper()
    rows = [{**r, "exact_match": r["room_code"].upper() == q}
            for r in ROOMS if r["room_code"] and q in r["room_code"].upper()]
    return {"status": "ok" if rows else "not_found", "candidates": rows}


@pytest.mark.parametrize("a,b,distance", [
    ("A1301", "A1301", 0), ("A1301", "A1302", 1), ("A1308", "A1302", 1),
    ("A1301", "A1201", 1), ("A1301", "A130", 1), ("A1301", "A13012", 1),
    ("A1301", "65A13", 4),      # 前面補 65（2）、後面去掉 01（2）；差很多，不會被當成相近
    ("", "AB", 2),
])
def test_edit_distance(a, b, distance):
    assert srs.edit_distance(a, b) == distance


def test_a_misread_code_finds_the_room_that_differs_by_one_character():
    found = srs.similar_rooms(["A1301", "A1308"], lookup=substring_lookup)
    assert [r["room_code"] for r in found] == ["A1302", "A1305", "A1306"]
    first = found[0]
    assert first["building_name"] == "B406 三系館鋼構區" and first["floor"] == "3F"
    assert first["resembles"] == ["A1301", "A1308"]       # 兩個讀到的代碼都指向它


def test_rooms_that_differ_a_lot_are_not_suggested():
    codes = [r["room_code"] for r in srs.similar_rooms(["A1301"], lookup=substring_lookup)]
    assert "65A13" not in codes


def test_a_code_that_exists_is_never_suggested_against_itself():
    codes = [r["room_code"] for r in srs.similar_rooms(["A1302"], lookup=substring_lookup)]
    assert "A1302" not in codes


def test_too_short_a_code_gives_no_suggestions_and_costs_no_lookups():
    calls = []
    assert srs.similar_rooms(["A13"], lookup=lambda q: calls.append(q) or substring_lookup(q)) == []
    assert calls == []


def test_suggestions_are_capped():
    many = [room(f"A130{i}", "B103", "B406", "3F") for i in range(10)]
    lookup = lambda q: {"status": "ok", "candidates": [
        {**r, "exact_match": False} for r in many if q in r["room_code"]]}
    assert len(srs.similar_rooms(["A1300"], lookup=lookup, limit=3)) == 3


def test_scan_offers_suggestions_instead_of_a_dead_end(world, monkeypatch):
    monkeypatch.setattr(srs, "lookup_room", substring_lookup)
    world["reads"] = {"room_codes": ["A1301", "A1308"], "confidence": "high"}
    result = srs.scan_room_sign(PNG, "image/png", "A1306")
    assert result["status"] == "not_recognized" and result["here"] is None
    assert [s["room_code"] for s in result["suggestions"]] == ["A1302", "A1305", "A1306"]
    assert "A1301、A1308" in result["note"] and "讀錯了一個字" in result["note"]


def test_scan_without_any_lookalike_asks_for_a_retake_or_manual_entry(world):
    world["reads"] = {"room_codes": ["9999"], "confidence": "high"}
    result = srs.scan_room_sign(PNG, "image/png")
    assert result["suggestions"] == []
    assert "直接輸入" in result["note"] and "再拍一次" in result["note"]


# ---- 使用者自己輸入或點選確認 ----

@pytest.fixture
def gis(monkeypatch):
    monkeypatch.setattr(srs, "lookup_room", substring_lookup)


def test_confirming_a_real_code_gives_the_location_and_relation(gis):
    result = srs.confirm_room("A1302", "A1306")
    assert result["status"] == "ok"
    assert result["here"]["building_name"] == "B406 三系館鋼構區" and result["here"]["floor"] == "3F"
    assert result["relation"]["kind"] == "same_floor"
    assert result["sign"]["confidence"] == "user"


def test_confirming_with_a_target_in_another_building(gis):
    assert srs.confirm_room("A1302", "A1305")["relation"]["kind"] == "other_building"


def test_confirmation_is_still_checked_against_the_gis(gis):
    # 使用者自己打的代碼也要在成大存在，打錯了照樣不採用
    result = srs.confirm_room("A1301")
    assert result["status"] == "not_recognized" and result["here"] is None
    assert [s["room_code"] for s in result["suggestions"]][:1] == ["A1302"]
    assert "代碼相近" in result["note"]


def test_confirming_nothing_is_an_error(gis):
    assert srs.confirm_room("   ")["status"] == "error"
