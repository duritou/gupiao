"""事件类型注册表 — 按领域拆分，IDE 自动补全"""

from __future__ import annotations

import sys
from typing import Union

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """Python 3.10 兼容的 StrEnum"""
        pass


class SignalEventType(StrEnum):
    """信号领域事件"""
    SIGNAL_CREATED = "domain.signal.created"
    SIGNAL_BATCH_COMPLETED = "domain.signal.batch_completed"


class ResearchEventType(StrEnum):
    """研究领域事件"""
    RESEARCH_STARTED = "domain.research.started"
    RESEARCH_COMPLETED = "domain.research.completed"
    RESEARCH_FAILED = "domain.research.failed"


class ScannerEventType(StrEnum):
    """扫描领域事件"""
    SCANNER_STARTED = "scanner.started"
    SCANNER_COMPLETED = "scanner.completed"
    CANDIDATE_CREATED = "scanner.candidate.created"


class MemoryEventType(StrEnum):
    """记忆领域事件"""
    WATCHLIST_UPDATED = "domain.watchlist.updated"
    MEMORY_RECORDED = "domain.memory.recorded"


class KnowledgeEventType(StrEnum):
    """知识领域事件"""
    KNOWLEDGE_IMPORTED = "domain.knowledge.imported"
    KNOWLEDGE_UPDATED = "domain.knowledge.updated"


class SystemEventType(StrEnum):
    """系统事件"""
    HEARTBEAT = "system.heartbeat"
    SHUTDOWN = "system.shutdown"


# 联合类型
AnyEventType = Union[
    SignalEventType,
    ResearchEventType,
    ScannerEventType,
    MemoryEventType,
    KnowledgeEventType,
    SystemEventType,
]
