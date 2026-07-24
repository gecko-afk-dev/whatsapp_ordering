import asyncio
import importlib
import sys
from pathlib import Path

from fastapi import BackgroundTasks

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeDB:
    def __init__(self):
        self.added = []
        self.committed = 0
        self.refreshed = []
        self._results = []

    async def execute(self, *_args, **_kwargs):
        if not self._results:
            return FakeResult(None)
        return self._results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed += 1

    async def refresh(self, obj):
        self.refreshed.append(obj)


def test_beta_signup_sends_confirmation_inline(monkeypatch):
    import app.api.beta as beta

    beta = importlib.reload(beta)

    called = {"count": 0}

    async def fake_send_signup_emails_task(**_kwargs):
        called["count"] += 1
        return True

    monkeypatch.setattr(beta, "send_signup_emails_task", fake_send_signup_emails_task)

    card = type("Card", (), {"id": 1, "status": beta.BetaCardStatus.AVAILABLE, "claimed_at": None})()
    db = FakeDB()
    db._results = [FakeResult(card), FakeResult(None)]

    req = beta.BetaSignupRequest(
        manager_name="Jane",
        restaurant_name="Chez Jane",
        email="jane@example.com",
        whatsapp_number="+212600000000",
        card_code="GEQO-ABC123",
        locale="fr",
    )

    asyncio.run(beta.beta_signup(req, db=db))

    assert called["count"] == 1
