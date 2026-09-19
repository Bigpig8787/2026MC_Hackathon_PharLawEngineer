"""課表視覺化頁面的後端。

這層做的是「串接」：先問課表下一堂是什麼，再用教室代碼查大樓，最後組導航連結。
這其實就是 README 規劃中 Skill 層要做的事，等 SkillToolset 上線後可以搬過去；
在那之前先放這裡，Tool 層維持各自獨立、互不呼叫。

課表來源分兩份，刻意不共用：
- `data/class_schedule.json` 是版控裡的範例，給 Agent 工具與測試用，本頁不會寫它；
- 使用者上傳辨識出來的課表寫進 `USER_SCHEDULE_PATH`（預設 data/user_schedule.json），
  沒有這個檔時頁面就是空的 —— 「預設空課表，上傳後才有東西」是刻意的。

啟動：
    ./.venv/bin/python -m web.server        # http://localhost:8080
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api import load_settings
from commute_agent.tools.class_schedule import PROJECT_ROOT, find_classes, load_courses
from commute_agent.tools.floor_plan import PICTURE_DIR, PICTURE_URL_PREFIX
from commute_agent.tools.ncku_room import lookup_room
from commute_agent.tools.schedule_ocr import OCRError, extract_schedule_from_image
from commute_agent.skills.bike_plan import plan_bike_journey
from commute_agent.skills.classroom_guide import locate_classroom
from commute_agent.skills.locate_place import locate_course_place
from commute_agent.skills.departure_plan import plan_departure
from commute_agent.skills.recommend_plan import recommend_plan
from commute_agent.skills.parking_plan import load_lot_locations, plan_parking
from commute_agent.tools.tdx_bus import get_bus_eta
from commute_agent.tools.youbike import get_bike_status
from commute_agent.tools.route_link import TRAVEL_MODE_LABELS, build_route_link

WEB_DIR = Path(__file__).resolve().parent

app = FastAPI(title="NCKU Smart Commute")

# 平面圖截圖放在版本庫的 picture/，直接以靜態檔供應；資料夾不存在時不掛，
# 免得整個服務起不來（這些圖是選配，沒有圖頁面照常運作）
if PICTURE_DIR.is_dir():
    app.mount(PICTURE_URL_PREFIX, StaticFiles(directory=PICTURE_DIR), name="picture")


def _abs_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def user_schedule_path() -> Path:
    """使用者上傳辨識出來的課表位置。內含個人課表，已被 .gitignore 擋掉。"""
    return _abs_path(os.getenv("USER_SCHEDULE_PATH", "data/user_schedule.json").strip()
                     or "data/user_schedule.json")


def sample_schedule_path() -> Path:
    """版控裡的範例課表。只讀不寫，作為 demo 時辨識失敗的備援。"""
    return _abs_path(load_settings().class_schedule_path)


def resolve_now(raw: str | None, tz: str) -> tuple[datetime, bool, str | None]:
    """決定「現在」是幾點。

    回傳 (時間, 是否為模擬時間, 錯誤訊息)。前端的時間模擬會傳 ISO 字串進來，
    讓 demo 可以跳到上課前幾分鐘 —— 查的仍是真實 API，只是換個時間點問，
    所以不會有假資料，但畫面上必須標示出來，這就是第二個回傳值的用途。
    """
    zone = ZoneInfo(tz)
    if not (raw or "").strip():
        return datetime.now(zone), False, None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError:
        return datetime.now(zone), False, f"無法解析的時間格式：{raw!r}"
    # 前端的 datetime-local 不帶時區，一律當成設定裡的時區
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed, True, None


def _resolve_building(entry: dict) -> dict:
    """用教室代碼查出真正的大樓，查不到就退回課表上的原始寫法。

    課表寫的大樓名稱不一定正確（例如「資訊系館」實際可能是 B501 或 B502），
    所以一律以 lookup_room 的 building_name 為準，並標記是否做過修正。
    """
    enriched = {**entry, "building_name": "", "floor": "", "lookup_status": "skipped",
                "corrected": False}
    query = entry.get("room_query")
    if not query:
        enriched["lookup_status"] = "no_room_code"
        return enriched

    result = lookup_room(query)
    enriched["lookup_status"] = result["status"]
    exact = [c for c in result.get("candidates", []) if c["exact_match"]]
    chosen = exact[0] if exact else (result.get("candidates") or [None])[0]
    if chosen:
        enriched["building_name"] = chosen["building_name"]
        enriched["floor"] = chosen["floor"]
        # 課表寫「資訊系館」但實際是「B501 資訊工程系館」，值得提醒使用者
        enriched["corrected"] = chosen["building_name"] not in entry["location"]
    return enriched


def _with_route(entry: dict | None, origin: str, travel_mode: str) -> dict | None:
    """把課表上那一行變成可以按下去導航的目的地。

    地點一律先過 locate_course_place：課表寫的「社科院大樓階梯教室－心理」
    這種字串，Google 會對到名字相近的別棟，成大 GIS 則根本查不到，
    那支會依序用教室代碼、GIS、Gemini 讀出的關鍵字去換出經過驗證的座標。
    """
    if entry is None:
        return None
    enriched = _resolve_building(entry)
    place = locate_course_place(entry["location"], entry.get("room_query", ""))
    if place["status"] == "ok":
        target = (place["lat"], place["lon"])
        # GIS 查不到教室代碼時，仍然把解析出的大樓名稱補上，別讓畫面空著
        if not enriched["building_name"] and place["name"]:
            enriched["building_name"] = place["name"]
            enriched["corrected"] = place["name"] not in entry["location"]
    else:
        target = enriched["building_name"] or enriched["location"]
    enriched["place"] = {k: place.get(k) for k in
                         ("status", "source", "is_verified", "name", "build_id",
                          "lat", "lon", "gemini_keyword", "error_message")}
    enriched["route_link"] = build_route_link(target, origin=origin or None,
                                              travel_mode=travel_mode)
    enriched["origin"] = origin
    enriched["travel_mode"] = travel_mode
    return enriched


def _parking_for(entry: dict | None, vehicle_type: str, origin: str) -> dict | None:
    """騎車或開車時才需要停車建議；目的地查不到大樓就不猜。

    這裡只列停車場，不算分段時間——那由 plan_departure 負責，
    兩邊都算會讓同一趟行程重複呼叫 Google 兩次。
    """
    if entry is None or not entry.get("building_name"):
        return None
    plan = plan_parking(entry["building_name"], vehicle_type)
    recommended = plan.get("recommended")
    if recommended:
        # 停車場名稱 Google 多半找不到，但對照表裡有座標，直接用座標最準
        known = load_lot_locations().get(recommended["name"], {})
        target = ((known["lat"], known["lon"]) if known.get("lat") is not None
                  else recommended["name"])
        recommended["route_link"] = build_route_link(
            target, origin=origin or None, travel_mode="driving")
    return plan


def _save_schedule(schedule: dict) -> Path:
    path = user_schedule_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schedule, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _bikes_for(entry: dict | None, origin: str) -> dict | None:
    """騎 YouBike 時，起點要借得到車、終點要還得了車，兩邊都要查。"""
    if entry is None or not origin:
        return None
    borrow = get_bike_status(origin, "bike")
    ret = get_bike_status(entry["building_name"] or entry["location"], "dock")
    return {"borrow": borrow, "return": ret}


@app.get("/api/state")
def state(mode: str = "walking", vehicle: str = "機車",
          origin: str | None = None, now: str | None = None) -> JSONResponse:
    if mode not in TRAVEL_MODE_LABELS:
        return JSONResponse({"error": f"不支援的交通模式：{mode}"}, status_code=400)

    settings = load_settings()
    moment, simulated, time_error = resolve_now(now, settings.timezone)
    if time_error:
        return JSONResponse({"error": time_error}, status_code=400)

    # 使用者在頁面上填了出發地就用它，沒填才退回 .env 的預設地址
    start = (origin or "").strip() or settings.default_origin

    path = user_schedule_path()
    base = {
        "now": moment.isoformat(timespec="seconds"),
        "simulated": simulated,
        "origin": start,
        "default_origin": settings.default_origin,
        "using_default_origin": start == settings.default_origin,
        "travel_mode": mode,
        "travel_mode_label": TRAVEL_MODE_LABELS[mode],
        "vehicle_type": vehicle,
        "modes": TRAVEL_MODE_LABELS,
        "has_sample": sample_schedule_path().is_file(),
    }

    # 還沒上傳課表是正常起始狀態，不是錯誤：回空課表讓前端顯示上傳引導
    if not path.is_file():
        return JSONResponse({**base, "has_schedule": False, "schedule_source": "",
                             "current_class": None, "next_class": None,
                             "departure": None, "parking": None, "bikes": None,
                             "bus": None, "courses": []})

    try:
        courses = load_courses(path)
        source = json.loads(path.read_text(encoding="utf-8")).get("source", "")
    except (ValueError, OSError) as exc:
        return JSONResponse({**base, "has_schedule": False, "courses": [],
                             "current_class": None, "next_class": None,
                             "departure": None, "parking": None, "bikes": None,
                             "bus": None, "schedule_source": "",
                             "error": f"課表檔案讀取失敗：{exc}"}, status_code=200)

    current, upcoming = find_classes(courses, moment)
    next_class = _with_route(upcoming, start, mode)

    # 出發規劃一次算完路程、緩衝與天氣；騎車模式的分段時間也在裡面，
    # 所以上面的停車查詢不再重算，避免同一趟路重複呼叫 Google。
    # 傳入使用者上傳的那份課表，否則出發時間會依範例課表算，跟畫面顯示的課不同堂
    departure = (plan_departure(start, mode, vehicle, str(path))
                 if (next_class and start) else None)

    return JSONResponse({
        **base,
        "has_schedule": True,
        "schedule_source": source,
        "current_class": _with_route(current, start, mode),
        "next_class": next_class,
        "departure": departure,
        # 每個模式只查自己用得到的資料：停車位要掃七個校區、公車有速率限制、
        # YouBike 要下載 6 MB，全部都查會讓每次換模式都變慢又浪費額度。
        "parking": _parking_for(next_class, vehicle, start) if mode == "driving" else None,
        "bikes": _bikes_for(next_class, start) if mode == "bicycling" else None,
        "bus": get_bus_eta(start) if (mode == "transit" and start) else None,
        "courses": courses,
    })


@app.get("/api/recommend")
def recommend(origin: str | None = None, vehicle: str = "機車") -> JSONResponse:
    """比較四種交通方式並請 Gemini 給建議。

    頁面載入時就自動打，不必等使用者按按鈕 —— 建議本來就是這頁要回答的問題，
    讓人多按一下只是把答案藏起來。但它要跑四次路程規劃（約十幾秒）又會用掉
    一次 Gemini 額度，所以前端以「課＋出發地＋車種」為鍵去重，
    切換交通方式或背景輪詢時不會重打。
    """
    settings = load_settings()
    start = (origin or "").strip() or settings.default_origin
    if not start:
        return JSONResponse({"error": "沒有出發地"}, status_code=400)

    path = user_schedule_path()
    if not path.is_file():
        return JSONResponse({"error": "還沒有課表，無法給建議"}, status_code=400)

    result = recommend_plan(start, vehicle, str(path))
    return JSONResponse(result,
                        status_code=200 if result["status"] == "ok" else 400)


@app.get("/api/classroom")
def classroom(q: str, origin: str | None = None, mode: str = "walking") -> JSONResponse:
    """查一間教室在哪棟大樓、哪一層，並附上該層平面圖。

    跟 /api/state 分開是因為它多打兩次成大 GIS；課表頁載入時不必等它，
    畫面先出來、平面圖後補，比整頁慢兩秒好。
    """
    settings = load_settings()
    start = (origin or "").strip() or settings.default_origin
    result = locate_classroom(q, start, mode)
    return JSONResponse(result,
                        status_code=200 if result["status"] != "error" else 400)


@app.get("/api/youbike/route")
def youbike_route(from_station: str, to_station: str,
                  origin: str | None = None) -> JSONResponse:
    """使用者在畫面上選好借還車站後，算整趟「走＋騎＋走」的時間。"""
    settings = load_settings()
    start = (origin or "").strip() or settings.default_origin
    if not start:
        return JSONResponse({"error": "沒有出發地"}, status_code=400)

    path = user_schedule_path()
    if not path.is_file():
        return JSONResponse({"error": "還沒有課表，無法得知目的地"}, status_code=400)

    moment, _, _ = resolve_now(None, settings.timezone)
    _, upcoming = find_classes(load_courses(path), moment)
    if upcoming is None:
        return JSONResponse({"error": "課表裡找不到接下來的課"}, status_code=400)

    target = _resolve_building(upcoming)
    plan = plan_bike_journey(start, target["building_name"] or target["location"],
                             from_station, to_station)
    return JSONResponse(plan, status_code=200 if plan["status"] == "ok" else 400)


@app.post("/api/schedule/import")
async def import_schedule(file: UploadFile = File(...)) -> JSONResponse:
    """收課表截圖，交給 Gemini 辨識，存成使用者課表。"""
    raw = await file.read()
    try:
        schedule = extract_schedule_from_image(
            raw, (file.content_type or "").lower(), source=file.filename or "上傳的圖片")
    except OCRError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    if not schedule["courses"]:
        return JSONResponse(
            {"error": "這張圖片裡沒有辨識出任何課程，請確認是課表截圖、字有沒有被裁掉。",
             "skipped": schedule["skipped"]}, status_code=400)

    path = _save_schedule(schedule)
    return JSONResponse({"imported": len(schedule["courses"]),
                         "skipped": schedule["skipped"],
                         "source": schedule["source"],
                         "saved_to": str(path)})


@app.post("/api/schedule/sample")
def use_sample_schedule() -> JSONResponse:
    """把版控裡的範例課表複製成使用者課表。

    現場辨識萬一失敗（沒網路、被限流、照片太糊）時的備援，讓 demo 還能繼續。
    """
    sample = sample_schedule_path()
    if not sample.is_file():
        return JSONResponse({"error": f"找不到範例課表：{sample}"}, status_code=404)

    schedule = json.loads(sample.read_text(encoding="utf-8"))
    schedule["source"] = f"範例課表（{sample.name}）"
    schedule.setdefault("skipped", [])
    _save_schedule(schedule)
    return JSONResponse({"imported": len(schedule.get("courses", [])),
                         "source": schedule["source"]})


@app.delete("/api/schedule")
def clear_schedule() -> JSONResponse:
    """清掉使用者課表，回到空白狀態。demo 要重跑一次時用得上。"""
    path = user_schedule_path()
    existed = path.is_file()
    if existed:
        path.unlink()
    return JSONResponse({"cleared": existed})


@app.get("/")
def index() -> FileResponse:
    # 開發中頁面常改，被瀏覽器快取會讓人以為修正沒生效
    return FileResponse(WEB_DIR / "index.html",
                        headers={"Cache-Control": "no-store"})


@app.get("/favicon.svg")
def favicon() -> FileResponse:
    # 圖示不太會變，可以放心讓瀏覽器快取久一點
    return FileResponse(WEB_DIR / "favicon.svg", media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
