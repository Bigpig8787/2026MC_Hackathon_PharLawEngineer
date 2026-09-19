# 2026MC_Hackathon_PharLawEngineer

## CampusPulse quickstart

- 後端：`apps/api`（FastAPI）。`pip install -r requirements.txt` → `uvicorn campuspulse.main:app --reload --port 8000` → `pytest -q`
- 前端：`apps/web`（Vite + React）。`npm install` → `npm run dev` → http://localhost:5173
- 無任何 key 也能跑（fixture 模式）。分工與接手方式見 `docs/team-ownership.md`；key 與資料清單見 `docs/api-and-data.md`。

## Local setup

Copy `.env.example` to `.env` and fill in only the values needed by your task. Never commit `.env`, `API`, or API keys.

```powershell
Copy-Item .env.example .env
```

`api.py` is the tracked Python configuration module. Keep secrets in environment variables or the git-ignored `API` / `API.txt` files; never paste a real key into `api.py`.

## AI Studio smoke test

Put the Gemini API key in the git-ignored `API` file, or set `GEMINI_API_KEY`, then run:

```powershell
node scripts/test-ai-studio.mjs
```

Set `GEMINI_MODEL` to test another model without changing the script.

## Team workflow

Use short-lived task branches and pull requests. See [CONTRIBUTING.md](CONTRIBUTING.md) for branch ownership, daily sync commands, and merge rules.
