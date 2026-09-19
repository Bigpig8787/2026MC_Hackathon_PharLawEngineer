# 2026MC_Hackathon_PharLawEngineer

## Local setup

Copy `.env.example` to `.env` and fill in only the values needed by your task. Never commit `.env`, `API`, or API keys.

```powershell
Copy-Item .env.example .env
```

The legacy `API` file is also supported by the smoke test and is ignored by Git.

## AI Studio smoke test

Put the Gemini API key in the git-ignored `API` file, or set `GEMINI_API_KEY`, then run:

```powershell
node scripts/test-ai-studio.mjs
```

Set `GEMINI_MODEL` to test another model without changing the script.

## Team workflow

Use short-lived task branches and pull requests. See [CONTRIBUTING.md](CONTRIBUTING.md) for branch ownership, daily sync commands, and merge rules.
