"""Provider 注册 — 应用启动时的依赖装配

所有 Singleton / Factory 在此注册。
Phase 0 内容较少，随 Phase 递增逐步充实。
"""

from __future__ import annotations

from loguru import logger

from config.settings import Settings, settings
from src.domain.ports.event_bus_port import EventBusPort
from src.infrastructure.container.container import Container
from src.infrastructure.eventbus.memory_bus import MemoryEventBus
from src.infrastructure.metrics.collector import MetricsCollector, metrics
from src.infrastructure.logging.setup import setup_logging


def build_container() -> Container:
    """构建 DI 容器 — 注册所有基础设施组件"""

    container = Container()

    # ---- 配置 ----
    container.singleton(Settings, lambda: settings)

    # ---- 日志 ----
    setup_logging()
    logger.info("Building application container...")

    # ---- 指标 ----
    container.singleton(MetricsCollector, lambda: metrics)

    # ---- EventBus ----
    container.singleton(
        EventBusPort,
        lambda: MemoryEventBus(max_queue_size=settings.EVENT_BUS_MAX_QUEUE_SIZE),
    )

    # ---- Phase 1+ 预留 ----
    # container.singleton(PluginRegistryPort, lambda: PluginRegistry(...))
    # container.singleton(DataSourcePort, lambda: MarketGateway(...))
    # container.singleton(RepositoryPort, lambda: StockRepository(...))

    logger.info("Container built: {} components registered", len(container._registry))
    return container
