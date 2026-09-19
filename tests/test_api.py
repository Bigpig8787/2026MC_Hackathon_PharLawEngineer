"""api.py 設定模組測試：重點是「不洩漏金鑰」與「正確偵測缺漏」。"""
import pytest

import api

SECRET = "sk-THIS-SHOULD-NEVER-APPEAR"
ALL_KEYS = ["GOOGLE_API_KEY", "GEMINI_API_KEY", "CWA_API_KEY",
            "TDX_CLIENT_ID", "TDX_CLIENT_SECRET", "GOOGLE_MAPS_API_KEY", "PROVIDER_MODE"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ALL_KEYS:
        monkeypatch.delenv(k, raising=False)


def test_default_mode_is_fixture():
    s = api.load_settings(load_env_file=False)
    assert s.provider_mode == "fixture"


def test_invalid_provider_mode_raises(monkeypatch):
    monkeypatch.setenv("PROVIDER_MODE", "production")
    with pytest.raises(ValueError):
        api.load_settings(load_env_file=False)


def test_gemini_key_detected_from_GEMINI_API_KEY(monkeypatch):
    # 回歸測試：朋友 repo 的 api.py 標籤寫 GEMINI_API_KEY 卻讀 OPENAI_API_KEY
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    s = api.load_settings(load_env_file=False)
    assert "GEMINI_API_KEY" not in api.missing_credentials(s, ["gemini"])


def test_gemini_key_detected_from_GOOGLE_API_KEY(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", SECRET)
    s = api.load_settings(load_env_file=False)
    assert api.missing_credentials(s, ["gemini"]) == []


def test_missing_credentials_lists_names_only():
    s = api.load_settings(load_env_file=False)
    missing = api.missing_credentials(s, ["gemini", "transit"])
    assert "GEMINI_API_KEY" in missing
    assert "TDX_CLIENT_ID" in missing and "TDX_CLIENT_SECRET" in missing


def test_ncku_needs_no_credentials():
    s = api.load_settings(load_env_file=False)
    assert api.missing_credentials(s, ["ncku"]) == []


def test_unknown_feature_raises():
    s = api.load_settings(load_env_file=False)
    with pytest.raises(KeyError):
        api.missing_credentials(s, ["teleport"])


def test_repr_and_str_never_leak_secrets(monkeypatch):
    for k in ["GEMINI_API_KEY", "CWA_API_KEY", "TDX_CLIENT_SECRET", "GOOGLE_MAPS_API_KEY"]:
        monkeypatch.setenv(k, SECRET)
    s = api.load_settings(load_env_file=False)
    assert SECRET not in repr(s)
    assert SECRET not in str(s)
