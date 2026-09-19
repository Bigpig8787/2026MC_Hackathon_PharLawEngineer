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
