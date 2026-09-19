"""pytest 全局 fixtures"""

import os
import tempfile
from pathlib import Path

import pytest

# Set before importing application singletons. A partially mocked pipeline can
# otherwise write synthetic candidates/checkpoints into the production default.
_test_storage_root = Path(tempfile.mkdtemp(prefix="adaptive-pytest-"))
os.environ["ADAPTIVE_MARKET_DB_PATH"] = str(_test_storage_root / "market_data.db")
os.environ["TUSHARE_BUDGET_DB_PATH"] = str(_test_storage_root / "tushare_budget.db")
os.environ["ADAPTIVE_DATABASE_URL"] = "sqlite+aiosqlite:///" + (
    _test_storage_root / "quant.db"
).as_posix()

from src.infrastructure.market_data.provider_metrics import reliability_engine  # noqa: E402


@pytest.fixture(autouse=True)
def reset_metrics():
    """每个测试前重置指标"""
    # Only the provider reliability counters are live; the v1.0
    # infrastructure/metrics collector was removed with the rest of that
    # architecture and had no production caller.
    reliability_engine.reset_runtime_state()
    yield
    reliability_engine.reset_runtime_state()
