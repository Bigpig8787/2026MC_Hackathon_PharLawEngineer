from __future__ import annotations

from typing import Any


class FixtureEmailProvider:
    """Never sends. Returns previews and dry-run receipts."""

    def preview(self, to: list[str], subject: str, body: str) -> dict[str, Any]:
        return {"to": to, "subject": subject, "body": body, "provider": "fixture"}

    def send(self, preview: dict[str, Any]) -> dict[str, Any]:
        return {"status": "dry_run", "to": preview.get("to", []), "subject": preview.get("subject", "")}
