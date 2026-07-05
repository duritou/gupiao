"""pytest 全局 fixtures"""

import pytest

from src.infrastructure.metrics.collector import metrics


@pytest.fixture(autouse=True)
def reset_metrics():
    """每个测试前重置指标"""
    metrics.reset()
    yield
