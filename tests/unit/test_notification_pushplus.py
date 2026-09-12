import pytest

from src.notification import engine


class _Response:
    is_error = False

    @staticmethod
    def json() -> dict[str, int]:
        return {"code": 200}


class _Client:
    payloads: list[dict[str, str]] = []

    def __init__(self, **_: object):
        pass

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, _: str, *, json: dict[str, str]) -> _Response:
        self.payloads.append(json)
        return _Response()


@pytest.mark.asyncio
async def test_pushplus_sends_configured_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    _Client.payloads = []
    monkeypatch.setattr(engine.httpx, "AsyncClient", _Client)

    channel = engine.PushPlusChannel("token", topic="1")

    assert await channel.send("模拟买入", "纸面交易") is True
    assert _Client.payloads[0]["topic"] == "1"


@pytest.mark.asyncio
async def test_pushplus_omits_empty_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    _Client.payloads = []
    monkeypatch.setattr(engine.httpx, "AsyncClient", _Client)

    channel = engine.PushPlusChannel("token")

    assert await channel.send("提醒", "个人消息") is True
    assert "topic" not in _Client.payloads[0]
