"""DI Container 单元测试"""

import pytest

from src.infrastructure.container.container import Container, ContainerError


class FakeService:
    """测试用的假服务"""
    def __init__(self, name: str = "default"):
        self.name = name
        self.initialized = True


class FakeEventBus:
    """测试用的假 EventBus"""
    def __init__(self):
        self.started = False

    async def shutdown(self):
        self.started = False


class TestContainer:
    """Container 单元测试"""

    @pytest.fixture
    def container(self):
        return Container()

    def test_singleton_returns_same_instance(self, container):
        container.singleton(FakeService, lambda: FakeService("singleton"))
        a = container.resolve(FakeService)
        b = container.resolve(FakeService)
        assert a is b
        assert a.name == "singleton"

    def test_factory_returns_new_instance(self, container):
        counter = [0]

        def make_fake():
            counter[0] += 1
            return FakeService(f"factory_{counter[0]}")

        container.factory(FakeService, make_fake)
        a = container.resolve(FakeService)
        b = container.resolve(FakeService)

        assert a is not b
        assert a.name == "factory_1"
        assert b.name == "factory_2"

    def test_resolve_unregistered_raises(self, container):
        with pytest.raises(ContainerError, match="未注册"):
            container.resolve(FakeService)

    def test_is_registered(self, container):
        assert not container.is_registered(FakeService)
        container.singleton(FakeService, lambda: FakeService())
        assert container.is_registered(FakeService)

    def test_singleton_lazy_creation(self, container):
        """单例在第一次 resolve 时才创建"""
        created = [False]

        def lazy_factory():
            created[0] = True
            return FakeService()

        container.singleton(FakeService, lazy_factory)
        assert not created[0]  # 还未创建

        container.resolve(FakeService)
        assert created[0]  # 现在创建了

    def test_multiple_types(self, container):
        """不同类型独立解析"""
        class ServiceA: pass
        class ServiceB: pass

        container.singleton(ServiceA, lambda: ServiceA())
        container.singleton(ServiceB, lambda: ServiceB())

        a = container.resolve(ServiceA)
        b = container.resolve(ServiceB)

        assert isinstance(a, ServiceA)
        assert isinstance(b, ServiceB)

    @pytest.mark.asyncio
    async def test_shutdown_calls_shutdown_on_instances(self, container):
        bus = FakeEventBus()
        container.singleton(FakeEventBus, lambda: bus)
        container.resolve(FakeEventBus)

        await container.shutdown()
        # shutdown 被调用，容器清空
        assert not container.is_registered(FakeEventBus)

    @pytest.mark.asyncio
    async def test_shutdown_handles_errors(self, container):
        """有实例的 shutdown 抛异常不影响其他"""

        class BadService:
            async def shutdown(self):
                raise RuntimeError("boom")

        container.singleton(BadService, lambda: BadService())
        container.resolve(BadService)

        # 不应抛异常
        await container.shutdown()
