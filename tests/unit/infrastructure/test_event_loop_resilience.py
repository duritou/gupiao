import asyncio
import threading
import urllib.request

import pytest

from src.infrastructure.market_data import source_manager as source_module


@pytest.mark.asyncio
async def test_fetch_url_bytes_does_not_block_event_loop(monkeypatch):
    release_read = threading.Event()
    read_started = threading.Event()

    class SlowResponse:
        def read(self) -> bytes:
            read_started.set()
            release_read.wait(2)
            return b"payload"

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *_args, **_kwargs: SlowResponse()
    )

    request = urllib.request.Request("https://example.invalid")
    task = asyncio.create_task(source_module._fetch_url_bytes(request, timeout=1.0))
    assert await asyncio.to_thread(read_started.wait, 0.5)

    # If response.read() runs on the event loop this sleep cannot complete.
    await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.1)
    release_read.set()
    assert await task == b"payload"


@pytest.mark.asyncio
async def test_fetch_url_bytes_has_a_complete_exchange_deadline(monkeypatch):
    class SlowResponse:
        def read(self) -> bytes:
            threading.Event().wait(1)
            return b"late"

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *_args, **_kwargs: SlowResponse()
    )
    request = urllib.request.Request("https://example.invalid")

    with pytest.raises(asyncio.TimeoutError):
        await source_module._fetch_url_bytes(request, timeout=0.01)
