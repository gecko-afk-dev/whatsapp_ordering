import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DummyRequest:
    def __init__(self, client_ip: str):
        self.headers = {}
        self.client = SimpleNamespace(host=client_ip)


def test_rate_limit_can_be_disabled(monkeypatch):
    monkeypatch.setenv("BETA_SIGNUP_RATE_LIMIT_ENABLED", "false")

    import app.api.beta as beta

    beta = importlib.reload(beta)
    request = DummyRequest("203.0.113.10")

    for _ in range(10):
        asyncio.run(beta.check_rate_limit(request))
