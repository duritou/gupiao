"""追踪上下文 — 封装所有分布式追踪字段

v1.0: trace_id / span_id / correlation_id
v1.2: + traceparent / tracestate (W3C Trace Context)
v2+:  + baggage / sampling / tenant_id
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from src.domain.events.core.serializable import Serializable


@dataclass(frozen=True)
class TraceContext(Serializable):
    """追踪上下文"""

    trace_id: str = field(default_factory=lambda: str(uuid4()))
    span_id: str = field(default_factory=lambda: str(uuid4()))
    parent_span_id: str = ""
    correlation_id: str = ""

    # v1.2 预留（当前为空）
    traceparent: str = ""
    tracestate: str = ""
    sampled: bool = True

    # ===== Factory Methods =====

    @classmethod
    def root(cls, correlation_id: str = "") -> "TraceContext":
        """创建根 Trace — 新请求入口"""
        return cls(correlation_id=correlation_id)

    @classmethod
    def child(cls, parent: "TraceContext") -> "TraceContext":
        """创建子 Span — 同一调用链内使用

        Scanner → Research → Report: 全部用 child()
        继承 trace_id，新 span_id，设置 parent_span_id
        """
        return cls(
            trace_id=parent.trace_id,
            parent_span_id=parent.span_id,
            correlation_id=parent.correlation_id,
        )

    @classmethod
    def fork(cls, parent: "TraceContext") -> "TraceContext":
        """Fork 独立 Trace — 异步任务/新 Pipeline

        新 trace_id，非继承关系
        保留 correlation_id 用于业务关联
        """
        return cls(correlation_id=parent.correlation_id)
