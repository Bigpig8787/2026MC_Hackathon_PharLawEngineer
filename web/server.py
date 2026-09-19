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

from api import load_settings
from commute_agent.tools.class_schedule import PROJECT_ROOT, find_classes, load_courses
from commute_agent.tools.ncku_room import lookup_room
from commute_agent.tools.schedule_ocr import OCRError, extract_schedule_from_image
from commute_agent.skills.parking_plan import plan_parking
from commute_agent.skills.road_watch import check_route_events
from commute_agent.skills.trip_plan import estimate_trip
from commute_agent.tools.route_link import TRAVEL_MODE_LABELS, build_route_link

WEB_DIR = Path(__file__).resolve().parent

app = FastAPI(title="NCKU Smart Commute")


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
    if entry is None:
        return None
    enriched = _resolve_building(entry)
    destination = enriched["building_name"] or enriched["location"]
    enriched["route_link"] = build_route_link(destination, origin=origin or None,
                                              travel_mode=travel_mode)
    enriched["origin"] = origin
    enriched["travel_mode"] = travel_mode
    return enriched


def _parking_for(entry: dict | None, vehicle_type: str) -> dict | None:
    """騎車或開車時才需要停車建議；目的地查不到大樓就不猜。"""
    if entry is None or not entry.get("building_name"):
        return None
    plan = plan_parking(entry["building_name"], vehicle_type)
    if plan.get("recommended"):
        plan["recommended"]["route_link"] = build_route_link(
            plan["recommended"]["name"], travel_mode="driving")
    return plan


def _save_schedule(schedule: dict) -> Path:
    path = user_schedule_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schedule, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


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
                             "trip": None, "road_events": None, "parking": None, "courses": []})

    try:
        courses = load_courses(path)
        source = json.loads(path.read_text(encoding="utf-8")).get("source", "")
    except (ValueError, OSError) as exc:
        return JSONResponse({**base, "has_schedule": False, "courses": [],
                             "current_class": None, "next_class": None,
                             "trip": None, "road_events": None, "parking": None, "schedule_source": "",
                             "error": f"課表檔案讀取失敗：{exc}"}, status_code=200)

    current, upcoming = find_classes(courses, moment)
    next_class = _with_route(upcoming, start, mode)

    trip = None
    road_events = None
    if next_class:
        destination = next_class["building_name"] or next_class["location"]
        trip = estimate_trip(start, destination, mode) if start else None
        # 起點與目的地都查得到座標才有意義；查不到座標的那端 check_route_events
        # 自己會標成 resolved=False，這裡只是省掉明知道會兩端都落空的呼叫
        road_events = check_route_events(start, destination) if start else None

    return JSONResponse({
        **base,
        "has_schedule": True,
        "schedule_source": source,
        "current_class": _with_route(current, start, mode),
        "next_class": next_class,
        "trip": trip,
        "road_events": road_events,
        # 只有騎車開車才需要停車位，步行與大眾運輸不查，省掉七次連線
        "parking": _parking_for(next_class, vehicle) if mode == "driving" else None,
        "courses": courses,
    })


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
    return FileResponse(WEB_DIR / "index.html")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
