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
