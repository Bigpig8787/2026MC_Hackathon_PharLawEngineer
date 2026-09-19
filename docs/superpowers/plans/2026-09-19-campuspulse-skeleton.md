# CampusPulse 骨架與導航主線 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `apps/api`（FastAPI）+ `apps/web`（React/Vite）骨架，讓「承諾 → 四模式規劃 → 劇本推進 → 自動改計畫 → 確認閘門 → 教室卡」全程用 fixture 跑通，其餘 provider 留空殼。

**Architecture:** 後端 planner/trigger 為純函式，loop 負責 perceive→plan→act→reflect 與時間軸；provider 走 Protocol 介面，registry 依 key 選 live 或 fixture；前端單頁讀 `/api/state` 渲染卡片、地圖、時間軸。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、httpx、pytest、google-genai；React 19、Vite、TypeScript、Tailwind v4、react-leaflet 5。

**Spec:** `docs/superpowers/specs/2026-09-19-campuspulse-skeleton-design.md`

## Global Constraints

- Python ≥ 3.12；Node ≥ 20；所有後端指令在 `apps/api` 執行，前端在 `apps/web`。
- 秘密只在 `apps/api/.env`；任何回應、log、測試輸出不得含 key 值。
- `PROVIDER_MODE=fixture` 時零網路；測試全部無網路。
- 每個 Signal / RouteResult 必帶 `source_mode`（`live|fixture|stale|unavailable`）。
- 外部寫入（email/calendar）預設 dry-run，需 `POST /api/actions/{id}/confirm`。
- planner `policy_version = "0.1"`；規則數字照 spec：緩衝 normal 5 / high 10 / critical 15 分；固定成本 walk 0 / bike 2 / scooter 3 / transit 2；可靠度基準 walk 0.9 / bike 0.6 / scooter 0.7 / transit 0.8。
- Commit 訊息用 `feat:` / `test:` / `docs:` / `chore:`；在 `feature/skeleton` 分支工作，不直接推 `main`。
- 時間一律 timezone-aware（`+08:00`）。

## 檔案結構總覽

```
apps/api/
  requirements.txt  pytest.ini  .env.example
  campuspulse/
    __init__.py  settings.py  main.py
    core/   __init__.py  models.py  campus.py  planner.py  triggers.py  actions.py  loop.py
    providers/  __init__.py  base.py  fixture_store.py  signals_fixture.py  registry.py
      routing/  __init__.py  fixture.py  polyline.py  google_routes.py
      weather/  __init__.py  fixture.py  cwa.py
      flood/    __init__.py  fixture.py  wra.py
      bike/     __init__.py  fixture.py  tdx_youbike.py
      transit/  __init__.py  fixture.py  tdx_bus.py
      parking/  __init__.py  fixture.py
      indoor/   __init__.py  fixture.py  floorplan_gemini.py
      email/    __init__.py  fixture.py  gmail.py
      calendar/ __init__.py  fixture.py  google_calendar.py
    ai/   __init__.py  gemini.py  rationale.py  timetable.py
    scenario/  __init__.py  runner.py
    api/  __init__.py  routes_state.py  routes_scenario.py  routes_actions.py  routes_plan.py
  data/ncku/  buildings.json  parking_lots.json  rooms.json  bike_stations.json  bus_stops.json  corridors.json
  fixtures/scenarios/ncku-wed-0900.json
  fixtures/routes/  walk.json  bike.json  scooter.json  transit.json
  tests/  test_health.py  test_models.py  test_campus.py  test_providers_fixture.py  test_planner.py  test_triggers.py  test_scenario.py  test_api.py  test_google_routes.py  test_ai.py  test_registry.py
apps/web/
  vite.config.ts  index.html  package.json
  src/  main.tsx  App.tsx  index.css  types.ts  api/client.ts
  src/components/  ScenarioBar.tsx  CommitmentCard.tsx  PlanCard.tsx  MapView.tsx  DecisionCounter.tsx  Timeline.tsx  ActionModal.tsx  IndoorCard.tsx
docs/  team-ownership.md  api-and-data.md
```

---

### Task 1: API 骨架、settings、health

**Files:**
- Create: `apps/api/requirements.txt`, `apps/api/pytest.ini`, `apps/api/.env.example`, `apps/api/campuspulse/__init__.py`, `apps/api/campuspulse/settings.py`, `apps/api/campuspulse/main.py`
- Test: `apps/api/tests/test_health.py`

**Interfaces:**
- Produces: `settings.load_settings() -> Settings`（欄位：`provider_mode, dry_run, timezone, gemini_api_key, gemini_flash_model, gemini_pro_model, google_maps_api_key, tdx_client_id, tdx_client_secret, cwa_api_key, wra_api_key`）、`settings.API_ROOT: Path`、`settings.missing_live_credentials(Settings) -> list[str]`、`main.create_app(settings=None) -> FastAPI`。

- [ ] **Step 1: 建分支與虛擬環境**

```powershell
git switch -c feature/skeleton
New-Item -ItemType Directory -Force apps/api/campuspulse, apps/api/tests
Set-Location apps/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

- [ ] **Step 2: 寫依賴與 pytest 設定**

`apps/api/requirements.txt`
```
fastapi>=0.115
uvicorn[standard]>=0.30
pydantic>=2.7
httpx>=0.27
python-dotenv>=1.0
google-genai>=1.0
pytest>=8
```

`apps/api/pytest.ini`
```ini
[pytest]
pythonpath = .
testpaths = tests
```

`apps/api/.env.example`
```
PROVIDER_MODE=fixture
DRY_RUN=true
TIMEZONE=Asia/Taipei
GEMINI_API_KEY=
GEMINI_FLASH_MODEL=gemini-3-flash-preview
GEMINI_PRO_MODEL=gemini-3-pro-preview
GOOGLE_MAPS_API_KEY=
TDX_CLIENT_ID=
TDX_CLIENT_SECRET=
CWA_API_KEY=
WRA_API_KEY=
```

Run: `pip install -r requirements.txt`

- [ ] **Step 3: 寫失敗測試**

`apps/api/tests/test_health.py`
```python
from fastapi.testclient import TestClient

from campuspulse.main import create_app


def test_health_reports_mode_without_secret_values(monkeypatch):
    monkeypatch.setenv("PROVIDER_MODE", "fixture")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "should-not-leak")
    monkeypatch.delenv("CWA_API_KEY", raising=False)
    client = TestClient(create_app())
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["provider_mode"] == "fixture"
    assert "GOOGLE_MAPS_API_KEY" not in body["missing_credentials"]
    assert "CWA_API_KEY" in body["missing_credentials"]
    assert "should-not-leak" not in str(body)
```

- [ ] **Step 4: 跑測試確認失敗**

Run: `pytest tests/test_health.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'campuspulse'`

- [ ] **Step 5: 實作 settings 與 main**

`apps/api/campuspulse/__init__.py`：空檔。

`apps/api/campuspulse/settings.py`
```python
"""Environment-backed settings. Never put secret values in code or logs."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

API_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(API_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool_env(name: str, default: bool) -> bool:
    return _env(name, str(default)).lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Settings:
    provider_mode: str = "fixture"
    dry_run: bool = True
    timezone: str = "Asia/Taipei"
    gemini_api_key: str = ""
    gemini_flash_model: str = "gemini-3-flash-preview"
    gemini_pro_model: str = "gemini-3-pro-preview"
    google_maps_api_key: str = ""
    tdx_client_id: str = ""
    tdx_client_secret: str = ""
    cwa_api_key: str = ""
    wra_api_key: str = ""


def load_settings() -> Settings:
    return Settings(
        provider_mode=_env("PROVIDER_MODE", "fixture") or "fixture",
        dry_run=_bool_env("DRY_RUN", True),
        timezone=_env("TIMEZONE", "Asia/Taipei") or "Asia/Taipei",
        gemini_api_key=_env("GEMINI_API_KEY"),
        gemini_flash_model=_env("GEMINI_FLASH_MODEL", "gemini-3-flash-preview"),
        gemini_pro_model=_env("GEMINI_PRO_MODEL", "gemini-3-pro-preview"),
        google_maps_api_key=_env("GOOGLE_MAPS_API_KEY"),
        tdx_client_id=_env("TDX_CLIENT_ID"),
        tdx_client_secret=_env("TDX_CLIENT_SECRET"),
        cwa_api_key=_env("CWA_API_KEY"),
        wra_api_key=_env("WRA_API_KEY"),
    )


def missing_live_credentials(settings: Settings) -> list[str]:
    """Names only. Never return values."""
    required = {
        "GEMINI_API_KEY": settings.gemini_api_key,
        "GOOGLE_MAPS_API_KEY": settings.google_maps_api_key,
        "TDX_CLIENT_ID": settings.tdx_client_id,
        "TDX_CLIENT_SECRET": settings.tdx_client_secret,
        "CWA_API_KEY": settings.cwa_api_key,
        "WRA_API_KEY": settings.wra_api_key,
    }
    return [name for name, value in required.items() if not value]
```

`apps/api/campuspulse/main.py`（Task 8 會擴充）
```python
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from campuspulse.settings import Settings, load_settings, missing_live_credentials


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="CampusPulse API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "provider_mode": settings.provider_mode,
            "dry_run": settings.dry_run,
            "missing_credentials": missing_live_credentials(settings),
        }

    return app


app = create_app()
```

- [ ] **Step 6: 跑測試確認通過**

Run: `pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 7: 手動啟動一次**

Run: `uvicorn campuspulse.main:app --reload --port 8000`，開 http://localhost:8000/api/health，看到 JSON 後 Ctrl+C。

- [ ] **Step 8: Commit**

```powershell
git add apps/api
git commit -m "feat(api): scaffold FastAPI app with settings and health endpoint"
```

---

### Task 2: 核心型別

**Files:**
- Create: `apps/api/campuspulse/core/__init__.py`, `apps/api/campuspulse/core/models.py`
- Test: `apps/api/tests/test_models.py`

**Interfaces:**
- Produces（全部 Pydantic v2）：`Mode`, `SourceMode`, `Importance`, `PlanStatus`, `LatLng`, `Commitment`, `Signal`, `RouteResult`, `LastDecision`, `TravelOption`, `Plan`, `Trigger`, `ProposedAction`, `TimelineEvent`, `IndoorGuidance`。欄位見下方程式碼；後續所有 task 以此為準。

- [ ] **Step 1: 寫失敗測試**

`apps/api/tests/test_models.py`
```python
from datetime import datetime, timezone, timedelta

from campuspulse.core.models import (
    Commitment, Importance, LatLng, Mode, Plan, PlanStatus, RouteResult, SourceMode, TravelOption,
)

TPE = timezone(timedelta(hours=8))


def test_plan_round_trips_through_json():
    route = RouteResult(mode=Mode.scooter, duration_min=12, distance_m=3200, polyline=[LatLng(lat=22.99, lng=120.22)])
    opt = TravelOption(mode=Mode.scooter, route=route, feasible=True, on_time=True)
    plan = Plan(
        commitment_id="c1",
        generated_at=datetime(2026, 9, 23, 7, 50, tzinfo=TPE),
        selected=opt,
        options=[opt],
    )
    dumped = plan.model_dump_json()
    loaded = Plan.model_validate_json(dumped)
    assert loaded.selected.route.source_mode == SourceMode.fixture
    assert loaded.status == PlanStatus.ok
    assert loaded.policy_version == "0.1"


def test_commitment_defaults():
    c = Commitment(id="c1", title="小組報告", start=datetime(2026, 9, 23, 9, 0, tzinfo=TPE), building_id="csie", room="4263")
    assert c.importance == Importance.normal
    assert c.confirmed is True
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_models.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'campuspulse.core'`

- [ ] **Step 3: 實作 models**

`apps/api/campuspulse/core/__init__.py`：空檔。

`apps/api/campuspulse/core/models.py`
```python
"""Typed domain models shared by planner, loop, providers and API."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Mode(str, Enum):
    walk = "walk"
    scooter = "scooter"
    bike = "bike"
    transit = "transit"


class SourceMode(str, Enum):
    live = "live"
    fixture = "fixture"
    stale = "stale"
    unavailable = "unavailable"


class Importance(str, Enum):
    normal = "normal"
    high = "high"
    critical = "critical"


class PlanStatus(str, Enum):
    ok = "ok"
    late_risk = "late_risk"
    no_feasible = "no_feasible"
    arrived = "arrived"


class LatLng(BaseModel):
    lat: float
    lng: float


class Commitment(BaseModel):
    id: str
    title: str
    start: datetime
    building_id: str
    room: str
    importance: Importance = Importance.normal
    source: str = "fixture"
    confirmed: bool = True


SignalKind = Literal["rain", "flood", "bike", "transit", "parking"]


class Signal(BaseModel):
    kind: SignalKind
    observed_at: datetime
    valid_until: Optional[datetime] = None
    value: dict[str, Any] = Field(default_factory=dict)
    source_mode: SourceMode = SourceMode.fixture
    confidence: float = 1.0


class RouteResult(BaseModel):
    mode: Mode
    duration_min: float
    distance_m: float
    polyline: list[LatLng] = Field(default_factory=list)
    summary: str = ""
    corridor_ids: list[str] = Field(default_factory=list)
    source_mode: SourceMode = SourceMode.fixture
    mode_proxy: Optional[str] = None
    alternative: Optional["RouteResult"] = None


class LastDecision(BaseModel):
    kind: Literal["parking_lot", "bike_dock", "bus_stop", "gate"]
    target_id: str
    label: str
    walk_min: float
    reason: str
    location: Optional[LatLng] = None


class TravelOption(BaseModel):
    mode: Mode
    route: Optional[RouteResult] = None
    last_decision: Optional[LastDecision] = None
    base_eta_min: float = 0.0
    conservative_eta_min: float = 0.0
    depart_at: Optional[datetime] = None
    arrive_at: Optional[datetime] = None
    feasible: bool = False
    on_time: bool = False
    slack_min: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    reliability: float = 0.0
    score: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    commitment_id: str
    generated_at: datetime
    selected: Optional[TravelOption] = None
    options: list[TravelOption] = Field(default_factory=list)
    rationale: str = ""
    next_check_at: Optional[datetime] = None
    status: PlanStatus = PlanStatus.ok
    policy_version: str = "0.1"
    decisions_made: int = 0


class Trigger(BaseModel):
    kind: str
    description: str
    old: Any = None
    new: Any = None
    observed_at: datetime
    material: bool = True


class ProposedAction(BaseModel):
    id: str
    type: Literal["email", "calendar"]
    preview: dict[str, Any]
    state: Literal["proposed", "confirmed", "rejected", "executed_dry_run"] = "proposed"
    created_at: datetime
    updated_at: Optional[datetime] = None


class TimelineEvent(BaseModel):
    at: datetime
    phase: Literal["perceive", "plan", "act", "reflect"]
    title: str
    detail: str = ""
    source_modes: list[str] = Field(default_factory=list)


class IndoorGuidance(BaseModel):
    building_id: str
    room: str
    floor: str
    wing: str
    entrance: str
    instructions: str
    source_mode: SourceMode = SourceMode.fixture
    confidence: float = 1.0
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add apps/api/campuspulse/core apps/api/tests/test_models.py
git commit -m "feat(core): add domain models"
```

---

### Task 3: 校園資料與 Campus loader

**Files:**
- Create: `apps/api/data/ncku/buildings.json`, `parking_lots.json`, `rooms.json`, `bike_stations.json`, `bus_stops.json`, `corridors.json`, `apps/api/campuspulse/core/campus.py`
- Test: `apps/api/tests/test_campus.py`

**Interfaces:**
- Produces: `Campus.load(data_dir=DATA_DIR) -> Campus`；`campus.building(id) -> Building`；`campus.room(room) -> Room | None`；`campus.entrance(building_id, entrance_id) -> Entrance`；`campus.nearest_entrance(building_id, point) -> Entrance`；`campus.walk_to_building(point, building_id) -> tuple[Entrance, float]`；`campus.lots -> list[ParkingLot]`；`campus.lot(id)`；`campus.bike_station(id) -> Station`；`campus.bus_stop(id) -> Station`；`campus.corridor_ids_in_text(text) -> list[str]`；`walk_minutes(a: LatLng, b: LatLng) -> float`。
- 所有座標為近似值，`"verified": false`；D 從成大官網校正時只改值不改欄位。

- [ ] **Step 1: 寫資料檔**

`apps/api/data/ncku/buildings.json`
```json
{
  "buildings": [
    {
      "id": "csie",
      "name": "資訊系館",
      "campus": "成功校區",
      "location": { "lat": 22.9997, "lng": 120.2220 },
      "verified": false,
      "entrances": [
        { "id": "csie-east", "name": "東側門", "location": { "lat": 22.9996, "lng": 120.2226 } },
        { "id": "csie-west", "name": "西側門", "location": { "lat": 22.9996, "lng": 120.2214 } }
      ]
    }
  ]
}
```

`apps/api/data/ncku/parking_lots.json`
```json
{
  "lots": [
    { "id": "lot-a", "name": "小東路側機車停車場", "location": { "lat": 23.0001, "lng": 120.2227 }, "covered": false, "capacity": 120, "verified": false },
    { "id": "lot-b", "name": "成功校區地下機車停車場", "location": { "lat": 22.9988, "lng": 120.2234 }, "covered": true, "capacity": 400, "verified": false },
    { "id": "lot-c", "name": "光復校區機車停車場", "location": { "lat": 22.9975, "lng": 120.2190 }, "covered": false, "capacity": 300, "verified": false }
  ]
}
```

`apps/api/data/ncku/rooms.json`
```json
{
  "rooms": [
    {
      "room": "4263",
      "building_id": "csie",
      "floor": "4F",
      "wing": "東側",
      "entrance_id": "csie-east",
      "instructions": "從東側門進，右手邊樓梯上 4 樓，出樓梯往東走到底。",
      "verified": false
    }
  ]
}
```

`apps/api/data/ncku/bike_stations.json`
```json
{
  "stations": [
    { "id": "yb-dongning", "name": "東寧路口", "location": { "lat": 22.9908, "lng": 120.2276 }, "verified": false },
    { "id": "yb-ncku-north", "name": "成大北門", "location": { "lat": 23.0003, "lng": 120.2218 }, "verified": false },
    { "id": "yb-ncku-east", "name": "成大東門", "location": { "lat": 22.9990, "lng": 120.2240 }, "verified": false }
  ]
}
```

`apps/api/data/ncku/bus_stops.json`
```json
{
  "stops": [
    { "id": "bs-dongning", "name": "東寧路口站", "location": { "lat": 22.9910, "lng": 120.2274 }, "verified": false },
    { "id": "bs-ncku-north", "name": "成大北門站", "location": { "lat": 23.0012, "lng": 120.2222 }, "verified": false },
    { "id": "bs-ncku-east", "name": "成大東門站", "location": { "lat": 22.9988, "lng": 120.2244 }, "verified": false }
  ]
}
```

`apps/api/data/ncku/corridors.json`
```json
{
  "corridors": [
    { "id": "xiaodong-rd", "name": "小東路", "aliases": ["小東路", "Xiaodong Rd", "Xiaodong Road"] },
    { "id": "changrong-rd", "name": "長榮路", "aliases": ["長榮路", "Changrong Rd", "Changrong Road"] },
    { "id": "dongning-rd", "name": "東寧路", "aliases": ["東寧路", "Dongning Rd", "Dongning Road"] }
  ]
}
```

- [ ] **Step 2: 寫失敗測試**

`apps/api/tests/test_campus.py`
```python
from campuspulse.core.campus import Campus, walk_minutes
from campuspulse.core.models import LatLng


def test_campus_loads_and_resolves_room():
    campus = Campus.load()
    room = campus.room("4263")
    assert room is not None and room.building_id == "csie"
    entrance = campus.entrance("csie", room.entrance_id)
    assert entrance.name == "東側門"


def test_walk_to_building_uses_nearest_entrance():
    campus = Campus.load()
    lot_b = campus.lot("lot-b")
    entrance, minutes = campus.walk_to_building(lot_b.location, "csie")
    assert entrance.id == "csie-east"
    assert 0 < minutes < 10


def test_walk_minutes_is_distance_over_80m_per_min():
    a = LatLng(lat=23.0, lng=120.22)
    b = LatLng(lat=23.0, lng=120.2208)  # ~82 m east
    assert 0.9 < walk_minutes(a, b) < 1.2


def test_corridor_ids_in_text_matches_aliases():
    campus = Campus.load()
    assert campus.corridor_ids_in_text("Turn left onto 小東路 then Changrong Rd") == ["xiaodong-rd", "changrong-rd"]
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `pytest tests/test_campus.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'campuspulse.core.campus'`

- [ ] **Step 4: 實作 campus.py**

`apps/api/campuspulse/core/campus.py`
```python
"""NCKU campus reference data: buildings, entrances, parking, stations, corridors."""
from __future__ import annotations

import json
import math
from pathlib import Path

from pydantic import BaseModel, Field

from campuspulse.core.models import LatLng
from campuspulse.settings import API_ROOT

DATA_DIR = API_ROOT / "data" / "ncku"
WALK_M_PER_MIN = 80.0


class Entrance(BaseModel):
    id: str
    name: str
    location: LatLng


class Building(BaseModel):
    id: str
    name: str
    campus: str
    location: LatLng
    entrances: list[Entrance] = Field(default_factory=list)
    verified: bool = False


class ParkingLot(BaseModel):
    id: str
    name: str
    location: LatLng
    covered: bool
    capacity: int
    verified: bool = False


class Room(BaseModel):
    room: str
    building_id: str
    floor: str
    wing: str
    entrance_id: str
    instructions: str
    verified: bool = False


class Station(BaseModel):
    id: str
    name: str
    location: LatLng
    verified: bool = False


class Corridor(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)


def haversine_m(a: LatLng, b: LatLng) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp = p2 - p1
    dl = math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def walk_minutes(a: LatLng, b: LatLng) -> float:
    return round(haversine_m(a, b) / WALK_M_PER_MIN, 1)


def _read(path: Path, key: str) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)[key]


class Campus:
    def __init__(
        self,
        buildings: list[Building],
        lots: list[ParkingLot],
        rooms: list[Room],
        bike_stations: list[Station],
        bus_stops: list[Station],
        corridors: list[Corridor],
    ) -> None:
        self._buildings = {b.id: b for b in buildings}
        self.lots = lots
        self._lots = {lot.id: lot for lot in lots}
        self._rooms = {r.room: r for r in rooms}
        self._bike = {s.id: s for s in bike_stations}
        self._bus = {s.id: s for s in bus_stops}
        self.corridors = corridors

    @classmethod
    def load(cls, data_dir: Path = DATA_DIR) -> "Campus":
        return cls(
            buildings=[Building(**b) for b in _read(data_dir / "buildings.json", "buildings")],
            lots=[ParkingLot(**p) for p in _read(data_dir / "parking_lots.json", "lots")],
            rooms=[Room(**r) for r in _read(data_dir / "rooms.json", "rooms")],
            bike_stations=[Station(**s) for s in _read(data_dir / "bike_stations.json", "stations")],
            bus_stops=[Station(**s) for s in _read(data_dir / "bus_stops.json", "stops")],
            corridors=[Corridor(**c) for c in _read(data_dir / "corridors.json", "corridors")],
        )

    @property
    def buildings(self) -> list[Building]:
        return list(self._buildings.values())

    def building(self, building_id: str) -> Building:
        return self._buildings[building_id]

    def room(self, room: str) -> Room | None:
        return self._rooms.get(room)

    def entrance(self, building_id: str, entrance_id: str) -> Entrance:
        for e in self.building(building_id).entrances:
            if e.id == entrance_id:
                return e
        raise KeyError(entrance_id)

    def nearest_entrance(self, building_id: str, point: LatLng) -> Entrance:
        b = self.building(building_id)
        if not b.entrances:
            return Entrance(id=f"{b.id}-main", name="正門", location=b.location)
        return min(b.entrances, key=lambda e: haversine_m(point, e.location))

    def walk_to_building(self, point: LatLng, building_id: str) -> tuple[Entrance, float]:
        e = self.nearest_entrance(building_id, point)
        return e, walk_minutes(point, e.location)

    def lot(self, lot_id: str) -> ParkingLot:
        return self._lots[lot_id]

    def bike_station(self, station_id: str) -> Station:
        return self._bike[station_id]

    def bus_stop(self, stop_id: str) -> Station:
        return self._bus[stop_id]

    def corridor_ids_in_text(self, text: str) -> list[str]:
        found: list[tuple[int, str]] = []
        for c in self.corridors:
            positions = [text.find(a) for a in c.aliases if a in text]
            if positions:
                found.append((min(positions), c.id))
        return [cid for _, cid in sorted(found)]
```

- [ ] **Step 5: 跑測試確認通過**

Run: `pytest tests/test_campus.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```powershell
git add apps/api/data apps/api/campuspulse/core/campus.py apps/api/tests/test_campus.py
git commit -m "feat(core): add NCKU campus data and loader"
```

---

### Task 4: Provider 介面、FixtureStore、fixture providers、registry

**Files:**
- Create: `apps/api/campuspulse/providers/__init__.py`, `base.py`, `fixture_store.py`, `signals_fixture.py`, `registry.py`；`providers/routing/__init__.py`, `routing/fixture.py`；`providers/{weather,flood,bike,transit,parking,indoor,email,calendar}/__init__.py` 與各自 `fixture.py`；`apps/api/fixtures/routes/{walk,bike,scooter,transit}.json`
- Test: `apps/api/tests/test_providers_fixture.py`

**Interfaces:**
- Consumes: Task 2 models、Task 3 `Campus`。
- Produces:
  - `ProviderError(code: str, message: str = "")`，`.code`。
  - `RoutingProvider.route(origin: LatLng, destination: LatLng, mode: Mode, depart_at: datetime) -> RouteResult`；屬性 `name: str`, `source_mode: SourceMode`。
  - `SignalProvider.fetch(at: datetime, context: dict) -> Signal`；屬性 `kind: str`, `source_mode`。
  - `IndoorProvider.locate(building_id: str, room: str) -> IndoorGuidance`。
  - `EmailProvider.preview(to: list[str], subject: str, body: str) -> dict`、`.send(preview: dict) -> dict`。
  - `CalendarProvider.preview_change(change: dict) -> dict`、`.execute_change(preview: dict) -> dict`。
  - `FixtureStore.set_all(values: dict[str, dict], observed_at: datetime)`、`.update(kind: str, patch: dict)`、`.get(kind) -> dict | None`、`.observed_at`。
  - `Providers` dataclass：`routing, signals: dict[str, SignalProvider], indoor, email, calendar`；`build_providers(settings, store, campus) -> Providers`；`LIVE_SIGNAL_CLASSES: dict[str, type]`（Task 11 填）。
- Signal `value` 格式（planner 依此讀）：
  - `rain`: `{"mm_per_hour": float, "forecast_next_hour_mm": float}`
  - `flood`: `{"alerts": [{"corridor_id": str, "level": "watch"|"warning"|"danger"}]}`
  - `bike`: `{"origin_station_id", "available": int, "dest_station_id", "docks": int, "next_station_id", "next_station_docks": int}`
  - `transit`: `{"route_name": str, "next_eta_min": float|null, "board_stop_id", "alight_stop_id"}`
  - `parking`: `{"lots": {lot_id: {"free": int}}}`

- [ ] **Step 1: 寫路線 fixture**

`apps/api/fixtures/routes/scooter.json`
```json
{
  "mode": "scooter", "duration_min": 12, "distance_m": 3200, "summary": "經小東路", "corridor_ids": ["xiaodong-rd"], "mode_proxy": "DRIVE",
  "polyline": [[22.9905, 120.2280], [22.9930, 120.2265], [22.9960, 120.2250], [22.9985, 120.2235], [22.9997, 120.2220]],
  "alternative": {
    "mode": "scooter", "duration_min": 15, "distance_m": 3900, "summary": "經長榮路（避開小東路）", "corridor_ids": ["changrong-rd"], "mode_proxy": "DRIVE",
    "polyline": [[22.9905, 120.2280], [22.9920, 120.2300], [22.9960, 120.2290], [22.9990, 120.2250], [22.9997, 120.2220]]
  }
}
```

`apps/api/fixtures/routes/bike.json`
```json
{
  "mode": "bike", "duration_min": 16, "distance_m": 3000, "summary": "經小東路自行車道", "corridor_ids": ["xiaodong-rd"],
  "polyline": [[22.9905, 120.2280], [22.9930, 120.2265], [22.9960, 120.2250], [22.9985, 120.2235], [23.0003, 120.2218]],
  "alternative": {
    "mode": "bike", "duration_min": 19, "distance_m": 3600, "summary": "經長榮路", "corridor_ids": ["changrong-rd"],
    "polyline": [[22.9905, 120.2280], [22.9920, 120.2300], [22.9960, 120.2290], [22.9990, 120.2250], [23.0003, 120.2218]]
  }
}
```

`apps/api/fixtures/routes/walk.json`
```json
{
  "mode": "walk", "duration_min": 38, "distance_m": 3000, "summary": "經小東路人行道", "corridor_ids": ["xiaodong-rd"],
  "polyline": [[22.9905, 120.2280], [22.9930, 120.2265], [22.9960, 120.2250], [22.9985, 120.2235], [22.9996, 120.2226]],
  "alternative": {
    "mode": "walk", "duration_min": 42, "distance_m": 3400, "summary": "經長榮路", "corridor_ids": ["changrong-rd"],
    "polyline": [[22.9905, 120.2280], [22.9920, 120.2300], [22.9960, 120.2290], [22.9990, 120.2250], [22.9996, 120.2226]]
  }
}
```

`apps/api/fixtures/routes/transit.json`
```json
{
  "mode": "transit", "duration_min": 22, "distance_m": 3800, "summary": "5 號公車 東寧路口站 → 成大北門站", "corridor_ids": [],
  "polyline": [[22.9905, 120.2280], [22.9910, 120.2274], [22.9950, 120.2262], [22.9990, 120.2240], [23.0006, 120.2222]]
}
```

- [ ] **Step 2: 寫失敗測試**

`apps/api/tests/test_providers_fixture.py`
```python
from datetime import datetime, timedelta, timezone

from campuspulse.core.campus import Campus
from campuspulse.core.models import LatLng, Mode, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.providers.fixture_store import FixtureStore
from campuspulse.providers.registry import build_providers
from campuspulse.settings import Settings

TPE = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 7, 50, tzinfo=TPE)


def _providers():
    store = FixtureStore()
    return build_providers(Settings(provider_mode="fixture"), store, Campus.load()), store


def test_fixture_routing_returns_all_four_modes_with_alternatives():
    providers, _ = _providers()
    origin, dest = LatLng(lat=22.9905, lng=120.2280), LatLng(lat=22.9997, lng=120.2220)
    for mode in Mode:
        r = providers.routing.route(origin, dest, mode, NOW)
        assert r.mode == mode and r.source_mode == SourceMode.fixture and r.polyline
    assert providers.routing.route(origin, dest, Mode.scooter, NOW).alternative.corridor_ids == ["changrong-rd"]


def test_fixture_signal_reads_store_and_marks_fixture():
    providers, store = _providers()
    store.set_all({"rain": {"mm_per_hour": 25, "forecast_next_hour_mm": 30}}, NOW)
    sig = providers.signals["rain"].fetch(NOW, {})
    assert sig.value["mm_per_hour"] == 25 and sig.source_mode == SourceMode.fixture and sig.observed_at == NOW


def test_fixture_signal_missing_raises_unavailable():
    providers, _ = _providers()
    try:
        providers.signals["flood"].fetch(NOW, {})
    except ProviderError as e:
        assert e.code == "unavailable"
    else:
        raise AssertionError("expected ProviderError")


def test_fixture_indoor_and_email_are_dry_run():
    providers, _ = _providers()
    g = providers.indoor.locate("csie", "4263")
    assert g.floor == "4F" and g.source_mode == SourceMode.fixture
    preview = providers.email.preview(["ta@example.com"], "遲到通知", "內文")
    assert providers.email.send(preview)["status"] == "dry_run"
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `pytest tests/test_providers_fixture.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'campuspulse.providers'`

- [ ] **Step 4: 實作 base、store、fixture providers**

所有 `__init__.py` 空檔：`providers/`, `routing/`, `weather/`, `flood/`, `bike/`, `transit/`, `parking/`, `indoor/`, `email/`, `calendar/`。

`apps/api/campuspulse/providers/base.py`
```python
"""Provider contracts. Live and fixture implementations return the same normalized models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from campuspulse.core.models import IndoorGuidance, LatLng, Mode, RouteResult, Signal, SourceMode


class ProviderError(Exception):
    """codes: unavailable | unauthorized | rate_limited | invalid_response | stale | not_implemented"""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


class RoutingProvider(Protocol):
    name: str
    source_mode: SourceMode

    def route(self, origin: LatLng, destination: LatLng, mode: Mode, depart_at: datetime) -> RouteResult: ...


class SignalProvider(Protocol):
    kind: str
    source_mode: SourceMode

    def fetch(self, at: datetime, context: dict[str, Any]) -> Signal: ...


class IndoorProvider(Protocol):
    source_mode: SourceMode

    def locate(self, building_id: str, room: str) -> IndoorGuidance: ...


class EmailProvider(Protocol):
    def preview(self, to: list[str], subject: str, body: str) -> dict[str, Any]: ...

    def send(self, preview: dict[str, Any]) -> dict[str, Any]: ...


class CalendarProvider(Protocol):
    def preview_change(self, change: dict[str, Any]) -> dict[str, Any]: ...

    def execute_change(self, preview: dict[str, Any]) -> dict[str, Any]: ...
```

`apps/api/campuspulse/providers/fixture_store.py`
```python
"""Scenario-owned signal values. The runner writes, fixture providers read."""
from __future__ import annotations

from datetime import datetime
from typing import Any


class FixtureStore:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}
        self.observed_at: datetime | None = None

    def set_all(self, values: dict[str, dict[str, Any]], observed_at: datetime) -> None:
        self.values = {k: dict(v) for k, v in values.items()}
        self.observed_at = observed_at

    def update(self, kind: str, patch: dict[str, Any]) -> None:
        self.values.setdefault(kind, {}).update(patch)

    def get(self, kind: str) -> dict[str, Any] | None:
        return self.values.get(kind)
```

`apps/api/campuspulse/providers/signals_fixture.py`
```python
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from campuspulse.core.models import Signal, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.providers.fixture_store import FixtureStore

VALID_FOR = timedelta(minutes=10)


class FixtureSignalProvider:
    kind: str = ""
    source_mode = SourceMode.fixture

    def __init__(self, store: FixtureStore, kind: str | None = None) -> None:
        self.store = store
        if kind:
            self.kind = kind

    def fetch(self, at: datetime, context: dict[str, Any]) -> Signal:
        value = self.store.get(self.kind)
        if value is None:
            raise ProviderError("unavailable", f"fixture has no {self.kind} value")
        observed = self.store.observed_at or at
        return Signal(kind=self.kind, observed_at=observed, valid_until=observed + VALID_FOR, value=value, source_mode=self.source_mode)
```

`apps/api/campuspulse/providers/weather/fixture.py`
```python
from campuspulse.providers.signals_fixture import FixtureSignalProvider


class FixtureWeatherProvider(FixtureSignalProvider):
    kind = "rain"
```

`apps/api/campuspulse/providers/flood/fixture.py`
```python
from campuspulse.providers.signals_fixture import FixtureSignalProvider


class FixtureFloodProvider(FixtureSignalProvider):
    kind = "flood"
```

`apps/api/campuspulse/providers/bike/fixture.py`
```python
from campuspulse.providers.signals_fixture import FixtureSignalProvider


class FixtureBikeProvider(FixtureSignalProvider):
    kind = "bike"
```

`apps/api/campuspulse/providers/transit/fixture.py`
```python
from campuspulse.providers.signals_fixture import FixtureSignalProvider


class FixtureTransitProvider(FixtureSignalProvider):
    kind = "transit"
```

`apps/api/campuspulse/providers/parking/fixture.py`
```python
from campuspulse.providers.signals_fixture import FixtureSignalProvider


class FixtureParkingProvider(FixtureSignalProvider):
    kind = "parking"
```

`apps/api/campuspulse/providers/routing/fixture.py`
```python
"""Canned routes for the canonical NCKU scenario. Ignores origin/destination on purpose."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from campuspulse.core.models import LatLng, Mode, RouteResult, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.settings import API_ROOT

ROUTES_DIR = API_ROOT / "fixtures" / "routes"


def _to_route(raw: dict) -> RouteResult:
    alt = raw.get("alternative")
    return RouteResult(
        mode=Mode(raw["mode"]),
        duration_min=raw["duration_min"],
        distance_m=raw["distance_m"],
        polyline=[LatLng(lat=p[0], lng=p[1]) for p in raw.get("polyline", [])],
        summary=raw.get("summary", ""),
        corridor_ids=raw.get("corridor_ids", []),
        source_mode=SourceMode.fixture,
        mode_proxy=raw.get("mode_proxy"),
        alternative=_to_route(alt) if alt else None,
    )


class FixtureRoutingProvider:
    name = "fixture-routes"
    source_mode = SourceMode.fixture

    def __init__(self, routes_dir: Path = ROUTES_DIR) -> None:
        self.routes_dir = routes_dir

    def route(self, origin: LatLng, destination: LatLng, mode: Mode, depart_at: datetime) -> RouteResult:
        path = self.routes_dir / f"{mode.value}.json"
        if not path.exists():
            raise ProviderError("unavailable", f"no fixture route for {mode.value}")
        with path.open(encoding="utf-8") as f:
            return _to_route(json.load(f))
```

`apps/api/campuspulse/providers/indoor/fixture.py`
```python
from __future__ import annotations

from campuspulse.core.campus import Campus
from campuspulse.core.models import IndoorGuidance, SourceMode
from campuspulse.providers.base import ProviderError


class FixtureIndoorProvider:
    source_mode = SourceMode.fixture

    def __init__(self, campus: Campus) -> None:
        self.campus = campus

    def locate(self, building_id: str, room: str) -> IndoorGuidance:
        r = self.campus.room(room)
        if r is None or r.building_id != building_id:
            raise ProviderError("unavailable", f"no fixture guidance for {building_id}/{room}")
        entrance = self.campus.entrance(building_id, r.entrance_id)
        return IndoorGuidance(
            building_id=building_id, room=room, floor=r.floor, wing=r.wing,
            entrance=entrance.name, instructions=r.instructions, source_mode=SourceMode.fixture,
        )
```

`apps/api/campuspulse/providers/email/fixture.py`
```python
from __future__ import annotations

from typing import Any


class FixtureEmailProvider:
    """Never sends. Returns previews and dry-run receipts."""

    def preview(self, to: list[str], subject: str, body: str) -> dict[str, Any]:
        return {"to": to, "subject": subject, "body": body, "provider": "fixture"}

    def send(self, preview: dict[str, Any]) -> dict[str, Any]:
        return {"status": "dry_run", "to": preview.get("to", []), "subject": preview.get("subject", "")}
```

`apps/api/campuspulse/providers/calendar/fixture.py`
```python
from __future__ import annotations

from typing import Any


class FixtureCalendarProvider:
    def preview_change(self, change: dict[str, Any]) -> dict[str, Any]:
        return {"change": change, "provider": "fixture"}

    def execute_change(self, preview: dict[str, Any]) -> dict[str, Any]:
        return {"status": "dry_run", "change": preview.get("change")}
```

`apps/api/campuspulse/providers/registry.py`
```python
"""Assemble providers. Live only when PROVIDER_MODE=auto, the key exists, and the class is implemented."""
from __future__ import annotations

from dataclasses import dataclass, field

from campuspulse.core.campus import Campus
from campuspulse.providers.base import CalendarProvider, EmailProvider, IndoorProvider, RoutingProvider, SignalProvider
from campuspulse.providers.bike.fixture import FixtureBikeProvider
from campuspulse.providers.calendar.fixture import FixtureCalendarProvider
from campuspulse.providers.email.fixture import FixtureEmailProvider
from campuspulse.providers.fixture_store import FixtureStore
from campuspulse.providers.flood.fixture import FixtureFloodProvider
from campuspulse.providers.indoor.fixture import FixtureIndoorProvider
from campuspulse.providers.parking.fixture import FixtureParkingProvider
from campuspulse.providers.routing.fixture import FixtureRoutingProvider
from campuspulse.providers.transit.fixture import FixtureTransitProvider
from campuspulse.providers.weather.fixture import FixtureWeatherProvider
from campuspulse.settings import Settings

# kind -> (live class, settings attribute names that must be non-empty). Task 9/11 fill these.
LIVE_SIGNAL_CLASSES: dict[str, tuple[type, tuple[str, ...]]] = {}
LIVE_ROUTING_CLASS: tuple[type, tuple[str, ...]] | None = None


@dataclass
class Providers:
    routing: RoutingProvider
    signals: dict[str, SignalProvider] = field(default_factory=dict)
    indoor: IndoorProvider | None = None
    email: EmailProvider | None = None
    calendar: CalendarProvider | None = None

    def modes(self) -> dict[str, str]:
        out = {"routing": self.routing.source_mode.value}
        out.update({k: p.source_mode.value for k, p in self.signals.items()})
        if self.indoor is not None:
            out["indoor"] = self.indoor.source_mode.value
        return out


def _wants_live(settings: Settings, keys: tuple[str, ...], cls: type) -> bool:
    return settings.provider_mode == "auto" and getattr(cls, "IMPLEMENTED", True) and all(getattr(settings, k) for k in keys)


def build_providers(settings: Settings, store: FixtureStore, campus: Campus) -> Providers:
    if LIVE_ROUTING_CLASS and _wants_live(settings, LIVE_ROUTING_CLASS[1], LIVE_ROUTING_CLASS[0]):
        routing = LIVE_ROUTING_CLASS[0](settings, campus)
    else:
        routing = FixtureRoutingProvider()

    fixture_signals = {
        "rain": FixtureWeatherProvider(store),
        "flood": FixtureFloodProvider(store),
        "bike": FixtureBikeProvider(store),
        "transit": FixtureTransitProvider(store),
        "parking": FixtureParkingProvider(store),
    }
    signals: dict[str, SignalProvider] = {}
    for kind, fixture in fixture_signals.items():
        live = LIVE_SIGNAL_CLASSES.get(kind)
        if live and _wants_live(settings, live[1], live[0]):
            signals[kind] = live[0](settings, campus)
        else:
            signals[kind] = fixture

    return Providers(
        routing=routing,
        signals=signals,
        indoor=FixtureIndoorProvider(campus),
        email=FixtureEmailProvider(),
        calendar=FixtureCalendarProvider(),
    )
```

- [ ] **Step 5: 跑測試確認通過**

Run: `pytest tests/test_providers_fixture.py -v`
Expected: PASS（4 tests）

- [ ] **Step 6: Commit**

```powershell
git add apps/api/campuspulse/providers apps/api/fixtures/routes apps/api/tests/test_providers_fixture.py
git commit -m "feat(providers): add provider contracts, fixture store, fixture providers and registry"
```

---

### Task 5: Planner（純函式）

**Files:**
- Create: `apps/api/campuspulse/core/planner.py`
- Test: `apps/api/tests/test_planner.py`

**Interfaces:**
- Consumes: Task 2 models、Task 3 `Campus`。
- Produces: `plan(commitment: Commitment, origin: LatLng, now: datetime, routes: dict[Mode, RouteResult | None], signals: dict[str, Signal], campus: Campus, user_state: str = "home") -> Plan`；`build_rationale(plan: Plan, commitment: Commitment) -> str`；`MODE_LABEL: dict[Mode, str]`；`POLICY_VERSION`。
- `Plan.options` 為四模式排序後全列（含 selected）；`Plan.selected` 為第一個 feasible 或 on_time 者，否則 None。

- [ ] **Step 1: 寫失敗測試**

`apps/api/tests/test_planner.py`
```python
from datetime import datetime, timedelta, timezone

import pytest

from campuspulse.core.campus import Campus
from campuspulse.core.models import Commitment, Importance, LatLng, Mode, PlanStatus, Signal
from campuspulse.core.planner import plan
from campuspulse.providers.routing.fixture import FixtureRoutingProvider

TPE = timezone(timedelta(hours=8))
START = datetime(2026, 9, 23, 9, 0, tzinfo=TPE)
ORIGIN = LatLng(lat=22.9905, lng=120.2280)
DEST = LatLng(lat=22.9997, lng=120.2220)


@pytest.fixture(scope="module")
def campus():
    return Campus.load()


def _routes(now):
    r = FixtureRoutingProvider()
    return {m: r.route(ORIGIN, DEST, m, now) for m in Mode}


def _signals(now, **over):
    base = {
        "rain": {"mm_per_hour": 0, "forecast_next_hour_mm": 0},
        "flood": {"alerts": []},
        "bike": {"origin_station_id": "yb-dongning", "available": 8, "dest_station_id": "yb-ncku-north", "docks": 5,
                 "next_station_id": "yb-ncku-east", "next_station_docks": 9},
        "transit": {"route_name": "5", "next_eta_min": 6, "board_stop_id": "bs-dongning", "alight_stop_id": "bs-ncku-north"},
        "parking": {"lots": {"lot-a": {"free": 12}, "lot-b": {"free": 30}, "lot-c": {"free": 5}}},
    }
    for k, v in over.items():
        base[k] = v
    return {k: Signal(kind=k, observed_at=now, value=v) for k, v in base.items()}


def _commitment(importance=Importance.high):
    return Commitment(id="c1", title="小組報告", start=START, building_id="csie", room="4263", importance=importance)


def test_baseline_selects_scooter_with_open_air_lot(campus):
    now = START - timedelta(minutes=70)
    p = plan(_commitment(), ORIGIN, now, _routes(now), _signals(now), campus)
    assert p.status == PlanStatus.ok
    assert p.selected.mode == Mode.scooter
    assert p.selected.last_decision.kind == "parking_lot" and p.selected.last_decision.target_id == "lot-a"
    assert all(o.feasible for o in p.options)
    assert p.selected.arrive_at <= START - timedelta(minutes=10)


def test_bike_zero_is_infeasible(campus):
    now = START - timedelta(minutes=70)
    sig = _signals(now)
    sig["bike"].value["available"] = 0
    p = plan(_commitment(), ORIGIN, now, _routes(now), sig, campus)
    bike = next(o for o in p.options if o.mode == Mode.bike)
    assert not bike.feasible and "no_bike" in bike.reasons


def test_heavy_rain_disqualifies_bike_and_prefers_covered_lot(campus):
    now = START - timedelta(minutes=45)
    sig = _signals(now, rain={"mm_per_hour": 25, "forecast_next_hour_mm": 30})
    p = plan(_commitment(), ORIGIN, now, _routes(now), sig, campus)
    bike = next(o for o in p.options if o.mode == Mode.bike)
    scooter = next(o for o in p.options if o.mode == Mode.scooter)
    assert "unsafe_heavy_rain" in bike.reasons
    assert scooter.last_decision.target_id == "lot-b"


def test_flood_reroutes_scooter_and_switches_to_transit_for_high_importance(campus):
    now = START - timedelta(minutes=45)  # 08:15
    sig = _signals(
        now,
        rain={"mm_per_hour": 25, "forecast_next_hour_mm": 30},
        flood={"alerts": [{"corridor_id": "xiaodong-rd", "level": "warning"}]},
        bike={"origin_station_id": "yb-dongning", "available": 0, "dest_station_id": "yb-ncku-north", "docks": 5,
              "next_station_id": "yb-ncku-east", "next_station_docks": 9},
        transit={"route_name": "5", "next_eta_min": 4, "board_stop_id": "bs-dongning", "alight_stop_id": "bs-ncku-north"},
        parking={"lots": {"lot-a": {"free": 0}, "lot-b": {"free": 30}, "lot-c": {"free": 5}}},
    )
    p = plan(_commitment(), ORIGIN, now, _routes(now), sig, campus)
    scooter = next(o for o in p.options if o.mode == Mode.scooter)
    walk = next(o for o in p.options if o.mode == Mode.walk)
    assert "rerouted" in scooter.risk_flags and scooter.route.corridor_ids == ["changrong-rd"]
    assert scooter.last_decision.target_id == "lot-b"
    assert not walk.feasible and "too_late" in walk.reasons
    assert p.selected.mode == Mode.transit
    assert p.selected.last_decision.kind == "bus_stop"


def test_bike_dock_full_moves_return_station(campus):
    now = START - timedelta(minutes=70)
    sig = _signals(now)
    sig["bike"].value["docks"] = 0
    p = plan(_commitment(), ORIGIN, now, _routes(now), sig, campus)
    bike = next(o for o in p.options if o.mode == Mode.bike)
    assert bike.last_decision.target_id == "yb-ncku-east"


def test_all_lots_full_makes_scooter_infeasible(campus):
    now = START - timedelta(minutes=70)
    sig = _signals(now, parking={"lots": {"lot-a": {"free": 0}, "lot-b": {"free": 0}, "lot-c": {"free": 0}}})
    p = plan(_commitment(), ORIGIN, now, _routes(now), sig, campus)
    scooter = next(o for o in p.options if o.mode == Mode.scooter)
    assert not scooter.feasible and "no_parking" in scooter.reasons


def test_late_risk_when_buffer_is_eaten(campus):
    now = START - timedelta(minutes=33)  # 08:27
    sig = _signals(
        now,
        rain={"mm_per_hour": 25, "forecast_next_hour_mm": 30},
        flood={"alerts": [{"corridor_id": "xiaodong-rd", "level": "warning"}]},
        bike={"origin_station_id": "yb-dongning", "available": 0, "dest_station_id": "yb-ncku-north", "docks": 5,
              "next_station_id": "yb-ncku-east", "next_station_docks": 9},
        transit={"route_name": "5", "next_eta_min": 3, "board_stop_id": "bs-dongning", "alight_stop_id": "bs-ncku-north"},
        parking={"lots": {"lot-a": {"free": 0}, "lot-b": {"free": 30}, "lot-c": {"free": 5}}},
    )
    p = plan(_commitment(), ORIGIN, now, _routes(now), sig, campus)
    assert p.status == PlanStatus.late_risk
    assert p.selected is not None and p.selected.on_time and not p.selected.feasible
    assert 0 < p.selected.slack_min < 10


def test_no_feasible_when_everything_is_too_late(campus):
    now = START - timedelta(minutes=5)
    p = plan(_commitment(), ORIGIN, now, _routes(now), _signals(now), campus)
    assert p.status == PlanStatus.no_feasible and p.selected is None


def test_normal_importance_prefers_time_over_reliability(campus):
    now = START - timedelta(minutes=70)
    p = plan(_commitment(Importance.normal), ORIGIN, now, _routes(now), _signals(now), campus)
    assert p.selected.mode == Mode.scooter
    assert p.selected.arrive_at <= START - timedelta(minutes=5)


def test_missing_rain_signal_flags_risk_not_crash(campus):
    now = START - timedelta(minutes=70)
    sig = _signals(now)
    del sig["rain"]
    p = plan(_commitment(), ORIGIN, now, _routes(now), sig, campus)
    assert "rain_unavailable" in p.selected.risk_flags


def test_arrived_state(campus):
    now = START - timedelta(minutes=10)
    p = plan(_commitment(), ORIGIN, now, _routes(now), _signals(now), campus, user_state="arrived_building")
    assert p.status == PlanStatus.arrived
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_planner.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'campuspulse.core.planner'`

- [ ] **Step 3: 實作 planner.py**

`apps/api/campuspulse/core/planner.py`
```python
"""Deterministic travel planner. Pure: no I/O, no wall clock, no model calls."""
from __future__ import annotations

from datetime import datetime, timedelta

from campuspulse.core.campus import Campus
from campuspulse.core.models import (
    Commitment, Importance, LastDecision, LatLng, Mode, Plan, PlanStatus, RouteResult, Signal, SourceMode, TravelOption,
)

POLICY_VERSION = "0.1"
BUFFER_MIN = {Importance.normal: 5, Importance.high: 10, Importance.critical: 15}
FIXED_COST_MIN = {Mode.walk: 0.0, Mode.bike: 2.0, Mode.scooter: 3.0, Mode.transit: 2.0}
BASE_RELIABILITY = {Mode.walk: 0.9, Mode.bike: 0.6, Mode.scooter: 0.7, Mode.transit: 0.8}
MODE_ORDER = [Mode.scooter, Mode.transit, Mode.bike, Mode.walk]
MODE_LABEL = {Mode.walk: "步行", Mode.scooter: "機車", Mode.bike: "YouBike", Mode.transit: "公車"}
RECHECK_MIN = 5
RECHECK_URGENT_MIN = 2
TRANSIT_UNKNOWN_WAIT_MIN = 10.0
REASON_LABEL = {
    "route_unavailable": "查無路線",
    "unsafe_heavy_rain": "豪雨不安全",
    "flood_on_route": "路線積淹水",
    "no_bike": "起點站無車",
    "no_dock": "終點站無位",
    "no_parking": "停車場全滿",
    "too_late": "已來不及準時",
}


def rain_factor(mode: Mode, rain_mm_h: float) -> float | None:
    if rain_mm_h >= 20:
        return {Mode.walk: 1.6, Mode.bike: None, Mode.scooter: 1.3, Mode.transit: 1.1}[mode]
    if rain_mm_h >= 5:
        return {Mode.walk: 1.3, Mode.bike: 1.4, Mode.scooter: 1.2, Mode.transit: 1.05}[mode]
    return 1.0


def _known(signals: dict[str, Signal], kind: str) -> Signal | None:
    s = signals.get(kind)
    if s is None or s.source_mode == SourceMode.unavailable:
        return None
    return s


def _rain_mm(signals: dict[str, Signal]) -> tuple[float, bool]:
    s = _known(signals, "rain")
    if s is None:
        return 0.0, False
    v = s.value
    return max(float(v.get("mm_per_hour", 0)), float(v.get("forecast_next_hour_mm", 0))), True


def _flooded(signals: dict[str, Signal]) -> tuple[set[str], bool]:
    s = _known(signals, "flood")
    if s is None:
        return set(), False
    return {a["corridor_id"] for a in s.value.get("alerts", []) if a.get("level") in ("warning", "danger")}, True


def _resolve_route(route: RouteResult, mode: Mode, flooded: set[str]) -> tuple[RouteResult | None, list[str], list[str]]:
    if mode == Mode.transit or not (set(route.corridor_ids) & flooded):
        return route, [], []
    alt = route.alternative
    if alt and not (set(alt.corridor_ids) & flooded):
        return alt, [], ["rerouted"]
    return None, ["flood_on_route"], ["flood_on_route"]


def _fmt(sig: Signal, text: str) -> str:
    return f"{text}（{sig.source_mode.value}，{sig.observed_at.strftime('%H:%M')}）"


def _last_decision(
    mode: Mode, commitment: Commitment, origin: LatLng, campus: Campus, signals: dict[str, Signal], rain_mm: float
) -> tuple[LastDecision | None, list[str], list[str], list[str]]:
    """Returns (decision, reasons, risk_flags, evidence)."""
    b = commitment.building_id
    if mode == Mode.scooter:
        s = _known(signals, "parking")
        risks: list[str] = []
        if s is None:
            candidates = list(campus.lots)
            free_of = {lot.id: None for lot in candidates}
            risks.append("parking_unavailable")
            evidence = ["停車場狀態不可用，假設有位"]
        else:
            lots_state = s.value.get("lots", {})
            free_of = {lot.id: int(lots_state.get(lot.id, {}).get("free", 0)) for lot in campus.lots}
            candidates = [lot for lot in campus.lots if free_of[lot.id] > 0]
            evidence = [_fmt(s, "停車場剩位 " + ", ".join(f"{lot.id}:{free_of[lot.id]}" for lot in campus.lots))]
        if not candidates:
            return None, ["no_parking"], risks, evidence
        ranked = sorted(
            candidates,
            key=lambda lot: (0 if (rain_mm >= 5 and lot.covered) else 1, campus.walk_to_building(lot.location, b)[1]),
        )
        lot = ranked[0]
        entrance, walk = campus.walk_to_building(lot.location, b)
        free_txt = f"剩 {free_of[lot.id]} 位" if free_of[lot.id] is not None else "剩位未知"
        reason = f"{'有遮雨、' if lot.covered else ''}離{entrance.name}步行 {walk} 分，{free_txt}"
        return LastDecision(kind="parking_lot", target_id=lot.id, label=lot.name, walk_min=walk, reason=reason, location=lot.location), [], risks, evidence

    if mode == Mode.bike:
        s = _known(signals, "bike")
        if s is None:
            return None, ["route_unavailable"], ["bike_unavailable"], ["YouBike 狀態不可用"]
        v = s.value
        evidence = [_fmt(s, f"起點站可借 {v.get('available')}，終點站可還 {v.get('docks')}")]
        if int(v.get("available", 0)) <= 0:
            return None, ["no_bike"], [], evidence
        station = campus.bike_station(v["dest_station_id"])
        reason = "終點站有空位"
        if int(v.get("docks", 0)) <= 0:
            if int(v.get("next_station_docks", 0)) <= 0:
                return None, ["no_dock"], [], evidence
            station = campus.bike_station(v["next_station_id"])
            reason = "原站無空位，改還下一站"
        entrance, walk = campus.walk_to_building(station.location, b)
        return LastDecision(kind="bike_dock", target_id=station.id, label=station.name, walk_min=walk, reason=f"{reason}，離{entrance.name}步行 {walk} 分", location=station.location), [], [], evidence

    if mode == Mode.transit:
        s = _known(signals, "transit")
        if s is None:
            return None, ["route_unavailable"], ["transit_unavailable"], ["公車狀態不可用"]
        v = s.value
        stop = campus.bus_stop(v["alight_stop_id"])
        entrance, walk = campus.walk_to_building(stop.location, b)
        eta = v.get("next_eta_min")
        evidence = [_fmt(s, f"{v.get('route_name', '')} 號公車下一班 {eta if eta is not None else '未知'} 分")]
        return LastDecision(kind="bus_stop", target_id=stop.id, label=stop.name, walk_min=walk, reason=f"離{entrance.name}最近的站，步行 {walk} 分", location=stop.location), [], [], evidence

    entrance = campus.nearest_entrance(b, origin)
    return LastDecision(kind="gate", target_id=entrance.id, label=entrance.name, walk_min=0.0, reason="離你方向最近的入口", location=entrance.location), [], [], []


def evaluate_option(
    mode: Mode, commitment: Commitment, origin: LatLng, now: datetime, route: RouteResult | None,
    signals: dict[str, Signal], campus: Campus,
) -> TravelOption:
    reasons: list[str] = []
    risks: list[str] = []
    evidence: list[str] = []
    if route is None:
        return TravelOption(mode=mode, reasons=["route_unavailable"], risk_flags=["routing_unavailable"])

    rain_mm, rain_known = _rain_mm(signals)
    if not rain_known:
        risks.append("rain_unavailable")
    else:
        evidence.append(_fmt(signals["rain"], f"雨量 {rain_mm:g} mm/h"))
    flooded, flood_known = _flooded(signals)
    if not flood_known:
        risks.append("flood_unavailable")
    elif flooded:
        evidence.append(_fmt(signals["flood"], "積淹水警戒：" + ", ".join(sorted(flooded))))

    route_used, r_reasons, r_risks = _resolve_route(route, mode, flooded)
    reasons += r_reasons
    risks += r_risks
    factor = rain_factor(mode, rain_mm)
    if factor is None:
        reasons.append("unsafe_heavy_rain")
        factor = 1.0

    decision, d_reasons, d_risks, d_evidence = _last_decision(mode, commitment, origin, campus, signals, rain_mm)
    reasons += d_reasons
    risks += d_risks
    evidence += d_evidence

    base = (route_used or route).duration_min
    conservative = base * factor + FIXED_COST_MIN[mode] + (decision.walk_min if decision else 0.0)

    buffer = timedelta(minutes=BUFFER_MIN[commitment.importance])
    deadline = commitment.start - buffer

    if mode == Mode.transit:
        transit = _known(signals, "transit")
        eta = transit.value.get("next_eta_min") if transit else None
        if eta is None:
            conservative += TRANSIT_UNKNOWN_WAIT_MIN
            risks.append("transit_eta_unavailable")
            depart_at = now
        else:
            depart_at = now + timedelta(minutes=float(eta))
    else:
        latest = deadline - timedelta(minutes=conservative)
        depart_at = max(now, latest)
    arrive_at = depart_at + timedelta(minutes=conservative)

    feasible = not reasons and arrive_at <= deadline
    on_time = not reasons and arrive_at <= commitment.start
    if not reasons and not on_time:
        reasons.append("too_late")
    slack = round((commitment.start - arrive_at).total_seconds() / 60, 1)

    reliability = BASE_RELIABILITY[mode]
    if rain_mm >= 5:
        reliability -= {Mode.bike: 0.2, Mode.walk: 0.1}.get(mode, 0.0)
    if rain_mm >= 20 and mode == Mode.scooter:
        reliability -= 0.1
    if any(r.endswith("_unavailable") for r in risks):
        reliability -= 0.3
    reliability = max(0.0, min(1.0, reliability))

    return TravelOption(
        mode=mode, route=route_used or route, last_decision=decision, base_eta_min=base,
        conservative_eta_min=round(conservative, 1), depart_at=depart_at, arrive_at=arrive_at,
        feasible=feasible, on_time=on_time, slack_min=slack, reasons=reasons, risk_flags=risks,
        reliability=round(reliability, 2), evidence=evidence,
    )


def _score(option: TravelOption, importance: Importance, max_cons: float) -> float:
    time_part = 1.0 - (option.conservative_eta_min / max_cons if max_cons else 0.0)
    if importance in (Importance.high, Importance.critical):
        return round(0.7 * option.reliability + 0.3 * time_part, 3)
    return round(0.3 * option.reliability + 0.7 * time_part, 3)


def plan(
    commitment: Commitment, origin: LatLng, now: datetime, routes: dict[Mode, RouteResult | None],
    signals: dict[str, Signal], campus: Campus, user_state: str = "home",
) -> Plan:
    options = [evaluate_option(m, commitment, origin, now, routes.get(m), signals, campus) for m in MODE_ORDER]
    max_cons = max((o.conservative_eta_min for o in options if o.route), default=1.0) or 1.0
    for o in options:
        o.score = _score(o, commitment.importance, max_cons)
    ranked = sorted(options, key=lambda o: (0 if o.feasible else 1 if o.on_time else 2, -o.score, o.conservative_eta_min))
    top = ranked[0]
    selected = top if (top.feasible or top.on_time) else None

    if user_state == "arrived_building":
        status = PlanStatus.arrived
    elif selected is None:
        status = PlanStatus.no_feasible
    elif not selected.feasible:
        status = PlanStatus.late_risk
    else:
        status = PlanStatus.ok

    decisions = len(options) + 1 + sum(1 for o in options if o.last_decision)
    urgent = status in (PlanStatus.late_risk, PlanStatus.no_feasible)
    p = Plan(
        commitment_id=commitment.id, generated_at=now, selected=selected, options=ranked,
        next_check_at=now + timedelta(minutes=RECHECK_URGENT_MIN if urgent else RECHECK_MIN),
        status=status, policy_version=POLICY_VERSION, decisions_made=decisions,
    )
    p.rationale = build_rationale(p, commitment)
    return p


def _hhmm(dt: datetime | None) -> str:
    return dt.strftime("%H:%M") if dt else "--:--"


def build_rationale(p: Plan, commitment: Commitment) -> str:
    rejected = [o for o in p.options if p.selected is None or o.mode != p.selected.mode]
    rejected_txt = "；".join(
        f"{MODE_LABEL[o.mode]}：" + ("、".join(REASON_LABEL.get(r, r) for r in o.reasons) if o.reasons else f"可行但分數較低（可靠度 {o.reliability}）")
        for o in rejected
    )
    if p.status == PlanStatus.arrived:
        return "你已到大樓，切換為教室導引。"
    if p.selected is None:
        return f"四種方式都無法在 {_hhmm(commitment.start)} 前抵達。建議先通知助教與組員。{rejected_txt}"
    s = p.selected
    ld = f"，{s.last_decision.label}（{s.last_decision.reason}）" if s.last_decision else ""
    head = f"建議 {_hhmm(s.depart_at)} 出門{MODE_LABEL[s.mode]}，預計 {_hhmm(s.arrive_at)} 到{ld}。"
    if p.status == PlanStatus.late_risk:
        head += f" 緩衝只剩 {s.slack_min:g} 分鐘，再晚就會遲到。"
    return head + " 其他：" + rejected_txt
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_planner.py -v`
Expected: PASS（11 tests）。若 `test_flood_reroutes...` 的 selected 不是 transit，檢查 `_score`：high 重要度應為 `0.7*reliability + 0.3*time_part`。

- [ ] **Step 5: Commit**

```powershell
git add apps/api/campuspulse/core/planner.py apps/api/tests/test_planner.py
git commit -m "feat(core): add deterministic four-mode planner with last-mile decisions"
```

---

### Task 6: Triggers

**Files:**
- Create: `apps/api/campuspulse/core/triggers.py`
- Test: `apps/api/tests/test_triggers.py`

**Interfaces:**
- Consumes: Task 2 `Plan`, `Trigger`, `TravelOption`；Task 5 `MODE_LABEL`。
- Produces: `detect_triggers(old: Plan | None, new: Plan, now: datetime) -> list[Trigger]`；`apply_cooldown(triggers: list[Trigger], history: list[Trigger], now: datetime) -> list[Trigger]`（回傳同一批，但被冷卻者 `material=False`）。

- [ ] **Step 1: 寫失敗測試**

`apps/api/tests/test_triggers.py`
```python
from datetime import datetime, timedelta, timezone

from campuspulse.core.models import Mode, Plan, PlanStatus, TravelOption, Trigger
from campuspulse.core.triggers import apply_cooldown, detect_triggers

TPE = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 8, 15, tzinfo=TPE)


def _opt(mode, feasible=True, depart=NOW, eta=20.0, risks=None):
    return TravelOption(mode=mode, feasible=feasible, on_time=feasible, depart_at=depart, arrive_at=depart + timedelta(minutes=eta),
                        conservative_eta_min=eta, risk_flags=risks or [])


def _plan(selected, options, status=PlanStatus.ok):
    return Plan(commitment_id="c1", generated_at=NOW, selected=selected, options=options, status=status)


def test_initial_plan_is_single_material_trigger():
    p = _plan(_opt(Mode.scooter), [_opt(Mode.scooter)])
    t = detect_triggers(None, p, NOW)
    assert [x.kind for x in t] == ["initial_plan"] and t[0].material


def test_feasibility_flip_and_mode_change_are_material():
    old = _plan(_opt(Mode.scooter), [_opt(Mode.scooter), _opt(Mode.bike)])
    new = _plan(_opt(Mode.transit), [_opt(Mode.transit), _opt(Mode.scooter), _opt(Mode.bike, feasible=False)])
    kinds = {t.kind for t in detect_triggers(old, new, NOW) if t.material}
    assert {"feasibility_flip", "selected_mode_changed"} <= kinds


def test_small_eta_drift_is_not_material():
    old = _plan(_opt(Mode.scooter, eta=20), [_opt(Mode.scooter, eta=20)])
    new = _plan(_opt(Mode.scooter, eta=22), [_opt(Mode.scooter, eta=22)])
    t = detect_triggers(old, new, NOW)
    assert all(not x.material for x in t)


def test_big_eta_increase_and_earlier_departure_are_material():
    old = _plan(_opt(Mode.scooter, eta=20, depart=NOW + timedelta(minutes=20)), [_opt(Mode.scooter, eta=20)])
    new = _plan(_opt(Mode.scooter, eta=27, depart=NOW + timedelta(minutes=13)), [_opt(Mode.scooter, eta=27)])
    kinds = {t.kind for t in detect_triggers(old, new, NOW) if t.material}
    assert {"eta_increase", "depart_earlier"} <= kinds


def test_cooldown_suppresses_repeat_but_not_flip():
    history = [Trigger(kind="eta_increase", description="", observed_at=NOW - timedelta(minutes=2))]
    fresh = [
        Trigger(kind="eta_increase", description="", observed_at=NOW),
        Trigger(kind="feasibility_flip", description="", observed_at=NOW),
    ]
    out = apply_cooldown(fresh, history, NOW)
    assert out[0].material is False and out[1].material is True
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_triggers.py -v`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: 實作 triggers.py**

`apps/api/campuspulse/core/triggers.py`
```python
"""Material-change detection between consecutive plans."""
from __future__ import annotations

from datetime import datetime, timedelta

from campuspulse.core.models import Plan, Trigger
from campuspulse.core.planner import MODE_LABEL

MATERIAL_ETA_INCREASE_MIN = 5.0
MATERIAL_DEPART_EARLIER_MIN = 3.0
COOLDOWN = timedelta(minutes=5)
ALWAYS_MATERIAL = {"initial_plan", "feasibility_flip"}


def detect_triggers(old: Plan | None, new: Plan, now: datetime) -> list[Trigger]:
    if old is None:
        return [Trigger(kind="initial_plan", description="產生初始計畫", observed_at=now, material=True)]
    out: list[Trigger] = []
    old_by = {o.mode: o for o in old.options}
    for n in new.options:
        o = old_by.get(n.mode)
        if o is not None and o.feasible != n.feasible:
            out.append(Trigger(
                kind="feasibility_flip", description=f"{MODE_LABEL[n.mode]}{'變為可行' if n.feasible else '不再可行'}",
                old=o.feasible, new=n.feasible, observed_at=now, material=True,
            ))
    old_mode = old.selected.mode if old.selected else None
    new_mode = new.selected.mode if new.selected else None
    if old_mode != new_mode:
        out.append(Trigger(
            kind="selected_mode_changed",
            description=f"建議從 {MODE_LABEL[old_mode] if old_mode else '無'} 改為 {MODE_LABEL[new_mode] if new_mode else '無'}",
            old=old_mode.value if old_mode else None, new=new_mode.value if new_mode else None, observed_at=now, material=True,
        ))
    elif old.selected and new.selected:
        o, n = old.selected, new.selected
        if o.depart_at and n.depart_at:
            earlier = (o.depart_at - n.depart_at).total_seconds() / 60
            if earlier > MATERIAL_DEPART_EARLIER_MIN:
                out.append(Trigger(kind="depart_earlier", description=f"出門時間提早 {earlier:.0f} 分", old=o.depart_at, new=n.depart_at, observed_at=now, material=True))
        delta = n.conservative_eta_min - o.conservative_eta_min
        if delta > MATERIAL_ETA_INCREASE_MIN:
            out.append(Trigger(kind="eta_increase", description=f"預估時間增加 {delta:.0f} 分", old=o.conservative_eta_min, new=n.conservative_eta_min, observed_at=now, material=True))
        elif delta != 0:
            out.append(Trigger(kind="eta_drift", description=f"預估時間變動 {delta:+.0f} 分", old=o.conservative_eta_min, new=n.conservative_eta_min, observed_at=now, material=False))
        if "rerouted" in n.risk_flags and "rerouted" not in o.risk_flags:
            out.append(Trigger(kind="rerouted", description="原路線積淹水，已改道", observed_at=now, material=True))
    if old.status != new.status:
        out.append(Trigger(kind="status_changed", description=f"狀態 {old.status.value} → {new.status.value}", old=old.status.value, new=new.status.value, observed_at=now, material=True))
    return out


def apply_cooldown(triggers: list[Trigger], history: list[Trigger], now: datetime) -> list[Trigger]:
    for t in triggers:
        if t.kind in ALWAYS_MATERIAL or not t.material:
            continue
        if any(h.kind == t.kind and (now - h.observed_at) < COOLDOWN for h in history):
            t.material = False
    return triggers
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_triggers.py -v`
Expected: PASS（5 tests）

- [ ] **Step 5: Commit**

```powershell
git add apps/api/campuspulse/core/triggers.py apps/api/tests/test_triggers.py
git commit -m "feat(core): add material-change triggers with cooldown"
```

---

### Task 7: 行動建構、Agent loop、劇本 runner

**Files:**
- Create: `apps/api/campuspulse/core/actions.py`, `apps/api/campuspulse/core/loop.py`, `apps/api/campuspulse/scenario/__init__.py`, `apps/api/campuspulse/scenario/runner.py`, `apps/api/fixtures/scenarios/ncku-wed-0900.json`
- Test: `apps/api/tests/test_scenario.py`

**Interfaces:**
- Consumes: Task 4 `Providers`, `FixtureStore`, `ProviderError`；Task 5 `plan`, `MODE_LABEL`；Task 6 `detect_triggers`, `apply_cooldown`。
- Produces:
  - `build_late_email(commitment: Commitment, plan: Plan, signals: dict[str, Signal]) -> dict`（keys `to: list[str]`, `subject: str`, `body: str`）。
  - `AgentLoop(campus, providers, commitment, origin, rationale_fn=None, dry_run=True)`；`.reset()`；`.run(now: datetime, user_state: str) -> None`；`.confirm_action(action_id: str, now: datetime) -> ProposedAction`；`.reject_action(action_id, now) -> ProposedAction`；`.snapshot() -> dict`；屬性 `plan, timeline, actions, trigger_history, signals, routes, indoor, decisions_agent, decisions_user, clock, user_state`。
  - `rationale_fn` 簽名：`(plan: Plan, commitment: Commitment, triggers: list[Trigger]) -> str`；None 時用 `plan.rationale`。
  - `Scenario.load(path: Path) -> Scenario`（欄位 `id, title, commitment, origin, steps: list[ScenarioStep]`；`ScenarioStep(at, user_state="home", signals: dict[str, dict], note="")`）。
  - `ScenarioRunner(scenario, loop, store)`；`.reset() -> dict`；`.step() -> dict`；`.inject(overrides: dict[str, dict]) -> dict`；`.snapshot() -> dict`；`.index: int`。
- snapshot 形狀（前端 `types.ts` 依此）：
  ```
  { clock, user_state, step_index, step_count, step_note, scenario_title,
    commitment, origin, building: {id,name,campus,location},
    plan, signals: {kind: Signal}, routes_source: {mode: source_mode},
    timeline: TimelineEvent[], triggers: Trigger[], actions: ProposedAction[],
    decisions: {agent, user}, indoor: IndoorGuidance|null, providers: {name: source_mode} }
  ```

- [ ] **Step 1: 寫劇本 fixture**

`apps/api/fixtures/scenarios/ncku-wed-0900.json`
```json
{
  "id": "ncku-wed-0900",
  "title": "週三 09:00 小組報告，資訊系館 4263",
  "commitment": {
    "id": "c-wed-0900",
    "title": "資料庫系統 小組報告",
    "start": "2026-09-23T09:00:00+08:00",
    "building_id": "csie",
    "room": "4263",
    "importance": "high",
    "source": "timetable+email",
    "confirmed": true
  },
  "origin": { "lat": 22.9905, "lng": 120.2280 },
  "steps": [
    {
      "at": "2026-09-23T07:50:00+08:00",
      "user_state": "home",
      "note": "起床，一切正常",
      "signals": {
        "rain": { "mm_per_hour": 0, "forecast_next_hour_mm": 0 },
        "flood": { "alerts": [] },
        "bike": { "origin_station_id": "yb-dongning", "available": 8, "dest_station_id": "yb-ncku-north", "docks": 5, "next_station_id": "yb-ncku-east", "next_station_docks": 9 },
        "transit": { "route_name": "5", "next_eta_min": 6, "board_stop_id": "bs-dongning", "alight_stop_id": "bs-ncku-north" },
        "parking": { "lots": { "lot-a": { "free": 12 }, "lot-b": { "free": 30 }, "lot-c": { "free": 5 } } }
      }
    },
    {
      "at": "2026-09-23T08:15:00+08:00",
      "user_state": "home",
      "note": "暴雨、小東路積淹水、YouBike 借光、露天停車場關閉",
      "signals": {
        "rain": { "mm_per_hour": 25, "forecast_next_hour_mm": 30 },
        "flood": { "alerts": [ { "corridor_id": "xiaodong-rd", "level": "warning" } ] },
        "bike": { "origin_station_id": "yb-dongning", "available": 0, "dest_station_id": "yb-ncku-north", "docks": 5, "next_station_id": "yb-ncku-east", "next_station_docks": 9 },
        "transit": { "route_name": "5", "next_eta_min": 4, "board_stop_id": "bs-dongning", "alight_stop_id": "bs-ncku-north" },
        "parking": { "lots": { "lot-a": { "free": 0 }, "lot-b": { "free": 30 }, "lot-c": { "free": 5 } } }
      }
    },
    {
      "at": "2026-09-23T08:27:00+08:00",
      "user_state": "home",
      "note": "還沒出門",
      "signals": {
        "rain": { "mm_per_hour": 25, "forecast_next_hour_mm": 30 },
        "flood": { "alerts": [ { "corridor_id": "xiaodong-rd", "level": "warning" } ] },
        "bike": { "origin_station_id": "yb-dongning", "available": 0, "dest_station_id": "yb-ncku-north", "docks": 5, "next_station_id": "yb-ncku-east", "next_station_docks": 9 },
        "transit": { "route_name": "5", "next_eta_min": 3, "board_stop_id": "bs-dongning", "alight_stop_id": "bs-ncku-north" },
        "parking": { "lots": { "lot-a": { "free": 0 }, "lot-b": { "free": 30 }, "lot-c": { "free": 5 } } }
      }
    },
    {
      "at": "2026-09-23T08:50:00+08:00",
      "user_state": "arrived_building",
      "note": "到資訊系館樓下",
      "signals": {
        "rain": { "mm_per_hour": 18, "forecast_next_hour_mm": 10 },
        "flood": { "alerts": [ { "corridor_id": "xiaodong-rd", "level": "warning" } ] },
        "bike": { "origin_station_id": "yb-dongning", "available": 0, "dest_station_id": "yb-ncku-north", "docks": 5, "next_station_id": "yb-ncku-east", "next_station_docks": 9 },
        "transit": { "route_name": "5", "next_eta_min": 9, "board_stop_id": "bs-dongning", "alight_stop_id": "bs-ncku-north" },
        "parking": { "lots": { "lot-a": { "free": 0 }, "lot-b": { "free": 22 }, "lot-c": { "free": 2 } } }
      }
    }
  ]
}
```

- [ ] **Step 2: 寫失敗測試**

`apps/api/tests/test_scenario.py`
```python
from campuspulse.core.campus import Campus
from campuspulse.core.loop import AgentLoop
from campuspulse.providers.fixture_store import FixtureStore
from campuspulse.providers.registry import build_providers
from campuspulse.scenario.runner import SCENARIO_DIR, Scenario, ScenarioRunner
from campuspulse.settings import Settings


def _runner():
    campus = Campus.load()
    store = FixtureStore()
    providers = build_providers(Settings(provider_mode="fixture"), store, campus)
    scenario = Scenario.load(SCENARIO_DIR / "ncku-wed-0900.json")
    loop = AgentLoop(campus, providers, scenario.commitment, scenario.origin)
    return ScenarioRunner(scenario, loop, store)


def test_reset_produces_initial_scooter_plan_with_full_loop_timeline():
    r = _runner()
    s = r.reset()
    assert s["step_index"] == 0 and s["plan"]["selected"]["mode"] == "scooter"
    assert {e["phase"] for e in s["timeline"]} == {"perceive", "plan", "act", "reflect"}
    assert s["decisions"]["agent"] > 0 and s["decisions"]["user"] == 0
    assert s["providers"]["routing"] == "fixture"


def test_step_one_switches_to_transit_and_records_material_triggers():
    r = _runner()
    r.reset()
    before = r.snapshot()["decisions"]["agent"]
    s = r.step()
    assert s["plan"]["selected"]["mode"] == "transit"
    kinds = {t["kind"] for t in s["triggers"] if t["material"]}
    assert "selected_mode_changed" in kinds and "feasibility_flip" in kinds
    assert s["decisions"]["agent"] > before
    scooter = next(o for o in s["plan"]["options"] if o["mode"] == "scooter")
    assert scooter["last_decision"]["target_id"] == "lot-b" and "rerouted" in scooter["risk_flags"]


def test_step_two_is_late_risk_and_proposes_email_once():
    r = _runner()
    r.reset(); r.step()
    s = r.step()
    assert s["plan"]["status"] == "late_risk"
    assert len(s["actions"]) == 1 and s["actions"][0]["type"] == "email" and s["actions"][0]["state"] == "proposed"
    assert "4263" in s["actions"][0]["preview"]["body"]
    s = r.inject({"transit": {"next_eta_min": 3}})
    assert len(s["actions"]) == 1  # no duplicate proposal


def test_confirm_is_dry_run_and_counts_user_decision():
    r = _runner()
    r.reset(); r.step(); r.step()
    action_id = r.snapshot()["actions"][0]["id"]
    r.loop.confirm_action(action_id, r.loop.clock)
    s = r.snapshot()
    assert s["actions"][0]["state"] == "executed_dry_run" and s["decisions"]["user"] == 1


def test_step_three_arrived_shows_indoor_card():
    r = _runner()
    r.reset(); r.step(); r.step()
    s = r.step()
    assert s["plan"]["status"] == "arrived"
    assert s["indoor"]["floor"] == "4F" and s["indoor"]["entrance"] == "東側門"
    assert r.step()["step_index"] == 3  # stays on last step


def test_inject_bike_zero_flips_bike_feasibility():
    r = _runner()
    r.reset()
    s = r.inject({"bike": {"available": 0}})
    bike = next(o for o in s["plan"]["options"] if o["mode"] == "bike")
    assert bike["feasible"] is False
    assert any(t["kind"] == "feasibility_flip" for t in s["triggers"])
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `pytest tests/test_scenario.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'campuspulse.core.loop'`

- [ ] **Step 4: 實作 actions.py**

`apps/api/campuspulse/core/actions.py`
```python
"""Build previews for external actions. Never sends anything."""
from __future__ import annotations

from campuspulse.core.models import Commitment, Plan, Signal
from campuspulse.core.planner import MODE_LABEL

# Fixture recipients. C/E replace with contacts derived from course email.
DEFAULT_TO = ["ta@example.edu", "group-db-2026@example.edu"]


def disruption_summary(signals: dict[str, Signal]) -> str:
    parts: list[str] = []
    rain = signals.get("rain")
    if rain and max(float(rain.value.get("mm_per_hour", 0)), float(rain.value.get("forecast_next_hour_mm", 0))) >= 20:
        parts.append("豪雨")
    flood = signals.get("flood")
    if flood and any(a.get("level") in ("warning", "danger") for a in flood.value.get("alerts", [])):
        parts.append("道路積淹水")
    bike = signals.get("bike")
    if bike and int(bike.value.get("available", 1)) <= 0:
        parts.append("YouBike 無車")
    return "、".join(parts) or "交通狀況"


def build_late_email(commitment: Commitment, plan: Plan, signals: dict[str, Signal]) -> dict:
    when = commitment.start.strftime("%m/%d %H:%M")
    subject = f"[{commitment.title}] 可能遲到通知"
    cause = disruption_summary(signals)
    if plan.selected and plan.selected.arrive_at:
        arrive = plan.selected.arrive_at.strftime("%H:%M")
        late = max(0.0, -plan.selected.slack_min)
        body = (
            f"老師、助教、各位組員好：\n\n"
            f"{when} 的「{commitment.title}」（{commitment.room} 教室）因{cause}，"
            f"我已改{MODE_LABEL[plan.selected.mode]}前往，預計 {arrive} 抵達"
            f"{'' if late == 0 else f'，可能晚約 {late:.0f} 分鐘'}。\n\n"
            f"造成不便很抱歉，會盡快到。"
        )
    else:
        body = (
            f"老師、助教、各位組員好：\n\n"
            f"{when} 的「{commitment.title}」（{commitment.room} 教室）因{cause}，"
            f"目前所有交通方式都無法準時抵達。我會盡快趕到，若有需要請先開始。\n\n造成不便很抱歉。"
        )
    return {"to": list(DEFAULT_TO), "subject": subject, "body": body}
```

- [ ] **Step 5: 實作 loop.py**

`apps/api/campuspulse/core/loop.py`
```python
"""Perceive → plan → act → reflect. Deterministic code owns authorization and state; models only explain."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable

from campuspulse.core.actions import build_late_email
from campuspulse.core.campus import Campus
from campuspulse.core.models import (
    Commitment, IndoorGuidance, LatLng, Mode, Plan, PlanStatus, ProposedAction, RouteResult, Signal, SourceMode,
    TimelineEvent, Trigger,
)
from campuspulse.core.planner import MODE_LABEL, plan as make_plan
from campuspulse.core.triggers import apply_cooldown, detect_triggers
from campuspulse.providers.base import ProviderError
from campuspulse.providers.registry import Providers

RationaleFn = Callable[[Plan, Commitment, list[Trigger]], str]


class AgentLoop:
    def __init__(
        self, campus: Campus, providers: Providers, commitment: Commitment, origin: LatLng,
        rationale_fn: RationaleFn | None = None, dry_run: bool = True,
    ) -> None:
        self.campus = campus
        self.providers = providers
        self.commitment = commitment
        self.origin = origin
        self.rationale_fn = rationale_fn
        self.dry_run = dry_run
        self.reset()

    def reset(self) -> None:
        self.plan: Plan | None = None
        self.timeline: list[TimelineEvent] = []
        self.actions: list[ProposedAction] = []
        self.trigger_history: list[Trigger] = []
        self.last_triggers: list[Trigger] = []
        self.signals: dict[str, Signal] = {}
        self.routes: dict[Mode, RouteResult | None] = {}
        self.indoor: IndoorGuidance | None = None
        self.decisions_agent = 0
        self.decisions_user = 0
        self.clock: datetime | None = None
        self.user_state = "home"

    # ---- loop -----------------------------------------------------------------

    def run(self, now: datetime, user_state: str) -> None:
        self.clock = now
        self.user_state = user_state
        self._perceive(now)
        new_plan, triggers = self._plan(now, user_state)
        self._act(now, new_plan, triggers, user_state)
        self._reflect(now, user_state)

    def _perceive(self, now: datetime) -> None:
        signals: dict[str, Signal] = {}
        for kind, provider in self.providers.signals.items():
            try:
                signals[kind] = provider.fetch(now, {"commitment": self.commitment.model_dump(mode="json")})
            except ProviderError as e:
                signals[kind] = Signal(kind=kind, observed_at=now, value={}, source_mode=SourceMode.unavailable, confidence=0.0)  # type: ignore[arg-type]
        dest = self.campus.building(self.commitment.building_id).location
        routes: dict[Mode, RouteResult | None] = {}
        for mode in Mode:
            try:
                routes[mode] = self.providers.routing.route(self.origin, dest, mode, now)
            except ProviderError:
                routes[mode] = None
        self.signals, self.routes = signals, routes
        modes = sorted({s.source_mode.value for s in signals.values()} | {r.source_mode.value for r in routes.values() if r})
        unavailable = [k for k, s in signals.items() if s.source_mode == SourceMode.unavailable]
        detail = "四種路線與五種訊號已讀取" + (f"；不可用：{', '.join(unavailable)}" if unavailable else "")
        self._log(now, "perceive", "讀取即時訊號與路線", detail, modes)

    def _plan(self, now: datetime, user_state: str) -> tuple[Plan, list[Trigger]]:
        new_plan = make_plan(self.commitment, self.origin, now, self.routes, self.signals, self.campus, user_state)
        triggers = apply_cooldown(detect_triggers(self.plan, new_plan, now), self.trigger_history, now)
        if self.rationale_fn is not None:
            try:
                new_plan.rationale = self.rationale_fn(new_plan, self.commitment, [t for t in triggers if t.material]) or new_plan.rationale
            except Exception:
                pass  # model text is optional; the template rationale stays
        chosen = MODE_LABEL[new_plan.selected.mode] if new_plan.selected else "無可行方案"
        self._log(now, "plan", f"比較四種方式，選擇：{chosen}", new_plan.rationale)
        return new_plan, triggers

    def _act(self, now: datetime, new_plan: Plan, triggers: list[Trigger], user_state: str) -> None:
        material = [t for t in triggers if t.material]
        self.trigger_history.extend(triggers)
        self.last_triggers = triggers
        if material:
            self.decisions_agent += new_plan.decisions_made + len(material)
            self._log(now, "act", "更新建議卡", "；".join(t.description for t in material))
        self.plan = new_plan
        if new_plan.status in (PlanStatus.late_risk, PlanStatus.no_feasible) and user_state == "home" and not self._pending("email"):
            draft = build_late_email(self.commitment, new_plan, self.signals)
            preview = self.providers.email.preview(**draft) if self.providers.email else draft
            action = ProposedAction(id=f"act-{uuid.uuid4().hex[:8]}", type="email", preview=preview, created_at=now)
            self.actions.append(action)
            self._log(now, "act", "提議寄信給助教與組員（需你確認）", f"收件：{', '.join(preview.get('to', []))}")

    def _reflect(self, now: datetime, user_state: str) -> None:
        if user_state == "arrived_building":
            try:
                self.indoor = self.providers.indoor.locate(self.commitment.building_id, self.commitment.room) if self.providers.indoor else None
            except ProviderError:
                self.indoor = None
            self._log(now, "reflect", "已到大樓，切換教室導引", self.indoor.instructions if self.indoor else "此棟樓尚無平面圖")
            return
        nxt = self.plan.next_check_at.strftime("%H:%M") if self.plan and self.plan.next_check_at else "--:--"
        self._log(now, "reflect", f"下次檢查 {nxt}", f"你目前狀態：{user_state}")

    # ---- actions --------------------------------------------------------------

    def _pending(self, action_type: str) -> bool:
        return any(a.type == action_type and a.state == "proposed" for a in self.actions)

    def _find(self, action_id: str) -> ProposedAction:
        for a in self.actions:
            if a.id == action_id:
                return a
        raise KeyError(action_id)

    def confirm_action(self, action_id: str, now: datetime) -> ProposedAction:
        a = self._find(action_id)
        if a.state != "proposed":
            return a
        a.state = "confirmed"
        if a.type == "email" and self.providers.email:
            receipt = self.providers.email.send(a.preview)
            a.state = "executed_dry_run" if (self.dry_run or receipt.get("status") == "dry_run") else "confirmed"
        a.updated_at = now
        self.decisions_user += 1
        self._log(now, "act", "你確認寄信", "dry-run：未真的寄出" if a.state == "executed_dry_run" else "已寄出")
        return a

    def reject_action(self, action_id: str, now: datetime) -> ProposedAction:
        a = self._find(action_id)
        if a.state == "proposed":
            a.state = "rejected"
            a.updated_at = now
            self.decisions_user += 1
            self._log(now, "act", "你拒絕寄信", "")
        return a

    # ---- helpers --------------------------------------------------------------

    def _log(self, at: datetime, phase: str, title: str, detail: str = "", source_modes: list[str] | None = None) -> None:
        self.timeline.append(TimelineEvent(at=at, phase=phase, title=title, detail=detail, source_modes=source_modes or []))  # type: ignore[arg-type]

    def snapshot(self) -> dict[str, Any]:
        b = self.campus.building(self.commitment.building_id)
        return {
            "clock": self.clock.isoformat() if self.clock else None,
            "user_state": self.user_state,
            "commitment": self.commitment.model_dump(mode="json"),
            "origin": self.origin.model_dump(),
            "building": {"id": b.id, "name": b.name, "campus": b.campus, "location": b.location.model_dump()},
            "plan": self.plan.model_dump(mode="json") if self.plan else None,
            "signals": {k: s.model_dump(mode="json") for k, s in self.signals.items()},
            "routes_source": {m.value: (r.source_mode.value if r else "unavailable") for m, r in self.routes.items()},
            "timeline": [e.model_dump(mode="json") for e in self.timeline],
            "triggers": [t.model_dump(mode="json") for t in self.last_triggers],
            "actions": [a.model_dump(mode="json") for a in self.actions],
            "decisions": {"agent": self.decisions_agent, "user": self.decisions_user},
            "indoor": self.indoor.model_dump(mode="json") if self.indoor else None,
            "providers": self.providers.modes(),
        }
```

- [ ] **Step 6: 實作 scenario runner**

`apps/api/campuspulse/scenario/__init__.py`：空檔。

`apps/api/campuspulse/scenario/runner.py`
```python
"""Fixture clock. Drives the loop through a JSON timeline; inject() overrides signals at the current time."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from campuspulse.core.loop import AgentLoop
from campuspulse.core.models import Commitment, LatLng
from campuspulse.providers.fixture_store import FixtureStore
from campuspulse.settings import API_ROOT

SCENARIO_DIR = API_ROOT / "fixtures" / "scenarios"


class ScenarioStep(BaseModel):
    at: datetime
    user_state: str = "home"
    signals: dict[str, dict[str, Any]] = Field(default_factory=dict)
    note: str = ""


class Scenario(BaseModel):
    id: str
    title: str
    commitment: Commitment
    origin: LatLng
    steps: list[ScenarioStep]

    @classmethod
    def load(cls, path: Path) -> "Scenario":
        with path.open(encoding="utf-8") as f:
            return cls.model_validate(json.load(f))


class ScenarioRunner:
    def __init__(self, scenario: Scenario, loop: AgentLoop, store: FixtureStore) -> None:
        self.scenario = scenario
        self.loop = loop
        self.store = store
        self.index = -1

    def reset(self) -> dict[str, Any]:
        self.loop.reset()
        self.index = 0
        self._apply(self.scenario.steps[0])
        return self.snapshot()

    def step(self) -> dict[str, Any]:
        if self.index < 0:
            return self.reset()
        if self.index < len(self.scenario.steps) - 1:
            self.index += 1
            self._apply(self.scenario.steps[self.index])
        return self.snapshot()

    def inject(self, overrides: dict[str, dict[str, Any]]) -> dict[str, Any]:
        if self.index < 0:
            self.reset()
        for kind, patch in overrides.items():
            self.store.update(kind, patch)
        current = self.scenario.steps[self.index]
        self.loop.run(self.loop.clock or current.at, self.loop.user_state or current.user_state)
        return self.snapshot()

    def _apply(self, step: ScenarioStep) -> None:
        self.store.set_all(step.signals, step.at)
        self.loop.run(step.at, step.user_state)

    def snapshot(self) -> dict[str, Any]:
        snap = self.loop.snapshot()
        step = self.scenario.steps[self.index] if self.index >= 0 else None
        snap.update({
            "scenario_id": self.scenario.id,
            "scenario_title": self.scenario.title,
            "step_index": self.index,
            "step_count": len(self.scenario.steps),
            "step_note": step.note if step else "",
        })
        return snap
```

- [ ] **Step 7: 跑測試確認通過**

Run: `pytest tests/test_scenario.py -v`
Expected: PASS（6 tests）。全套：`pytest -q` 全綠。

- [ ] **Step 8: Commit**

```powershell
git add apps/api/campuspulse/core/actions.py apps/api/campuspulse/core/loop.py apps/api/campuspulse/scenario apps/api/fixtures/scenarios apps/api/tests/test_scenario.py
git commit -m "feat(core): add agent loop, late-email action builder and scenario runner"
```

---

### Task 8: HTTP API

**Files:**
- Create: `apps/api/campuspulse/api/__init__.py`, `routes_state.py`, `routes_scenario.py`, `routes_actions.py`, `routes_plan.py`
- Modify: `apps/api/campuspulse/main.py`
- Test: `apps/api/tests/test_api.py`

**Interfaces:**
- Consumes: Task 7 `ScenarioRunner`, `AgentLoop`, `Scenario`；Task 4 `build_providers`, `FixtureStore`。
- Produces: `create_app(settings=None, scenario_path=None) -> FastAPI`，`app.state.runner: ScenarioRunner`；端點如 spec：`GET /api/health`、`GET /api/state`、`POST /api/scenario/reset|step|inject`、`POST /api/actions/{id}/confirm|reject`、`POST /api/plan`。

- [ ] **Step 1: 寫失敗測試**

`apps/api/tests/test_api.py`
```python
from fastapi.testclient import TestClient

from campuspulse.main import create_app
from campuspulse.settings import Settings


def _client():
    return TestClient(create_app(Settings(provider_mode="fixture")))


def test_state_after_startup_is_step_zero():
    c = _client()
    s = c.get("/api/state").json()
    assert s["step_index"] == 0 and s["plan"]["selected"]["mode"] == "scooter"


def test_scenario_step_and_reset():
    c = _client()
    assert c.post("/api/scenario/step").json()["plan"]["selected"]["mode"] == "transit"
    assert c.post("/api/scenario/reset").json()["step_index"] == 0


def test_inject_overrides_signal():
    c = _client()
    s = c.post("/api/scenario/inject", json={"bike": {"available": 0}}).json()
    assert next(o for o in s["plan"]["options"] if o["mode"] == "bike")["feasible"] is False


def test_confirm_action_is_dry_run():
    c = _client()
    c.post("/api/scenario/step"); s = c.post("/api/scenario/step").json()
    action_id = s["actions"][0]["id"]
    out = c.post(f"/api/actions/{action_id}/confirm").json()
    assert out["action"]["state"] == "executed_dry_run"
    assert c.post("/api/actions/nope/confirm").status_code == 404


def test_plan_endpoint_runs_planner_directly():
    c = _client()
    body = {
        "commitment": {"id": "x", "title": "普通課", "start": "2026-09-23T09:00:00+08:00", "building_id": "csie", "room": "4263", "importance": "normal"},
        "origin": {"lat": 22.9905, "lng": 120.2280},
        "now": "2026-09-23T07:50:00+08:00",
        "signals": {"rain": {"mm_per_hour": 0, "forecast_next_hour_mm": 0}, "flood": {"alerts": []},
                    "bike": {"origin_station_id": "yb-dongning", "available": 3, "dest_station_id": "yb-ncku-north", "docks": 2, "next_station_id": "yb-ncku-east", "next_station_docks": 9},
                    "transit": {"route_name": "5", "next_eta_min": 6, "board_stop_id": "bs-dongning", "alight_stop_id": "bs-ncku-north"},
                    "parking": {"lots": {"lot-a": {"free": 1}, "lot-b": {"free": 1}, "lot-c": {"free": 1}}}},
    }
    r = c.post("/api/plan", json=body)
    assert r.status_code == 200 and r.json()["status"] == "ok" and len(r.json()["options"]) == 4
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_api.py -v`
Expected: FAIL `404` on `/api/state`

- [ ] **Step 3: 實作路由**

`apps/api/campuspulse/api/__init__.py`：空檔。

`apps/api/campuspulse/api/routes_state.py`
```python
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["state"])


@router.get("/state")
def get_state(request: Request) -> dict:
    return request.app.state.runner.snapshot()
```

`apps/api/campuspulse/api/routes_scenario.py`
```python
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/scenario", tags=["scenario"])


@router.post("/reset")
def reset(request: Request) -> dict:
    return request.app.state.runner.reset()


@router.post("/step")
def step(request: Request) -> dict:
    return request.app.state.runner.step()


@router.post("/inject")
def inject(request: Request, overrides: dict[str, dict[str, Any]]) -> dict:
    return request.app.state.runner.inject(overrides)
```

`apps/api/campuspulse/api/routes_actions.py`
```python
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.post("/{action_id}/confirm")
def confirm(request: Request, action_id: str) -> dict:
    runner = request.app.state.runner
    try:
        action = runner.loop.confirm_action(action_id, runner.loop.clock)
    except KeyError:
        raise HTTPException(status_code=404, detail="action not found")
    return {"action": action.model_dump(mode="json"), "state": runner.snapshot()}


@router.post("/{action_id}/reject")
def reject(request: Request, action_id: str) -> dict:
    runner = request.app.state.runner
    try:
        action = runner.loop.reject_action(action_id, runner.loop.clock)
    except KeyError:
        raise HTTPException(status_code=404, detail="action not found")
    return {"action": action.model_dump(mode="json"), "state": runner.snapshot()}
```

`apps/api/campuspulse/api/routes_plan.py`
```python
"""Direct planner access so teammates can test their signals without the scenario."""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from campuspulse.core.models import Commitment, LatLng, Mode, Plan, Signal, SourceMode
from campuspulse.core.planner import plan as make_plan
from campuspulse.providers.base import ProviderError

router = APIRouter(prefix="/api", tags=["plan"])


class PlanRequest(BaseModel):
    commitment: Commitment
    origin: LatLng
    now: datetime
    signals: dict[str, dict[str, Any]] = Field(default_factory=dict)
    user_state: str = "home"


@router.post("/plan", response_model=Plan)
def post_plan(request: Request, body: PlanRequest) -> Plan:
    runner = request.app.state.runner
    campus, providers = runner.loop.campus, runner.loop.providers
    dest = campus.building(body.commitment.building_id).location
    routes = {}
    for mode in Mode:
        try:
            routes[mode] = providers.routing.route(body.origin, dest, mode, body.now)
        except ProviderError:
            routes[mode] = None
    signals = {k: Signal(kind=k, observed_at=body.now, value=v, source_mode=SourceMode.fixture) for k, v in body.signals.items()}  # type: ignore[arg-type]
    return make_plan(body.commitment, body.origin, body.now, routes, signals, campus, body.user_state)
```

- [ ] **Step 4: 擴充 main.py**

`apps/api/campuspulse/main.py`（整檔取代）
```python
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from campuspulse.api import routes_actions, routes_plan, routes_scenario, routes_state
from campuspulse.core.campus import Campus
from campuspulse.core.loop import AgentLoop
from campuspulse.providers.fixture_store import FixtureStore
from campuspulse.providers.registry import build_providers
from campuspulse.scenario.runner import SCENARIO_DIR, Scenario, ScenarioRunner
from campuspulse.settings import Settings, load_settings, missing_live_credentials

DEFAULT_SCENARIO = SCENARIO_DIR / "ncku-wed-0900.json"


def build_runner(settings: Settings, scenario_path: Path = DEFAULT_SCENARIO) -> ScenarioRunner:
    campus = Campus.load()
    store = FixtureStore()
    providers = build_providers(settings, store, campus)
    scenario = Scenario.load(scenario_path)
    loop = AgentLoop(campus, providers, scenario.commitment, scenario.origin, dry_run=settings.dry_run)
    runner = ScenarioRunner(scenario, loop, store)
    runner.reset()
    return runner


def create_app(settings: Settings | None = None, scenario_path: Path = DEFAULT_SCENARIO) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="CampusPulse API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.runner = build_runner(settings, scenario_path)

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "provider_mode": settings.provider_mode,
            "dry_run": settings.dry_run,
            "missing_credentials": missing_live_credentials(settings),
            "providers": app.state.runner.loop.providers.modes(),
        }

    app.include_router(routes_state.router)
    app.include_router(routes_scenario.router)
    app.include_router(routes_actions.router)
    app.include_router(routes_plan.router)
    return app


app = create_app()
```

- [ ] **Step 5: 跑測試確認通過**

Run: `pytest -q`
Expected: 全綠。

- [ ] **Step 6: 手動煙霧**

Run: `uvicorn campuspulse.main:app --reload --port 8000`；`curl -X POST http://localhost:8000/api/scenario/step`，看到 `"selected": {"mode": "transit"...`。

- [ ] **Step 7: Commit**

```powershell
git add apps/api/campuspulse/api apps/api/campuspulse/main.py apps/api/tests/test_api.py
git commit -m "feat(api): expose state, scenario, actions and plan endpoints"
```

---

### Task 9: Google Routes live provider

**Files:**
- Create: `apps/api/campuspulse/providers/routing/polyline.py`, `apps/api/campuspulse/providers/routing/google_routes.py`
- Modify: `apps/api/campuspulse/providers/registry.py`（設定 `LIVE_ROUTING_CLASS`）
- Test: `apps/api/tests/test_google_routes.py`, `apps/api/tests/test_registry.py`

**Interfaces:**
- Consumes: Task 4 `RoutingProvider`, `ProviderError`；Task 3 `campus.corridor_ids_in_text`。
- Produces: `decode_polyline(encoded: str) -> list[LatLng]`；`GoogleRoutesProvider(settings, campus, client: httpx.Client | None = None)`，`IMPLEMENTED = True`，`.route(...)` 回 `RouteResult(source_mode=live, mode_proxy="DRIVE" for scooter, alternative=第二條路線)`。
- 錯誤對應：連線失敗 → `unavailable`；401/403 → `unauthorized`；429 → `rate_limited`；其他非 200 或無 `routes` → `invalid_response` / `unavailable`。

- [ ] **Step 1: 寫失敗測試**

`apps/api/tests/test_google_routes.py`
```python
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from campuspulse.core.campus import Campus
from campuspulse.core.models import LatLng, Mode, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.providers.routing.google_routes import GoogleRoutesProvider
from campuspulse.providers.routing.polyline import decode_polyline
from campuspulse.settings import Settings

TPE = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 7, 50, tzinfo=TPE)
O, D = LatLng(lat=22.9905, lng=120.2280), LatLng(lat=22.9997, lng=120.2220)

RESPONSE = {
    "routes": [
        {"duration": "720s", "distanceMeters": 3200, "description": "小東路",
         "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"},
         "legs": [{"steps": [{"navigationInstruction": {"instructions": "Turn left onto 小東路"}}]}]},
        {"duration": "900s", "distanceMeters": 3900, "description": "長榮路",
         "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"},
         "legs": [{"steps": [{"navigationInstruction": {"instructions": "Head north on Changrong Rd"}}]}]},
    ]
}


def _provider(handler):
    settings = Settings(provider_mode="auto", google_maps_api_key="test-key")
    return GoogleRoutesProvider(settings, Campus.load(), client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_decode_polyline_matches_google_example():
    pts = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert [(round(p.lat, 5), round(p.lng, 5)) for p in pts] == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def test_scooter_uses_drive_proxy_and_maps_corridors():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        seen["mask"] = req.headers.get("X-Goog-FieldMask")
        assert "test-key" == req.headers.get("X-Goog-Api-Key")
        return httpx.Response(200, json=RESPONSE)

    r = _provider(handler).route(O, D, Mode.scooter, NOW)
    assert seen["body"]["travelMode"] == "DRIVE" and seen["body"]["routeModifiers"]["avoidHighways"] is True
    assert "routes.duration" in seen["mask"]
    assert r.source_mode == SourceMode.live and r.mode_proxy == "DRIVE"
    assert r.duration_min == 12 and r.distance_m == 3200 and r.corridor_ids == ["xiaodong-rd"]
    assert r.alternative is not None and r.alternative.corridor_ids == ["changrong-rd"]
    assert len(r.polyline) == 3


def test_transit_has_no_alternative_flag_and_no_route_modifiers():
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["travelMode"] == "TRANSIT" and "routeModifiers" not in body and body.get("computeAlternativeRoutes") is False
        return httpx.Response(200, json=RESPONSE)

    r = _provider(handler).route(O, D, Mode.transit, NOW)
    assert r.mode == Mode.transit and r.mode_proxy is None


@pytest.mark.parametrize("status,code", [(403, "unauthorized"), (401, "unauthorized"), (429, "rate_limited"), (500, "invalid_response")])
def test_http_errors_map_to_provider_errors(status, code):
    p = _provider(lambda req: httpx.Response(status, json={"error": {"message": "x"}}))
    with pytest.raises(ProviderError) as e:
        p.route(O, D, Mode.walk, NOW)
    assert e.value.code == code


def test_empty_routes_is_unavailable():
    p = _provider(lambda req: httpx.Response(200, json={}))
    with pytest.raises(ProviderError) as e:
        p.route(O, D, Mode.bike, NOW)
    assert e.value.code == "unavailable"
```

`apps/api/tests/test_registry.py`
```python
from campuspulse.core.campus import Campus
from campuspulse.providers.fixture_store import FixtureStore
from campuspulse.providers.registry import build_providers
from campuspulse.providers.routing.fixture import FixtureRoutingProvider
from campuspulse.providers.routing.google_routes import GoogleRoutesProvider
from campuspulse.settings import Settings


def test_auto_mode_with_key_uses_google_routes():
    p = build_providers(Settings(provider_mode="auto", google_maps_api_key="k"), FixtureStore(), Campus.load())
    assert isinstance(p.routing, GoogleRoutesProvider)
    assert all(v == "fixture" for k, v in p.modes().items() if k != "routing")


def test_auto_mode_without_key_falls_back_to_fixture():
    p = build_providers(Settings(provider_mode="auto"), FixtureStore(), Campus.load())
    assert isinstance(p.routing, FixtureRoutingProvider)


def test_fixture_mode_ignores_keys():
    p = build_providers(Settings(provider_mode="fixture", google_maps_api_key="k"), FixtureStore(), Campus.load())
    assert isinstance(p.routing, FixtureRoutingProvider)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_google_routes.py tests/test_registry.py -v`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: 實作 polyline 與 provider**

`apps/api/campuspulse/providers/routing/polyline.py`
```python
"""Google encoded polyline decoder."""
from __future__ import annotations

from campuspulse.core.models import LatLng


def decode_polyline(encoded: str) -> list[LatLng]:
    points: list[LatLng] = []
    index = lat = lng = 0
    while index < len(encoded):
        for is_lat in (True, False):
            result = shift = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lat:
                lat += delta
            else:
                lng += delta
        points.append(LatLng(lat=lat / 1e5, lng=lng / 1e5))
    return points
```

`apps/api/campuspulse/providers/routing/google_routes.py`
```python
"""Google Routes API (computeRoutes). Scooter uses DRIVE as a proxy; TWO_WHEELER is not offered in Taiwan."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from campuspulse.core.campus import Campus
from campuspulse.core.models import LatLng, Mode, RouteResult, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.providers.routing.polyline import decode_polyline
from campuspulse.settings import Settings

URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = ",".join([
    "routes.duration",
    "routes.distanceMeters",
    "routes.polyline.encodedPolyline",
    "routes.description",
    "routes.legs.steps.navigationInstruction.instructions",
])
MODE_MAP = {Mode.walk: "WALK", Mode.bike: "BICYCLE", Mode.scooter: "DRIVE", Mode.transit: "TRANSIT"}


class GoogleRoutesProvider:
    IMPLEMENTED = True
    name = "google-routes"
    source_mode = SourceMode.live

    def __init__(self, settings: Settings, campus: Campus, client: httpx.Client | None = None, timeout: float = 8.0) -> None:
        self._key = settings.google_maps_api_key
        self.campus = campus
        self.client = client or httpx.Client(timeout=timeout)

    def _body(self, origin: LatLng, destination: LatLng, mode: Mode, depart_at: datetime) -> dict:
        body: dict = {
            "origin": {"location": {"latLng": {"latitude": origin.lat, "longitude": origin.lng}}},
            "destination": {"location": {"latLng": {"latitude": destination.lat, "longitude": destination.lng}}},
            "travelMode": MODE_MAP[mode],
            "computeAlternativeRoutes": mode != Mode.transit,
            "languageCode": "zh-TW",
            "units": "METRIC",
        }
        if mode == Mode.scooter:
            body["routeModifiers"] = {"avoidHighways": True, "avoidTolls": True}
        if mode == Mode.transit and depart_at > datetime.now(timezone.utc):
            body["departureTime"] = depart_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return body

    def _parse(self, raw: dict, mode: Mode) -> RouteResult:
        seconds = float(str(raw.get("duration", "0s")).rstrip("s") or 0)
        text = " ".join(
            step.get("navigationInstruction", {}).get("instructions", "")
            for leg in raw.get("legs", []) for step in leg.get("steps", [])
        )
        return RouteResult(
            mode=mode,
            duration_min=round(seconds / 60, 1),
            distance_m=float(raw.get("distanceMeters", 0)),
            polyline=decode_polyline(raw.get("polyline", {}).get("encodedPolyline", "")),
            summary=raw.get("description", ""),
            corridor_ids=self.campus.corridor_ids_in_text(text + " " + raw.get("description", "")),
            source_mode=SourceMode.live,
            mode_proxy="DRIVE" if mode == Mode.scooter else None,
        )

    def route(self, origin: LatLng, destination: LatLng, mode: Mode, depart_at: datetime) -> RouteResult:
        headers = {"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": FIELD_MASK, "Content-Type": "application/json"}
        try:
            resp = self.client.post(URL, json=self._body(origin, destination, mode, depart_at), headers=headers)
        except httpx.HTTPError as e:
            raise ProviderError("unavailable", f"routes api: {type(e).__name__}") from e
        if resp.status_code in (401, 403):
            raise ProviderError("unauthorized", "routes api rejected the key")
        if resp.status_code == 429:
            raise ProviderError("rate_limited", "routes api rate limited")
        if resp.status_code != 200:
            raise ProviderError("invalid_response", f"routes api status {resp.status_code}")
        routes = (resp.json() or {}).get("routes") or []
        if not routes:
            raise ProviderError("unavailable", f"no {MODE_MAP[mode]} route returned")
        primary = self._parse(routes[0], mode)
        if len(routes) > 1:
            primary.alternative = self._parse(routes[1], mode)
        return primary
```

- [ ] **Step 4: 在 registry 註冊**

`apps/api/campuspulse/providers/registry.py`：在 `from campuspulse.settings import Settings` 之後加

```python
from campuspulse.providers.routing.google_routes import GoogleRoutesProvider
```

並把 `LIVE_ROUTING_CLASS: tuple[type, tuple[str, ...]] | None = None` 改成

```python
LIVE_ROUTING_CLASS: tuple[type, tuple[str, ...]] | None = (GoogleRoutesProvider, ("google_maps_api_key",))
```

- [ ] **Step 5: 跑測試確認通過**

Run: `pytest -q`
Expected: 全綠。

- [ ] **Step 6: 真 key 驗證（有 GCP 專案時）**

在 `apps/api/.env` 填 `PROVIDER_MODE=auto` 與 `GOOGLE_MAPS_API_KEY`，啟動後 `GET /api/health` 的 `providers.routing` 應為 `live`；`GET /api/state` 的 `routes_source` 四模式標 `live`。若 `BICYCLE` 回 `unavailable`，在 `docs/api-and-data.md` 記錄「台灣單車模式不可用，fixture 代替」。**不要把 key 貼進任何檔案或聊天。**

- [ ] **Step 7: Commit**

```powershell
git add apps/api/campuspulse/providers/routing apps/api/campuspulse/providers/registry.py apps/api/tests/test_google_routes.py apps/api/tests/test_registry.py
git commit -m "feat(routing): add Google Routes live provider with fixture fallback"
```

---

### Task 10: Gemini client、決策說明、課表辨識空殼

**Files:**
- Create: `apps/api/campuspulse/ai/__init__.py`, `gemini.py`, `rationale.py`, `timetable.py`
- Modify: `apps/api/campuspulse/main.py`（`build_runner` 注入 `rationale_fn`）
- Test: `apps/api/tests/test_ai.py`

**Interfaces:**
- Consumes: Task 5 `build_rationale`；Task 7 `RationaleFn`。
- Produces: `GeminiClient(settings)`，`.available: bool`，`.generate_text(prompt, model=None, parts=None) -> str | None`，`.generate_json(prompt, schema: type[BaseModel], model=None, parts=None) -> BaseModel | None`（無 key 或任何例外都回 None，絕不拋錯）；`make_rationale_fn(client) -> RationaleFn`；`TimetableExtraction(commitments, confidence, notes)`；`extract_commitments(image_bytes, mime_type, client, now) -> TimetableExtraction`。

- [ ] **Step 1: 寫失敗測試**

`apps/api/tests/test_ai.py`
```python
from datetime import datetime, timedelta, timezone

from campuspulse.ai.gemini import GeminiClient
from campuspulse.ai.rationale import make_rationale_fn
from campuspulse.ai.timetable import extract_commitments
from campuspulse.core.models import Commitment, Mode, Plan, TravelOption
from campuspulse.settings import Settings

TPE = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 7, 50, tzinfo=TPE)


def _plan():
    opt = TravelOption(mode=Mode.scooter, feasible=True, on_time=True, depart_at=NOW, arrive_at=NOW + timedelta(minutes=16))
    return Plan(commitment_id="c1", generated_at=NOW, selected=opt, options=[opt], rationale="模板說明")


def _commitment():
    return Commitment(id="c1", title="小組報告", start=NOW + timedelta(minutes=70), building_id="csie", room="4263")


def test_client_without_key_is_unavailable_and_returns_none():
    c = GeminiClient(Settings())
    assert c.available is False
    assert c.generate_text("hi") is None


def test_rationale_falls_back_to_template_without_key():
    fn = make_rationale_fn(GeminiClient(Settings()))
    assert fn(_plan(), _commitment(), []) == "模板說明"


def test_rationale_uses_model_text_when_available(monkeypatch):
    client = GeminiClient(Settings(gemini_api_key="k"))
    monkeypatch.setattr(client, "generate_text", lambda prompt, model=None, parts=None: "模型說明")
    assert make_rationale_fn(client)(_plan(), _commitment(), []) == "模型說明"


def test_rationale_keeps_template_when_model_returns_none(monkeypatch):
    client = GeminiClient(Settings(gemini_api_key="k"))
    monkeypatch.setattr(client, "generate_text", lambda prompt, model=None, parts=None: None)
    assert make_rationale_fn(client)(_plan(), _commitment(), []) == "模板說明"


def test_timetable_shell_returns_fixture():
    out = extract_commitments(b"", "image/png", GeminiClient(Settings()), NOW)
    assert len(out.commitments) == 1 and out.confidence == 0.0 and "fixture" in out.notes
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_ai.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'campuspulse.ai'`

- [ ] **Step 3: 實作 ai/**

`apps/api/campuspulse/ai/__init__.py`：空檔。

`apps/api/campuspulse/ai/gemini.py`
```python
"""Thin Gemini wrapper. Returns None on any failure so callers always have a deterministic fallback."""
from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from campuspulse.settings import Settings

T = TypeVar("T", bound=BaseModel)


class GeminiClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any = None

    @property
    def available(self) -> bool:
        return bool(self.settings.gemini_api_key)

    def _get(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._client

    def generate_text(self, prompt: str, model: str | None = None, parts: list[Any] | None = None) -> str | None:
        if not self.available:
            return None
        try:
            resp = self._get().models.generate_content(
                model=model or self.settings.gemini_flash_model, contents=[*(parts or []), prompt],
            )
            text = (getattr(resp, "text", None) or "").strip()
            return text or None
        except Exception:
            return None

    def generate_json(self, prompt: str, schema: type[T], model: str | None = None, parts: list[Any] | None = None) -> T | None:
        if not self.available:
            return None
        try:
            from google.genai import types

            resp = self._get().models.generate_content(
                model=model or self.settings.gemini_flash_model,
                contents=[*(parts or []), prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema),
            )
            return schema.model_validate_json(resp.text or "")
        except Exception:
            return None
```

`apps/api/campuspulse/ai/rationale.py`
```python
"""Two-sentence Chinese explanation of a plan. Model text is optional; the template is the contract."""
from __future__ import annotations

import json

from campuspulse.ai.gemini import GeminiClient
from campuspulse.core.models import Commitment, Plan, Trigger
from campuspulse.core.planner import MODE_LABEL, build_rationale

PROMPT = (
    "你是大學生的通勤助理。用繁體中文、最多兩句、不用技術名詞，向學生說明下面這個決策：先說該怎麼做，再說為什麼。"
    "只能根據給定資料，不可自己假設交通時間或天氣。\n\n決策資料：\n{payload}"
)


def _payload(plan: Plan, commitment: Commitment, triggers: list[Trigger]) -> str:
    s = plan.selected
    data = {
        "課程": commitment.title,
        "上課時間": commitment.start.strftime("%H:%M"),
        "重要度": commitment.importance.value,
        "狀態": plan.status.value,
        "建議": None if s is None else {
            "方式": MODE_LABEL[s.mode],
            "出門": s.depart_at.strftime("%H:%M") if s.depart_at else None,
            "到達": s.arrive_at.strftime("%H:%M") if s.arrive_at else None,
            "最後一個決定": s.last_decision.label if s.last_decision else None,
            "原因": s.last_decision.reason if s.last_decision else None,
            "緩衝分鐘": s.slack_min,
        },
        "其他方式": [{"方式": MODE_LABEL[o.mode], "可行": o.feasible, "原因": o.reasons} for o in plan.options if s is None or o.mode != s.mode],
        "剛發生的變化": [t.description for t in triggers],
    }
    return json.dumps(data, ensure_ascii=False)


def make_rationale_fn(client: GeminiClient):
    def fn(plan: Plan, commitment: Commitment, triggers: list[Trigger]) -> str:
        template = plan.rationale or build_rationale(plan, commitment)
        if not client.available:
            return template
        text = client.generate_text(PROMPT.format(payload=_payload(plan, commitment, triggers)))
        return text or template

    return fn
```

`apps/api/campuspulse/ai/timetable.py`
```python
"""Timetable image -> commitments. Shell: owner C wires the Gemini Flash multimodal call."""
from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from campuspulse.ai.gemini import GeminiClient
from campuspulse.core.models import Commitment, Importance


class TimetableExtraction(BaseModel):
    commitments: list[Commitment] = Field(default_factory=list)
    confidence: float = 0.0
    notes: str = ""


PROMPT = (
    "這是一張台灣大學生的課表截圖。抽出每堂課的：課名、星期、開始時間、教室編號、建築名稱。"
    "教室編號通常是 3–4 位數字或字母加數字。若看不清楚，該欄位留空並降低 confidence。"
)


def extract_commitments(image_bytes: bytes, mime_type: str, client: GeminiClient, now: datetime) -> TimetableExtraction:
    if client.available and image_bytes:
        # TODO(live, owner C): build parts with types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        # call client.generate_json(PROMPT, TimetableExtraction, parts=parts), then map building names to
        # campus building ids and next occurrence dates. Return that result instead of the fixture below.
        pass
    next_wed = now + timedelta(days=(2 - now.weekday()) % 7 or 7)
    start = next_wed.replace(hour=9, minute=0, second=0, microsecond=0)
    return TimetableExtraction(
        commitments=[Commitment(id="c-fixture-timetable", title="資料庫系統 小組報告", start=start, building_id="csie", room="4263", importance=Importance.high, source="timetable-fixture", confirmed=False)],
        confidence=0.0,
        notes="fixture: 課表辨識尚未接上（owner C）",
    )
```

- [ ] **Step 4: 注入 rationale_fn**

`apps/api/campuspulse/main.py`：在 import 區加

```python
from campuspulse.ai.gemini import GeminiClient
from campuspulse.ai.rationale import make_rationale_fn
```

`build_runner` 內把

```python
    loop = AgentLoop(campus, providers, scenario.commitment, scenario.origin, dry_run=settings.dry_run)
```

改成

```python
    rationale_fn = make_rationale_fn(GeminiClient(settings))
    loop = AgentLoop(campus, providers, scenario.commitment, scenario.origin, rationale_fn=rationale_fn, dry_run=settings.dry_run)
```

- [ ] **Step 5: 跑測試確認通過**

Run: `pytest -q`
Expected: 全綠。

- [ ] **Step 6: Commit**

```powershell
git add apps/api/campuspulse/ai apps/api/campuspulse/main.py apps/api/tests/test_ai.py
git commit -m "feat(ai): add Gemini client, plan rationale and timetable extraction shell"
```

---

### Task 11: Live provider 空殼

**Files:**
- Create: `apps/api/campuspulse/providers/weather/cwa.py`, `flood/wra.py`, `bike/tdx_youbike.py`, `transit/tdx_bus.py`, `indoor/floorplan_gemini.py`, `email/gmail.py`, `calendar/google_calendar.py`
- Modify: `apps/api/campuspulse/providers/registry.py`（填 `LIVE_SIGNAL_CLASSES`）
- Test: 追加到 `apps/api/tests/test_registry.py`

**Interfaces:**
- 每個空殼：`IMPLEMENTED = False`、`kind`、`source_mode = SourceMode.live`、`__init__(settings, campus)`、`fetch()` 拋 `ProviderError("not_implemented", "TODO(live, owner X): ...")`。接手者把 `IMPLEMENTED` 改 `True` 並實作 `fetch`，registry 就會在 `PROVIDER_MODE=auto` 且 key 齊全時選用。

- [ ] **Step 1: 追加失敗測試**

在 `apps/api/tests/test_registry.py` 末尾追加：

```python
def test_signal_shells_stay_fixture_until_implemented():
    s = Settings(provider_mode="auto", google_maps_api_key="k", cwa_api_key="k", wra_api_key="k", tdx_client_id="k", tdx_client_secret="k")
    p = build_providers(s, FixtureStore(), Campus.load())
    assert all(v == "fixture" for k, v in p.modes().items() if k in ("rain", "flood", "bike", "transit", "parking"))


def test_implemented_shell_is_selected(monkeypatch):
    from campuspulse.providers.weather.cwa import CwaWeatherProvider

    monkeypatch.setattr(CwaWeatherProvider, "IMPLEMENTED", True)
    p = build_providers(Settings(provider_mode="auto", cwa_api_key="k"), FixtureStore(), Campus.load())
    assert isinstance(p.signals["rain"], CwaWeatherProvider) and p.modes()["rain"] == "live"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_registry.py -v`
Expected: FAIL `ModuleNotFoundError: campuspulse.providers.weather.cwa`

- [ ] **Step 3: 寫空殼**

`apps/api/campuspulse/providers/weather/cwa.py`
```python
"""TODO(live, owner B): 中央氣象署開放資料。
建議來源：O-A0001-001（自動氣象站即時雨量）取最近測站的 HOUR_RAIN；F-C0032-001 或鄉鎮預報取下一小時降雨。
回傳 Signal(kind="rain", value={"mm_per_hour": float, "forecast_next_hour_mm": float}, source_mode=live, observed_at=資料時間)。
逾時 8 秒；資料時間超過 30 分鐘標 stale；失敗拋 ProviderError。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from campuspulse.core.campus import Campus
from campuspulse.core.models import Signal, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.settings import Settings


class CwaWeatherProvider:
    IMPLEMENTED = False
    kind = "rain"
    source_mode = SourceMode.live

    def __init__(self, settings: Settings, campus: Campus) -> None:
        self._key = settings.cwa_api_key
        self.campus = campus

    def fetch(self, at: datetime, context: dict[str, Any]) -> Signal:
        raise ProviderError("not_implemented", "TODO(live, owner B): CWA rain adapter")
```

`apps/api/campuspulse/providers/flood/wra.py`
```python
"""TODO(live, owner B): 水利署水資源物聯網（iot.wra.gov.tw）都市積淹水感測器。
把感測器座標對到 data/ncku/corridors.json 的走廊；水深 ≥ 10cm 為 warning、≥ 30cm 為 danger。
回傳 Signal(kind="flood", value={"alerts": [{"corridor_id", "level", "depth_cm"}]}, source_mode=live)。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from campuspulse.core.campus import Campus
from campuspulse.core.models import Signal, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.settings import Settings


class WraFloodProvider:
    IMPLEMENTED = False
    kind = "flood"
    source_mode = SourceMode.live

    def __init__(self, settings: Settings, campus: Campus) -> None:
        self._key = settings.wra_api_key
        self.campus = campus

    def fetch(self, at: datetime, context: dict[str, Any]) -> Signal:
        raise ProviderError("not_implemented", "TODO(live, owner B): WRA flood adapter")
```

`apps/api/campuspulse/providers/bike/tdx_youbike.py`
```python
"""TODO(live, owner B): TDX YouBike 台南即時站點（/v2/Bike/Availability/City/Tainan + /v2/Bike/Station/City/Tainan）。
先用 client_credentials 換 token（快取到過期前 60 秒）。以 data/ncku/bike_stations.json 的站名對應 TDX StationUID。
回傳 Signal(kind="bike", value={"origin_station_id", "available", "dest_station_id", "docks", "next_station_id", "next_station_docks"}, source_mode=live)。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from campuspulse.core.campus import Campus
from campuspulse.core.models import Signal, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.settings import Settings


class TdxYouBikeProvider:
    IMPLEMENTED = False
    kind = "bike"
    source_mode = SourceMode.live

    def __init__(self, settings: Settings, campus: Campus) -> None:
        self._client_id = settings.tdx_client_id
        self._client_secret = settings.tdx_client_secret
        self.campus = campus

    def fetch(self, at: datetime, context: dict[str, Any]) -> Signal:
        raise ProviderError("not_implemented", "TODO(live, owner B): TDX YouBike adapter")
```

`apps/api/campuspulse/providers/transit/tdx_bus.py`
```python
"""TODO(live, owner B): TDX 台南公車預估到站（/v2/Bus/EstimatedTimeOfArrival/City/Tainan/{RouteName}）。
以 data/ncku/bus_stops.json 的站名對應 StopUID；EstimateTime 秒 → next_eta_min。
回傳 Signal(kind="transit", value={"route_name", "next_eta_min", "board_stop_id", "alight_stop_id"}, source_mode=live)。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from campuspulse.core.campus import Campus
from campuspulse.core.models import Signal, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.settings import Settings


class TdxBusProvider:
    IMPLEMENTED = False
    kind = "transit"
    source_mode = SourceMode.live

    def __init__(self, settings: Settings, campus: Campus) -> None:
        self._client_id = settings.tdx_client_id
        self._client_secret = settings.tdx_client_secret
        self.campus = campus

    def fetch(self, at: datetime, context: dict[str, Any]) -> Signal:
        raise ProviderError("not_implemented", "TODO(live, owner B): TDX bus ETA adapter")
```

`apps/api/campuspulse/providers/indoor/floorplan_gemini.py`
```python
"""TODO(live, owner D): 用 Gemini 讀樓層平面圖（data/ncku/floorplans/<building_id>/<floor>.png）。
輸入建築、教室編號、平面圖影像；輸出 IndoorGuidance（樓層、翼、入口、走法、confidence）。
confidence < 0.6 時改回 fixture 指引並標 source_mode=stale。
"""
from __future__ import annotations

from campuspulse.ai.gemini import GeminiClient
from campuspulse.core.campus import Campus
from campuspulse.core.models import IndoorGuidance, SourceMode
from campuspulse.providers.base import ProviderError


class FloorplanGeminiIndoorProvider:
    IMPLEMENTED = False
    source_mode = SourceMode.live

    def __init__(self, client: GeminiClient, campus: Campus) -> None:
        self.client = client
        self.campus = campus

    def locate(self, building_id: str, room: str) -> IndoorGuidance:
        raise ProviderError("not_implemented", "TODO(live, owner D): floor-plan guidance")
```

`apps/api/campuspulse/providers/email/gmail.py`
```python
"""TODO(live, owner E): Gmail API。preview() 只組信；send() 只在 DRY_RUN=false 且 action 已 confirmed 時真寄。
需要 OAuth（gmail.send 最小 scope）。寄出後回 {"status": "sent", "message_id": ...}。
"""
from __future__ import annotations

from typing import Any

from campuspulse.providers.base import ProviderError
from campuspulse.settings import Settings


class GmailEmailProvider:
    IMPLEMENTED = False

    def __init__(self, settings: Settings) -> None:
        self.dry_run = settings.dry_run

    def preview(self, to: list[str], subject: str, body: str) -> dict[str, Any]:
        return {"to": to, "subject": subject, "body": body, "provider": "gmail"}

    def send(self, preview: dict[str, Any]) -> dict[str, Any]:
        if self.dry_run:
            return {"status": "dry_run", "to": preview.get("to", []), "subject": preview.get("subject", "")}
        raise ProviderError("not_implemented", "TODO(live, owner E): Gmail send")
```

`apps/api/campuspulse/providers/calendar/google_calendar.py`
```python
"""TODO(live, owner E): Google Calendar API。preview_change() 回將建立/更新的事件；execute_change() 需 idempotency key（用 commitment.id + 日期）。
"""
from __future__ import annotations

from typing import Any

from campuspulse.providers.base import ProviderError
from campuspulse.settings import Settings


class GoogleCalendarProvider:
    IMPLEMENTED = False

    def __init__(self, settings: Settings) -> None:
        self.dry_run = settings.dry_run

    def preview_change(self, change: dict[str, Any]) -> dict[str, Any]:
        return {"change": change, "provider": "google-calendar"}

    def execute_change(self, preview: dict[str, Any]) -> dict[str, Any]:
        if self.dry_run:
            return {"status": "dry_run", "change": preview.get("change")}
        raise ProviderError("not_implemented", "TODO(live, owner E): Calendar write")
```

- [ ] **Step 4: registry 註冊空殼**

`apps/api/campuspulse/providers/registry.py`：import 區加

```python
from campuspulse.providers.bike.tdx_youbike import TdxYouBikeProvider
from campuspulse.providers.flood.wra import WraFloodProvider
from campuspulse.providers.transit.tdx_bus import TdxBusProvider
from campuspulse.providers.weather.cwa import CwaWeatherProvider
```

把 `LIVE_SIGNAL_CLASSES: dict[str, tuple[type, tuple[str, ...]]] = {}` 改成

```python
LIVE_SIGNAL_CLASSES: dict[str, tuple[type, tuple[str, ...]]] = {
    "rain": (CwaWeatherProvider, ("cwa_api_key",)),
    "flood": (WraFloodProvider, ("wra_api_key",)),
    "bike": (TdxYouBikeProvider, ("tdx_client_id", "tdx_client_secret")),
    "transit": (TdxBusProvider, ("tdx_client_id", "tdx_client_secret")),
    # parking: 校方無即時資料前永遠 fixture（owner D 查總務處）
}
```

- [ ] **Step 5: 跑測試確認通過**

Run: `pytest -q`
Expected: 全綠。

- [ ] **Step 6: Commit**

```powershell
git add apps/api/campuspulse/providers apps/api/tests/test_registry.py
git commit -m "feat(providers): add live adapter shells for CWA, WRA, TDX, floor plan, Gmail and Calendar"
```

---

### Task 12: Web 骨架（Vite + React + Tailwind + Leaflet）、型別、API client

**Files:**
- Create: `apps/web/`（Vite 產生）、`apps/web/vite.config.ts`、`apps/web/src/index.css`、`apps/web/src/main.tsx`、`apps/web/src/types.ts`、`apps/web/src/api/client.ts`、`apps/web/src/App.tsx`（先只顯示 JSON）

**Interfaces:**
- Produces: `types.ts` 的 `AppState` 等型別（對應 Task 7 snapshot）；`api/client.ts`：`getState()`, `resetScenario()`, `stepScenario()`, `injectSignals(overrides)`, `confirmAction(id)`, `rejectAction(id)`, `getHealth()`，全部回 `Promise<AppState>`（health 回 `Promise<Health>`）。

- [ ] **Step 1: 產生專案並裝依賴**

```powershell
Set-Location apps
npm create vite@latest web -- --template react-ts
Set-Location web
npm install
npm install leaflet react-leaflet
npm install -D tailwindcss @tailwindcss/vite @types/leaflet
```

- [ ] **Step 2: 設定 Vite、Tailwind、Leaflet CSS**

`apps/web/vite.config.ts`
```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
});
```

`apps/web/src/index.css`（整檔取代）
```css
@import "tailwindcss";

:root {
  color-scheme: light;
  --cp-bg: #f5f6f8;
  --cp-card: #ffffff;
  --cp-ink: #1f2933;
  --cp-muted: #6b7280;
  --cp-accent: #1e66f5;
  --cp-ok: #15803d;
  --cp-warn: #b45309;
  --cp-bad: #b91c1c;
}
body { margin: 0; background: var(--cp-bg); color: var(--cp-ink); font-family: system-ui, "Noto Sans TC", sans-serif; }
.leaflet-container { height: 260px; width: 100%; border-radius: 12px; }
```

`apps/web/src/main.tsx`（整檔取代）
```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "./index.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

刪除 Vite 範本的 `src/App.css` 與 `src/assets/react.svg`。

- [ ] **Step 3: 型別與 client**

`apps/web/src/types.ts`
```ts
export type Mode = "walk" | "scooter" | "bike" | "transit";
export type SourceMode = "live" | "fixture" | "stale" | "unavailable";
export type PlanStatus = "ok" | "late_risk" | "no_feasible" | "arrived";

export interface LatLng { lat: number; lng: number }

export interface RouteResult {
  mode: Mode; duration_min: number; distance_m: number; polyline: LatLng[];
  summary: string; corridor_ids: string[]; source_mode: SourceMode; mode_proxy?: string | null;
}

export interface LastDecision {
  kind: "parking_lot" | "bike_dock" | "bus_stop" | "gate";
  target_id: string; label: string; walk_min: number; reason: string; location?: LatLng | null;
}

export interface TravelOption {
  mode: Mode; route: RouteResult | null; last_decision: LastDecision | null;
  base_eta_min: number; conservative_eta_min: number;
  depart_at: string | null; arrive_at: string | null;
  feasible: boolean; on_time: boolean; slack_min: number;
  reasons: string[]; risk_flags: string[]; reliability: number; score: number; evidence: string[];
}

export interface Plan {
  commitment_id: string; generated_at: string; selected: TravelOption | null; options: TravelOption[];
  rationale: string; next_check_at: string | null; status: PlanStatus; policy_version: string; decisions_made: number;
}

export interface Commitment {
  id: string; title: string; start: string; building_id: string; room: string;
  importance: "normal" | "high" | "critical"; source: string; confirmed: boolean;
}

export interface Signal {
  kind: string; observed_at: string; valid_until: string | null;
  value: Record<string, unknown>; source_mode: SourceMode; confidence: number;
}

export interface TimelineEvent {
  at: string; phase: "perceive" | "plan" | "act" | "reflect"; title: string; detail: string; source_modes: string[];
}

export interface Trigger { kind: string; description: string; observed_at: string; material: boolean }

export interface ProposedAction {
  id: string; type: "email" | "calendar";
  preview: { to?: string[]; subject?: string; body?: string; [k: string]: unknown };
  state: "proposed" | "confirmed" | "rejected" | "executed_dry_run"; created_at: string;
}

export interface IndoorGuidance {
  building_id: string; room: string; floor: string; wing: string; entrance: string;
  instructions: string; source_mode: SourceMode; confidence: number;
}

export interface AppState {
  clock: string | null; user_state: string;
  step_index: number; step_count: number; step_note: string; scenario_title: string;
  commitment: Commitment; origin: LatLng;
  building: { id: string; name: string; campus: string; location: LatLng };
  plan: Plan | null; signals: Record<string, Signal>; routes_source: Record<string, string>;
  timeline: TimelineEvent[]; triggers: Trigger[]; actions: ProposedAction[];
  decisions: { agent: number; user: number }; indoor: IndoorGuidance | null;
  providers: Record<string, string>;
}

export interface Health {
  status: string; provider_mode: string; dry_run: boolean; missing_credentials: string[]; providers: Record<string, string>;
}
```

`apps/web/src/api/client.ts`
```ts
import type { AppState, Health } from "../types";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return (await res.json()) as T;
}

export const getHealth = () => call<Health>("/api/health");
export const getState = () => call<AppState>("/api/state");
export const resetScenario = () => call<AppState>("/api/scenario/reset", { method: "POST" });
export const stepScenario = () => call<AppState>("/api/scenario/step", { method: "POST" });
export const injectSignals = (overrides: Record<string, Record<string, unknown>>) =>
  call<AppState>("/api/scenario/inject", { method: "POST", body: JSON.stringify(overrides) });
export const confirmAction = async (id: string) =>
  (await call<{ state: AppState }>(`/api/actions/${id}/confirm`, { method: "POST" })).state;
export const rejectAction = async (id: string) =>
  (await call<{ state: AppState }>(`/api/actions/${id}/reject`, { method: "POST" })).state;
```

`apps/web/src/App.tsx`（暫時版，Task 13 取代）
```tsx
import { useEffect, useState } from "react";
import { getState } from "./api/client";
import type { AppState } from "./types";

export default function App() {
  const [state, setState] = useState<AppState | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { getState().then(setState).catch((e) => setError(String(e))); }, []);
  if (error) return <pre className="p-4 text-red-700">{error}</pre>;
  if (!state) return <p className="p-4">載入中…</p>;
  return <pre className="p-4 text-xs whitespace-pre-wrap">{JSON.stringify(state.plan?.selected, null, 2)}</pre>;
}
```

- [ ] **Step 4: 驗證 build 與 dev**

Run（apps/web）: `npm run build`
Expected: `✓ built`，無 TS 錯誤。
Run: 後端 `uvicorn campuspulse.main:app --port 8000` + 前端 `npm run dev`，開 http://localhost:5173 看到 selected JSON。

- [ ] **Step 5: Commit**

```powershell
git add apps/web
git commit -m "feat(web): scaffold Vite React app with API client and types"
```

---

### Task 13: Web 元件與主畫面

**Files:**
- Create: `apps/web/src/components/ScenarioBar.tsx`, `CommitmentCard.tsx`, `PlanCard.tsx`, `MapView.tsx`, `DecisionCounter.tsx`, `Timeline.tsx`, `ActionModal.tsx`, `IndoorCard.tsx`, `apps/web/src/labels.ts`
- Modify: `apps/web/src/App.tsx`（整檔取代）

**Interfaces:**
- Consumes: Task 12 types 與 client。
- Produces: 每個元件的 props 如下方程式碼；`App` 持有 `state`，所有按鈕呼叫 client 後 `setState`。

- [ ] **Step 1: 標籤對照**

`apps/web/src/labels.ts`
```ts
import type { Mode, PlanStatus, SourceMode } from "./types";

export const MODE_LABEL: Record<Mode, string> = { walk: "步行", scooter: "機車", bike: "YouBike", transit: "公車" };
export const MODE_ICON: Record<Mode, string> = { walk: "🚶", scooter: "🛵", bike: "🚲", transit: "🚌" };
export const REASON_LABEL: Record<string, string> = {
  route_unavailable: "查無路線", unsafe_heavy_rain: "豪雨不安全", flood_on_route: "路線積淹水",
  no_bike: "起點站無車", no_dock: "終點站無位", no_parking: "停車場全滿", too_late: "已來不及準時",
};
export const RISK_LABEL: Record<string, string> = {
  rerouted: "已改道", rain_unavailable: "無雨量資料", flood_unavailable: "無積水資料",
  transit_eta_unavailable: "無公車到站資料", parking_unavailable: "無停車場資料", routing_unavailable: "無路線資料",
};
export const STATUS_LABEL: Record<PlanStatus, string> = { ok: "照計畫", late_risk: "快遲到", no_feasible: "來不及", arrived: "已到大樓" };
export const SOURCE_CLASS: Record<SourceMode | string, string> = {
  live: "bg-green-100 text-green-800", fixture: "bg-amber-100 text-amber-800",
  stale: "bg-orange-100 text-orange-800", unavailable: "bg-red-100 text-red-800",
};
export const hhmm = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Taipei" }) : "--:--";
```

- [ ] **Step 2: 元件**

`apps/web/src/components/ScenarioBar.tsx`
```tsx
import { SOURCE_CLASS, hhmm } from "../labels";
import type { AppState } from "../types";

interface Props { state: AppState; busy: boolean; onReset: () => void; onStep: () => void }

export default function ScenarioBar({ state, busy, onReset, onStep }: Props) {
  const last = state.step_index >= state.step_count - 1;
  return (
    <div className="rounded-xl bg-white p-3 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-2xl font-semibold tabular-nums">{hhmm(state.clock)}</div>
          <div className="text-xs text-gray-500">劇本 {state.step_index + 1}/{state.step_count}・{state.step_note}</div>
        </div>
        <div className="flex gap-2">
          <button onClick={onReset} disabled={busy} className="rounded-lg border px-3 py-2 text-sm">重設</button>
          <button onClick={onStep} disabled={busy || last} className="rounded-lg bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-40">推進 ▶</button>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {Object.entries(state.providers).map(([name, mode]) => (
          <span key={name} className={`rounded px-1.5 py-0.5 text-[11px] ${SOURCE_CLASS[mode] ?? SOURCE_CLASS.unavailable}`}>{name}: {mode}</span>
        ))}
      </div>
    </div>
  );
}
```

`apps/web/src/components/CommitmentCard.tsx`
```tsx
import { hhmm } from "../labels";
import type { AppState } from "../types";

const IMPORTANCE: Record<string, string> = { normal: "一般", high: "重要", critical: "絕不能遲到" };

export default function CommitmentCard({ state }: { state: AppState }) {
  const c = state.commitment;
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm">
      <div className="text-xs text-gray-500">今天的承諾・來源 {c.source}</div>
      <div className="mt-1 text-lg font-semibold">{c.title}</div>
      <div className="mt-1 text-sm">{hhmm(c.start)}・{state.building.name} {c.room}</div>
      <span className={`mt-2 inline-block rounded px-2 py-0.5 text-xs ${c.importance === "normal" ? "bg-gray-100" : "bg-red-100 text-red-800"}`}>
        {IMPORTANCE[c.importance]}
      </span>
    </div>
  );
}
```

`apps/web/src/components/PlanCard.tsx`
```tsx
import { MODE_ICON, MODE_LABEL, REASON_LABEL, RISK_LABEL, STATUS_LABEL, hhmm } from "../labels";
import type { Mode, Plan } from "../types";

interface Props { plan: Plan; activeMode: Mode; onSelectMode: (m: Mode) => void }

export default function PlanCard({ plan, activeMode, onSelectMode }: Props) {
  const active = plan.options.find((o) => o.mode === activeMode) ?? plan.options[0];
  const isSelected = plan.selected?.mode === active.mode;
  const statusClass = plan.status === "ok" ? "bg-green-100 text-green-800" : plan.status === "arrived" ? "bg-blue-100 text-blue-800" : "bg-red-100 text-red-800";
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-500">建議方案</div>
        <span className={`rounded px-2 py-0.5 text-xs ${statusClass}`}>{STATUS_LABEL[plan.status]}</span>
      </div>
      <div className="mt-2 flex gap-1">
        {plan.options.map((o) => (
          <button key={o.mode} onClick={() => onSelectMode(o.mode)}
            className={`flex-1 rounded-lg border px-1 py-1.5 text-xs ${o.mode === active.mode ? "border-blue-600 bg-blue-50" : "border-gray-200"} ${o.feasible ? "" : o.on_time ? "opacity-80" : "opacity-50"}`}>
            <div>{MODE_ICON[o.mode]} {MODE_LABEL[o.mode]}</div>
            <div className="text-[10px] text-gray-500">{o.feasible ? "可行" : o.on_time ? "勉強" : "不可行"}{plan.selected?.mode === o.mode ? "・推薦" : ""}</div>
          </button>
        ))}
      </div>
      <div className="mt-3">
        {active.reasons.length === 0 ? (
          <div className="text-xl font-semibold">
            {hhmm(active.depart_at)} 出門 → {hhmm(active.arrive_at)} 到
            <span className="ml-2 text-sm font-normal text-gray-500">緩衝 {active.slack_min} 分</span>
          </div>
        ) : (
          <div className="text-base font-semibold text-red-700">{active.reasons.map((r) => REASON_LABEL[r] ?? r).join("、")}</div>
        )}
        {active.last_decision && (
          <div className="mt-2 rounded-lg bg-gray-50 p-2 text-sm">
            <div className="text-xs text-gray-500">最後一個決定</div>
            <div className="font-medium">{active.last_decision.label}</div>
            <div className="text-xs text-gray-600">{active.last_decision.reason}</div>
          </div>
        )}
        {active.risk_flags.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {active.risk_flags.map((f) => <span key={f} className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-800">{RISK_LABEL[f] ?? f}</span>)}
          </div>
        )}
        <div className="mt-2 text-xs text-gray-500">
          路線 {active.route?.summary}・預估 {active.conservative_eta_min} 分（含緩衝係數）・可靠度 {active.reliability}
          {active.route?.mode_proxy ? `・以 ${active.route.mode_proxy} 代算` : ""}
        </div>
        {active.evidence.length > 0 && (
          <ul className="mt-1 list-disc pl-4 text-xs text-gray-500">{active.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>
        )}
        {isSelected && <p className="mt-3 border-t pt-2 text-sm">{plan.rationale}</p>}
      </div>
    </div>
  );
}
```

`apps/web/src/components/MapView.tsx`
```tsx
import { useEffect } from "react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import type { LatLng, TravelOption } from "../types";

interface Props { origin: LatLng; building: { name: string; location: LatLng }; option: TravelOption | undefined }

function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  useEffect(() => { if (points.length > 1) map.fitBounds(points, { padding: [24, 24] }); }, [map, points]);
  return null;
}

export default function MapView({ origin, building, option }: Props) {
  const line: [number, number][] = (option?.route?.polyline ?? []).map((p) => [p.lat, p.lng]);
  const points: [number, number][] = [[origin.lat, origin.lng], [building.location.lat, building.location.lng], ...line];
  const ld = option?.last_decision?.location;
  return (
    <MapContainer center={[origin.lat, origin.lng]} zoom={14} scrollWheelZoom={false}>
      <TileLayer attribution="&copy; OpenStreetMap" url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <FitBounds points={points} />
      {line.length > 1 && <Polyline positions={line} pathOptions={{ color: option?.feasible ? "#1e66f5" : "#b91c1c", weight: 5 }} />}
      <CircleMarker center={[origin.lat, origin.lng]} radius={7} pathOptions={{ color: "#1f2933" }}><Popup>出發</Popup></CircleMarker>
      <CircleMarker center={[building.location.lat, building.location.lng]} radius={8} pathOptions={{ color: "#15803d" }}><Popup>{building.name}</Popup></CircleMarker>
      {ld && <CircleMarker center={[ld.lat, ld.lng]} radius={7} pathOptions={{ color: "#b45309" }}><Popup>{option?.last_decision?.label}</Popup></CircleMarker>}
    </MapContainer>
  );
}
```

`apps/web/src/components/DecisionCounter.tsx`
```tsx
export default function DecisionCounter({ agent, user }: { agent: number; user: number }) {
  return (
    <div className="rounded-xl bg-blue-600 p-4 text-white shadow-sm">
      <div className="text-xs opacity-80">省下的專注力</div>
      <div className="text-lg font-semibold">今天 CampusPulse 幫你做了 {agent} 個決定，你做了 {user} 個</div>
    </div>
  );
}
```

`apps/web/src/components/Timeline.tsx`
```tsx
import { hhmm } from "../labels";
import type { TimelineEvent } from "../types";

const PHASE: Record<TimelineEvent["phase"], { label: string; cls: string }> = {
  perceive: { label: "感知", cls: "bg-gray-200 text-gray-800" },
  plan: { label: "規劃", cls: "bg-blue-100 text-blue-800" },
  act: { label: "行動", cls: "bg-green-100 text-green-800" },
  reflect: { label: "反思", cls: "bg-purple-100 text-purple-800" },
};

export default function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm">
      <div className="text-xs text-gray-500">Agent 時間軸（最新在上）</div>
      <ul className="mt-2 space-y-2">
        {[...events].reverse().map((e, i) => (
          <li key={i} className="flex gap-2 text-sm">
            <span className="w-11 shrink-0 tabular-nums text-gray-500">{hhmm(e.at)}</span>
            <span className={`h-fit shrink-0 rounded px-1.5 py-0.5 text-[11px] ${PHASE[e.phase].cls}`}>{PHASE[e.phase].label}</span>
            <div>
              <div>{e.title}</div>
              {e.detail && <div className="text-xs text-gray-500">{e.detail}</div>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

`apps/web/src/components/ActionModal.tsx`
```tsx
import type { ProposedAction } from "../types";

interface Props { action: ProposedAction; busy: boolean; onConfirm: () => void; onReject: () => void }

export default function ActionModal({ action, busy, onConfirm, onReject }: Props) {
  return (
    <div className="fixed inset-0 z-[1000] flex items-end justify-center bg-black/40 p-4 sm:items-center">
      <div className="w-full max-w-[480px] rounded-xl bg-white p-4 shadow-lg">
        <div className="text-xs text-gray-500">需要你確認・寄信</div>
        <div className="mt-1 font-semibold">{action.preview.subject}</div>
        <div className="mt-1 text-xs text-gray-500">收件：{(action.preview.to ?? []).join("、")}</div>
        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 text-sm">{action.preview.body}</pre>
        <div className="mt-3 flex gap-2">
          <button onClick={onReject} disabled={busy} className="flex-1 rounded-lg border px-3 py-2 text-sm">先不要</button>
          <button onClick={onConfirm} disabled={busy} className="flex-1 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white">確認寄出（dry-run）</button>
        </div>
      </div>
    </div>
  );
}
```

`apps/web/src/components/IndoorCard.tsx`
```tsx
import { SOURCE_CLASS } from "../labels";
import type { IndoorGuidance } from "../types";

export default function IndoorCard({ guidance, buildingName }: { guidance: IndoorGuidance; buildingName: string }) {
  return (
    <div className="rounded-xl border-2 border-green-600 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-500">最後 200 公尺・{buildingName}</div>
        <span className={`rounded px-1.5 py-0.5 text-[11px] ${SOURCE_CLASS[guidance.source_mode]}`}>{guidance.source_mode}</span>
      </div>
      <div className="mt-1 text-2xl font-semibold">{guidance.room}</div>
      <div className="text-sm">{guidance.floor}・{guidance.wing}・從{guidance.entrance}進</div>
      <p className="mt-2 text-sm">{guidance.instructions}</p>
    </div>
  );
}
```

- [ ] **Step 3: 主畫面**

`apps/web/src/App.tsx`（整檔取代）
```tsx
import { useCallback, useEffect, useState } from "react";
import { confirmAction, getState, rejectAction, resetScenario, stepScenario } from "./api/client";
import ActionModal from "./components/ActionModal";
import CommitmentCard from "./components/CommitmentCard";
import DecisionCounter from "./components/DecisionCounter";
import IndoorCard from "./components/IndoorCard";
import MapView from "./components/MapView";
import PlanCard from "./components/PlanCard";
import ScenarioBar from "./components/ScenarioBar";
import Timeline from "./components/Timeline";
import type { AppState, Mode } from "./types";

export default function App() {
  const [state, setState] = useState<AppState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<Mode | null>(null);

  const apply = useCallback(async (fn: () => Promise<AppState>) => {
    setBusy(true);
    try { const s = await fn(); setState(s); setMode(s.plan?.selected?.mode ?? null); setError(null); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }, []);

  useEffect(() => { void apply(getState); }, [apply]);

  if (error && !state) return <pre className="p-4 text-red-700">後端沒回應：{error}（先啟動 apps/api）</pre>;
  if (!state) return <p className="p-4">載入中…</p>;

  const plan = state.plan;
  const activeMode = mode ?? plan?.selected?.mode ?? plan?.options[0]?.mode ?? "scooter";
  const activeOption = plan?.options.find((o) => o.mode === activeMode);
  const pending = state.actions.find((a) => a.state === "proposed");

  return (
    <div className="mx-auto max-w-[480px] space-y-3 p-3 pb-10">
      <header className="px-1 pt-1">
        <div className="text-xl font-bold">CampusPulse</div>
        <div className="text-xs text-gray-500">{state.scenario_title}</div>
      </header>
      <ScenarioBar state={state} busy={busy} onReset={() => apply(resetScenario)} onStep={() => apply(stepScenario)} />
      <CommitmentCard state={state} />
      {plan && <PlanCard plan={plan} activeMode={activeMode} onSelectMode={setMode} />}
      <MapView origin={state.origin} building={state.building} option={activeOption} />
      {state.indoor && <IndoorCard guidance={state.indoor} buildingName={state.building.name} />}
      <DecisionCounter agent={state.decisions.agent} user={state.decisions.user} />
      <Timeline events={state.timeline} />
      {error && <div className="text-xs text-red-700">{error}</div>}
      {pending && (
        <ActionModal action={pending} busy={busy}
          onConfirm={() => apply(() => confirmAction(pending.id))}
          onReject={() => apply(() => rejectAction(pending.id))} />
      )}
    </div>
  );
}
```

- [ ] **Step 4: 驗證**

Run（apps/web）: `npm run build` → 無 TS 錯誤。
Run 兩個 dev server，瀏覽 http://localhost:5173：
1. 07:50 卡片：機車、停 A 場、地圖有路線。
2. 按「推進」：公車、機車 tab 顯示「已改道」與 B 場、時間軸有「建議從 機車 改為 公車」。
3. 再推進：狀態「快遲到」、跳出寄信 modal；按確認 → 計數器「你做了 1 個」。
4. 再推進：出現綠框教室卡「4263・4F・東側」。
5. 重設 → 回到第 1 步。

- [ ] **Step 5: Commit**

```powershell
git add apps/web
git commit -m "feat(web): add plan card, map, timeline, action modal and indoor card"
```

---

### Task 14: 文件與分工

**Files:**
- Create: `docs/team-ownership.md`, `docs/api-and-data.md`
- Modify: `README.md`（加 quickstart）

- [ ] **Step 1: 分工文件**

`docs/team-ownership.md`
```markdown
# 分工與交接

主線（A）已跑通：承諾 → 四模式規劃 → 劇本推進 → 自動改計畫 → 確認閘門 → 教室卡。全程 fixture，無 key 可 demo。

每個空殼 = 一個 class + `IMPLEMENTED = False` + docstring 寫清楚資料來源與回傳格式。接手者：
1. 讀 class docstring 與 `campuspulse/providers/base.py` 的 Protocol。
2. 實作 `fetch()` / `locate()` / `send()`，回傳同樣的 model。
3. 把 `IMPLEMENTED = True`。`PROVIDER_MODE=auto` 且 key 齊全時 registry 會自動選用。
4. 加 contract test：用 `httpx.MockTransport` 餵假回應，斷言 normalized 欄位與錯誤碼（範例：`tests/test_google_routes.py`）。
5. 不要改 planner；訊號格式在 `providers/registry.py` 註解與 `tests/test_planner.py` 的 `_signals()`。

| 人 | 資料夾 | 交付 | 驗收 |
|---|---|---|---|
| A | core、routing、scenario、ai/gemini、ai/rationale、web | 已完成主線 | `pytest -q` 全綠、`npm run build` 通過 |
| B | providers/weather/cwa.py、flood/wra.py、bike/tdx_youbike.py、transit/tdx_bus.py | 4 個 live adapter | `/api/health` 的 providers 顯示 `live`；contract test |
| C | ai/timetable.py、providers/email/gmail.py（讀信分類） | 課表圖 → commitments；教授信 → 重要度／教室變更 | fixture 圖 3 張（清晰／模糊／錯位）皆有輸出；低信心走人工修正 |
| D | data/ncku/*.json、providers/indoor/floorplan_gemini.py、providers/parking | 成大官網抓座標、入口、停車場；平面圖；教室卡 live | 每筆 `verified: true`；4263 導引由平面圖產生 |
| E | providers/calendar、email send、部署、demo | Calendar 預覽/寫入、真寄信（需確認）、Cloud Run／Vercel、簡報 | 兩次從重設跑完 demo 不出錯 |

## 本機啟動

後端（apps/api）：
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn campuspulse.main:app --reload --port 8000
pytest -q
```

前端（apps/web）：
```powershell
npm install
npm run dev
```

## 規則

- `main` 隨時可 demo；功能分支 + PR（見 CONTRIBUTING.md）。
- key 只放 `apps/api/.env`；不進 git、不進截圖、不進聊天。
- UI 上每個訊號都要有來源徽章；fixture 不可偽裝 live。
- 外部寫入（信、行事曆）預設 dry-run；真寫入只在使用者按確認後。
```

- [ ] **Step 2: API 與資料清單**

`docs/api-and-data.md`
```markdown
# 需要的 API、Key 與資料

## Key（全部免費）

| 用途 | 哪裡拿 | env 名稱 | 負責 |
|---|---|---|---|
| Gemini 3 Flash / Pro | Google AI Studio → Create API Key | `GEMINI_API_KEY` | 已有 |
| Google Routes API（步行／機車以 DRIVE 代／單車／公車） | GCP 專案 → 啟用 **Routes API** → 建 API key（限制只允許 Routes API）。用團隊 GCP 抵免額 | `GOOGLE_MAPS_API_KEY` | A |
| TDX（YouBike、公車到站） | https://tdx.transportdata.tw 註冊 → 會員中心 → API 金鑰 | `TDX_CLIENT_ID`、`TDX_CLIENT_SECRET` | B |
| 中央氣象署 | https://opendata.cwa.gov.tw 註冊 → 取得授權碼 | `CWA_API_KEY` | B |
| 水利署水資源物聯網 | https://iot.wra.gov.tw 申請 | `WRA_API_KEY` | B |
| Gmail / Calendar | GCP 同專案 → OAuth 同意畫面 → 桌面／Web 用戶端；scope 最小化 | 由 E 決定 env 名稱後加入 `.env.example` | E |

啟用方式：`apps/api/.env` 設 `PROVIDER_MODE=auto`。有 key 且 class `IMPLEMENTED=True` 的 provider 走 live，其餘 fixture。`GET /api/health` 看目前各 provider 模式。

## Routes API 注意

- 機車：台灣沒有 `TWO_WHEELER`，用 `DRIVE` + 避開高速公路代替，UI 標「以 DRIVE 代算」。
- `BICYCLE` 台灣覆蓋需實測；失敗會回 `unavailable`，planner 標該模式不可行並註明「無路線資料」。
- `TRANSIT` 台南公車 Google 有資料；需 `departureTime` 在未來，fixture 時鐘在過去時會略過此欄。
- 每次 `/api/state` 重算四模式 = 4 次呼叫；demo 前確認額度。

## 手工資料（D，從成大官網抓）

檔案都在 `apps/api/data/ncku/`，只改值不改欄位，改完把 `verified` 設 `true`。

| 檔案 | 內容 | 來源 |
|---|---|---|
| `buildings.json` | 建築 id、名稱、校區、座標、入口（哪側門、座標） | 成大校園地圖 |
| `parking_lots.json` | 機車停車場座標、有無遮雨、容量 | 總務處事務組／校園地圖 |
| `rooms.json` | 教室 → 建築、樓層、翼、入口、走法 | 系網平面圖；沒有就拍門口逃生圖 |
| `bike_stations.json` | 校園周邊 YouBike 站 | TDX 站點清單（B 提供 StationUID） |
| `bus_stops.json` | 校園周邊公車站 | TDX 站點清單 |
| `corridors.json` | 路名 → 走廊 id（積淹水對應用） | 自行維護 |
| `floorplans/<building>/<floor>.png` | 平面圖影像（新資料夾） | 系網 PDF 轉圖／逃生圖照片 |

先做資訊系館 + 2 棟常用系館；每棟至少 1 張平面圖。

## 待查（D）

- 成大教室編號規則（4263 = 哪棟幾樓？）→ 決定 IndoorCard 文案。
- 校內機車停車場有無即時車位（總務處）→ 沒有就永遠 fixture。
```

- [ ] **Step 3: README quickstart**

在 `README.md` 的 `## Local setup` 之前插入：

```markdown
## CampusPulse quickstart

- 後端：`apps/api`（FastAPI）。`pip install -r requirements.txt` → `uvicorn campuspulse.main:app --reload --port 8000` → `pytest -q`
- 前端：`apps/web`（Vite + React）。`npm install` → `npm run dev` → http://localhost:5173
- 無任何 key 也能跑（fixture 模式）。分工與接手方式見 `docs/team-ownership.md`；key 與資料清單見 `docs/api-and-data.md`。
```

- [ ] **Step 4: Commit 與 PR**

```powershell
git add docs README.md
git commit -m "docs: add team ownership and API/data guide"
git push -u origin feature/skeleton
```

開 PR 到 `main`，標題 `feat: CampusPulse skeleton with fixture-driven navigation mainline`。
