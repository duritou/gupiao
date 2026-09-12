from types import SimpleNamespace

import pytest

import src.ai_os.pipeline_runner as pipeline_module
from src.api.routes.ai_os_routes import run_ai_pipeline


def test_force_reanalysis_bypasses_same_day_cache_and_budget():
    candidates = [{"stock_code": "000001.SZ"}, {"stock_code": "600000.SH"}]
    cache = {"000001.SZ": {"available": True}}

    reusable, missing, skipped = pipeline_module._deep_analysis_plan(
        candidates,
        cache,
        deep_target=2,
        daily_deep_successes=2,
        daily_deep_attempts=4,
        force_reanalysis=True,
    )

    assert reusable == {}
    assert [item["stock_code"] for item in missing] == [
        "000001.SZ",
        "600000.SH",
    ]
    assert skipped == 0


@pytest.mark.asyncio
async def test_pipeline_runner_forwards_force_reanalysis_without_paper_trades(
    monkeypatch,
):
    calls = {}

    async def fake_run_once(
        self,
        codes=None,
        save_to_journal=True,
        execute_paper_trades=True,
        force_reanalysis=False,
    ):
        calls.update(
            execute_paper_trades=execute_paper_trades,
            force_reanalysis=force_reanalysis,
        )
        return SimpleNamespace()

    monkeypatch.setattr(
        pipeline_module.AIPipelineRunner,
        "_run_daily_pipeline_once",
        fake_run_once,
    )

    await pipeline_module.AIPipelineRunner().run_daily_pipeline(
        save_to_journal=False,
        execute_paper_trades=False,
        force_reanalysis=True,
    )

    assert calls == {"execute_paper_trades": False, "force_reanalysis": True}


@pytest.mark.asyncio
async def test_api_force_reanalysis_disables_paper_execution(monkeypatch):
    calls = {}

    class FakeResult:
        def to_dict(self):
            return {"market_data_quality": {}}

    async def fake_run_daily_pipeline(**kwargs):
        calls.update(kwargs)
        return FakeResult()

    monkeypatch.setattr(
        "src.ai_os.pipeline_runner.pipeline_runner.run_daily_pipeline",
        fake_run_daily_pipeline,
    )

    result = await run_ai_pipeline(force_reanalysis=True)

    assert result["reanalysis_mode"] == "forced"
    assert calls == {"force_reanalysis": True, "execute_paper_trades": False}
