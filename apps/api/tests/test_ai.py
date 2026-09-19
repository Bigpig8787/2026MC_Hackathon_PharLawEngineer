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
