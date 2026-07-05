"""Agent 基类 — 所有 Agent 遵循此协议

每个 Agent:
  - 接收 AgentContext (上一阶段输出 + 可用工具)
  - 输出 AgentResult (结构化结果 + 思考过程)
  - 可独立选择 LLM 或纯规则模式
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class AgentMode(Enum):
    RULE = "rule"       # 纯规则，不调 LLM
    LLM = "llm"         # 调用 LLM


@dataclass
class AgentContext:
    """Agent 执行上下文 — 上游 Agent 的输出 + 可用工具"""

    session_id: str = ""
    task_description: str = ""
    input_data: dict = field(default_factory=dict)    # 上一阶段输出
    available_tools: list[str] = field(default_factory=list)
    knowledge_context: str = ""                        # 知识库上下文（纯文本）
    budget_tokens: int = 2000


@dataclass
class AgentResult:
    """Agent 执行结果"""

    success: bool = True
    agent_name: str = ""
    output: dict = field(default_factory=dict)         # 结构化输出
    thinking_trace: str = ""                           # 思考过程（可审计）
    tokens_used: int = 0
    tools_called: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class BaseAgent(ABC):
    """Agent 基类"""

    name: str = "base"
    description: str = ""
    mode: AgentMode = AgentMode.RULE
    llm_model: str = ""                                # LLM 模式下使用的模型

    @abstractmethod
    async def execute(self, context: AgentContext) -> AgentResult:
        """执行 Agent 任务"""
        ...

    def get_system_prompt(self) -> str:
        """获取 Agent 的系统提示词（LLM 模式使用）"""
        return ""

    def _ok(self, output: dict, thinking: str = "", tokens: int = 0) -> AgentResult:
        return AgentResult(
            success=True, agent_name=self.name,
            output=output, thinking_trace=thinking, tokens_used=tokens,
        )

    def _fail(self, error: str, thinking: str = "") -> AgentResult:
        return AgentResult(
            success=False, agent_name=self.name,
            errors=[error], thinking_trace=thinking,
        )
