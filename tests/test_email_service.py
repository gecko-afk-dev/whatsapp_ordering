import asyncio
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_email_service_retries_transient_failures(monkeypatch):
    import app.services.email as email_service

    email_service = importlib.reload(email_service)

    attempts = {"count": 0}

    async def fake_send_email_async(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary failure")
        return True

    monkeypatch.setattr(email_service.EmailService, "_send_email_async", fake_send_email_async)

    async def run_test():
        return await email_service.EmailService.send_beta_confirmation(
            email="test@example.com",
            manager_name="Jane",
            restaurant_name="Chez Jane",
            locale="fr",
        )

    result = asyncio.run(run_test())

    assert result is True
    assert attempts["count"] == 3
