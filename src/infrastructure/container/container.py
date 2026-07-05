"""轻量 DI Container — Phase 0

原则:
  - 不引入第三方 DI 框架（punq/dependency-injector 等 Phase 12 再说）
  - 支持 Singleton / Factory 两种生命周期
  - 支持简单的类型解析
  - 所有注册在 app 启动时完成，运行时只 resolve
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

T = TypeVar("T")


class Container:
    """轻量依赖注入容器

    使用:
      container = Container()

      # 注册
      container.singleton(Settings, lambda: Settings())
      container.singleton(EventBusPort, lambda: MemoryEventBus())

      # 解析
      settings = container.resolve(Settings)
      bus = container.resolve(EventBusPort)
    """

    def __init__(self):
        self._registry: dict[type, Callable[[], Any]] = {}
        self._instances: dict[type, Any] = {}

    # ===== 注册 =====

    def singleton(self, interface: type[T], factory: Callable[[], T]) -> None:
        """注册单例 — 全局只有一个实例"""
        self._registry[interface] = factory

    def factory(self, interface: type[T], factory: Callable[[], T]) -> None:
        """注册工厂 — 每次 resolve 创建新实例"""
        self._registry[interface] = factory
        # 标记为非单例：通过 _is_factory set 来跟踪
        if not hasattr(self, "_factories"):
            self._factories: set[type] = set()
        self._factories.add(interface)

    # ===== 解析 =====

    def resolve(self, interface: type[T]) -> T:
        """解析依赖"""
        if interface not in self._registry:
            raise ContainerError(f"未注册的类型: {interface.__name__}")

        # 非单例：每次创建新实例
        if hasattr(self, "_factories") and interface in self._factories:
            return self._registry[interface]()  # type: ignore

        # 单例：缓存
        if interface not in self._instances:
            self._instances[interface] = self._registry[interface]()
        return self._instances[interface]  # type: ignore

    def is_registered(self, interface: type) -> bool:
        """检查类型是否已注册"""
        return interface in self._registry

    # ===== 生命周期 =====

    async def shutdown(self) -> None:
        """关闭容器 — 调用所有实现了 shutdown 的单例"""
        for instance in self._instances.values():
            if hasattr(instance, "shutdown") and callable(instance.shutdown):
                try:
                    await instance.shutdown()
                except Exception:
                    pass
        self._instances.clear()
        self._registry.clear()


class ContainerError(Exception):
    """容器异常"""
    pass
