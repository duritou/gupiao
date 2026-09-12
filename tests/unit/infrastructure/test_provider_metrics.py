from src.infrastructure.market_data.provider_metrics import ProviderReliabilityEngine


def test_provider_reliability_engine_can_reset_runtime_state():
    engine = ProviderReliabilityEngine()
    engine.record_call("tickflow", "quote", False, 100.0, "test failure")

    engine.reset_runtime_state()

    assert engine.get_metrics_summary("tickflow") == {
        "provider": "tickflow",
        "available": False,
    }
