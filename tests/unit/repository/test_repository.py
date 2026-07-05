"""Repository + UnitOfWork 集成测试"""

import pytest
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.domain.models.stock import Stock
from src.domain.models.market_data import MarketData
from src.infrastructure.orm.base import Base
from src.infrastructure.repositories.stock_repository import StockRepository
from src.infrastructure.repositories.unit_of_work import UnitOfWork


# ===== In-memory SQLite for tests =====

TEST_DATABASE_URL = "sqlite+aiosqlite://"


@pytest.fixture
async def engine():
    """创建内存 SQLite 引擎"""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def session_factory(engine):
    """创建 Session 工厂"""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def session(session_factory):
    """创建独立 Session"""
    async with session_factory() as s:
        yield s


# ===== StockRepository Tests =====

class TestStockRepository:
    """StockRepository CRUD 测试"""

    @pytest.mark.asyncio
    async def test_save_and_find_by_code(self, session):
        repo = StockRepository(session)
        stock = Stock(code="000001.SZ", name="平安银行", market="SZ", status="active")

        saved = await repo.save(stock)
        await session.commit()

        assert saved.id is not None
        found = await repo.find_by_code("000001.SZ")
        assert found is not None
        assert found.name == "平安银行"
        assert found.code == "000001.SZ"

    @pytest.mark.asyncio
    async def test_find_by_id(self, session):
        repo = StockRepository(session)
        stock = Stock(code="000002.SZ", name="万科A", market="SZ")
        saved = await repo.save(stock)
        await session.commit()

        found = await repo.find_by_id(saved.id)  # type: ignore
        assert found is not None
        assert found.code == "000002.SZ"

    @pytest.mark.asyncio
    async def test_find_by_code_not_found(self, session):
        repo = StockRepository(session)
        found = await repo.find_by_code("NONEXISTENT")
        assert found is None

    @pytest.mark.asyncio
    async def test_find_all(self, session):
        repo = StockRepository(session)
        await repo.save(Stock(code="000001.SZ", name="A", market="SZ"))
        await repo.save(Stock(code="600000.SH", name="B", market="SH"))
        await session.commit()

        all_active = await repo.find_all()
        assert len(all_active) == 2

        sz_only = await repo.find_all(market="SZ")
        assert len(sz_only) == 1
        assert sz_only[0].code == "000001.SZ"

    @pytest.mark.asyncio
    async def test_save_batch(self, session):
        repo = StockRepository(session)
        stocks = [
            Stock(code="000001.SZ", name="A", market="SZ"),
            Stock(code="000002.SZ", name="B", market="SZ"),
            Stock(code="000003.SZ", name="C", market="SZ"),
        ]
        await repo.save_batch(stocks)
        await session.commit()

        count = await repo.count()
        assert count == 3

    @pytest.mark.asyncio
    async def test_delete(self, session):
        repo = StockRepository(session)
        saved = await repo.save(Stock(code="000001.SZ", name="test", market="SZ"))
        await session.commit()

        deleted = await repo.delete(saved.id)  # type: ignore
        assert deleted is True

        found = await repo.find_by_code("000001.SZ")
        assert found is None

    @pytest.mark.asyncio
    async def test_count(self, session):
        repo = StockRepository(session)
        assert await repo.count() == 0

        await repo.save(Stock(code="000001.SZ", name="A", market="SZ"))
        await repo.save(Stock(code="600000.SH", name="B", market="SH"))
        await session.commit()

        assert await repo.count() == 2
        assert await repo.count(market="SZ") == 1


# ===== UnitOfWork Tests =====

class TestUnitOfWork:
    """UnitOfWork 事务边界测试"""

    @pytest.mark.asyncio
    async def test_commit_on_success(self, session_factory):
        async with UnitOfWork(session_factory) as uow:
            stock = Stock(code="000001.SZ", name="平安银行", market="SZ")
            await uow.stocks.save(stock)  # type: ignore
        # 退出时自动 commit

        # 验证持久化
        async with UnitOfWork(session_factory) as uow:
            found = await uow.stocks.find_by_code("000001.SZ")  # type: ignore
            assert found is not None

    @pytest.mark.asyncio
    async def test_rollback_on_error(self, session_factory):
        class TestError(Exception):
            pass

        with pytest.raises(TestError):
            async with UnitOfWork(session_factory) as uow:
                stock = Stock(code="000002.SZ", name="test", market="SZ")
                await uow.stocks.save(stock)  # type: ignore
                raise TestError("boom")

        # 验证未持久化
        async with UnitOfWork(session_factory) as uow:
            found = await uow.stocks.find_by_code("000002.SZ")  # type: ignore
            assert found is None

    @pytest.mark.asyncio
    async def test_multiple_repos_same_transaction(self, session_factory):
        """同一 UoW 中多次操作在同一事务"""
        async with UnitOfWork(session_factory) as uow:
            repo = uow.stocks
            await repo.save(Stock(code="A", name="A", market="SZ"))  # type: ignore
            await repo.save(Stock(code="B", name="B", market="SZ"))  # type: ignore
        # 两条都 commit

        async with UnitOfWork(session_factory) as uow:
            count = await uow.stocks.count()  # type: ignore
            assert count == 2

    @pytest.mark.asyncio
    async def test_explicit_commit(self, session_factory):
        async with UnitOfWork(session_factory) as uow:
            await uow.stocks.save(Stock(code="C", name="C", market="SZ"))  # type: ignore
            await uow.commit()
            count = await uow.stocks.count()  # type: ignore
            assert count == 1


# ===== Domain Model Tests =====

class TestStockDomainModel:
    """Stock 领域模型纯逻辑测试（不涉及 DB）"""

    def test_is_active(self):
        s = Stock(code="000001.SZ", status="active")
        assert s.is_active is True

        s2 = Stock(code="000002.SZ", status="suspended")
        assert s2.is_active is False

    def test_market_display(self):
        assert Stock(code="000001.SZ", market="SZ").market_display == "深圳"
        assert Stock(code="600000.SH", market="SH").market_display == "上海"

    def test_equality_by_code(self):
        a = Stock(code="000001.SZ", name="A")
        b = Stock(code="000001.SZ", name="B")
        assert a == b

    def test_hash_by_code(self):
        s = Stock(code="000001.SZ")
        assert hash(s) == hash("000001.SZ")

    def test_id_none_for_new(self):
        s = Stock(code="000001.SZ")
        assert s.id is None


class TestMarketDataDomainModel:
    """MarketData 值对象测试"""

    def test_frozen(self):
        md = MarketData(
            stock_code="000001.SZ", period="1d",
            timestamp=datetime.now(),
            open=Decimal("10.0"), high=Decimal("11.0"),
            low=Decimal("9.5"), close=Decimal("10.5"),
            volume=1000000,
        )
        with pytest.raises(Exception):
            md.close = Decimal("11.0")  # type: ignore

    def test_defaults(self):
        md = MarketData(
            stock_code="000001.SZ", period="1d",
            timestamp=datetime.now(),
            open=Decimal("10"), high=Decimal("10"),
            low=Decimal("10"), close=Decimal("10"),
            volume=100,
        )
        assert md.amount == Decimal("0")
        assert md.turnover_rate is None
