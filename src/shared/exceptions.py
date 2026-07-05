"""自定义异常体系"""


class QuantAIError(Exception):
    """基础异常 — 所有自定义异常的父类"""
    pass


# ===== Domain 异常 =====

class DomainError(QuantAIError):
    """领域层异常基类"""
    pass


class InvalidStockCodeError(DomainError):
    """无效股票代码"""
    pass


class InvalidSignalError(DomainError):
    """无效信号"""
    pass


class ResearchSessionError(DomainError):
    """研究会话异常"""
    pass


# ===== Infrastructure 异常 =====

class InfrastructureError(QuantAIError):
    """基础设施层异常基类"""
    pass


class DataSourceError(InfrastructureError):
    """数据源异常"""
    pass


class DataSourceUnavailableError(DataSourceError):
    """数据源不可用"""
    pass


class ComplianceError(InfrastructureError):
    """合规检查异常"""
    pass


class LicenseDeniedError(ComplianceError):
    """许可证拒绝"""
    pass


class RateLimitExceededError(ComplianceError):
    """速率限制超限"""
    pass


# ===== Plugin 异常 =====

class PluginError(QuantAIError):
    """插件异常基类"""
    pass


class PluginValidationError(PluginError):
    """插件校验失败"""
    pass


class PluginVersionError(PluginError):
    """插件版本不兼容"""
    pass


class PluginNotFoundError(PluginError):
    """插件未找到"""
    pass


# ===== Event 异常 =====

class EventError(QuantAIError):
    """事件异常基类"""
    pass


class EventSerializationError(EventError):
    """事件序列化失败"""
    pass


# ===== Agent 异常 =====

class AgentError(QuantAIError):
    """Agent 异常基类"""
    pass


class AgentExecutionError(AgentError):
    """Agent 执行失败"""
    pass


class AgentReviewRejectedError(AgentError):
    """Reviewer 驳回 Analyst 输出"""
    pass
