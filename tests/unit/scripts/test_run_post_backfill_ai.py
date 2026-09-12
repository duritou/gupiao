from __future__ import annotations

import asyncio

from scripts import run_post_backfill_ai


class _Result:
    def to_dict(self):
        return {"run_id": "run-new", "paper_trades": []}


class _Runner:
    def __init__(self):
        self.calls = []

    async def run_daily_pipeline(self, **kwargs):
        self.calls.append(kwargs)
        return _Result()


def test_worker_always_requests_research_only_pipeline(monkeypatch):
    import src.ai_os.pipeline_runner as pipeline_module

    runner = _Runner()
    monkeypatch.setattr(pipeline_module, "pipeline_runner", runner)

    payload = asyncio.run(run_post_backfill_ai._run())

    assert payload["status"] == "success"
    assert payload["execute_paper_trades"] is False
    assert runner.calls == [{
        "save_to_journal": True,
        "execute_paper_trades": False,
        "force_reanalysis": True,
        "research_window": "post_backfill",
    }]
