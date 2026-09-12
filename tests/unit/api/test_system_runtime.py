import pytest

from src.api.routes import system_routes


@pytest.mark.asyncio
async def test_runtime_route_exposes_frozen_process_identity(monkeypatch):
    expected = {
        "managed": True,
        "deployment_ready": True,
        "release_id": "test-release",
        "artifact_hash": "abc",
        "disk_drift": False,
        "pid": 123,
    }
    def fake_startup_identity():
        return expected

    thread_calls = []

    async def fake_to_thread(function, *args, **kwargs):
        thread_calls.append(function)
        return function(*args, **kwargs)

    monkeypatch.setattr(
        "src.infrastructure.runtime_identity.startup_identity",
        fake_startup_identity,
    )
    monkeypatch.setattr(system_routes.asyncio, "to_thread", fake_to_thread)

    result = await system_routes.runtime_identity()

    assert result is expected
    assert result["release_id"] == "test-release"
    assert result["disk_drift"] is False
    assert thread_calls == [fake_startup_identity]
