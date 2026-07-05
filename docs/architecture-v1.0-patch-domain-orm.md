# v1.0 Patch: Domain Model ↔ ORM 彻底解耦

> **优先级**: 进入 Phase 0 开发前完成  
> **影响**: `domain/models/` `infrastructure/orm/` `infrastructure/repositories/`  
> **原则**: Repository 外面永远只看到 Domain Model，ORM 细节完全封装在内部

---

## 问题

当前 v1.0 文档中，Repository 示例存在模糊边界：

```python
# 问题代码
class StockRepository:
    async def find_by_code(self, code: str) -> Stock | None:
        result = await self._session.execute(
            select(Stock).where(Stock.code == code)  # ← Stock 是 Domain 还是 ORM？
        )
```

两种坏情况必居其一：
- `Stock` 是 Domain Model → 它依赖了 SQLAlchemy（`select()`/`.where()`）
- `Stock` 是 ORM Model → Repository 向上层暴露了 ORM 对象

**都不对。**

---

## 方案：三层模型分离

```
┌─────────────────────────────────────────────┐
│              UseCase / Domain Service        │
│                 只看到 Domain Model           │
└──────────────────────┬──────────────────────┘
                       │
┌──────────────────────┴──────────────────────┐
│              Repository (抽象)               │
│        输入/输出: 永远是 Domain Model          │
│        内部: Mapper 做 Domain ↔ ORM 转换      │
└──────────────────────┬──────────────────────┘
                       │
┌──────────────────────┴──────────────────────┐
│              Mapper 层                       │
│    Domain Model ←→ Persistence Model (ORM)  │
└──────────────────────┬──────────────────────┘
                       │
┌──────────────────────┴──────────────────────┐
│         Persistence Model (SQLAlchemy ORM)   │
│              纯数据映射，不含业务逻辑           │
└──────────────────────┬──────────────────────┘
                       │
┌──────────────────────┴──────────────────────┐
│              Database                        │
└─────────────────────────────────────────────┘
```

---

## 实现

### 1. Domain Model（纯 Python，零 ORM 依赖）

```python
# src/domain/models/stock.py
# 不 import 任何 SQLAlchemy / ORM 相关内容

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

@dataclass
class Stock:
    """股票领域模型 —— 纯 Python，持久化无关"""
    id: Optional[int] = None
    code: str = ""
    name: str = ""
    market: str = ""            # SH / SZ / BJ
    industry: str = ""
    sub_industry: str = ""
    listing_date: Optional[date] = None
    delisting_date: Optional[date] = None
    status: str = "active"
    total_shares: Optional[int] = None
    float_shares: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # ===== 领域方法（业务逻辑在此，不涉及持久化）=====

    @property
    def is_active(self) -> bool:
        return self.status == "active" and self.delisting_date is None

    @property
    def market_display(self) -> str:
        return {"SH": "上海", "SZ": "深圳", "BJ": "北交所"}.get(self.market, self.market)

    def suspend(self) -> None:
        if self.status != "active":
            raise ValueError(f"无法停牌: 当前状态为 {self.status}")
        self.status = "suspended"

    def resume(self) -> None:
        if self.status != "suspended":
            raise ValueError(f"无法复牌: 当前状态为 {self.status}")
        self.status = "active"
```

### 2. Persistence Model（SQLAlchemy ORM，纯数据映射）

```python
# src/infrastructure/storage/sqlite/stock_orm.py
# 只有表结构映射，不含任何业务逻辑

from sqlalchemy import Column, Integer, String, Date, DateTime, BigInteger
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class StockORM(Base):
    """股票 ORM 模型 —— 纯表映射，不含业务逻辑"""
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, unique=True)
    name = Column(String(50), nullable=False)
    market = Column(String(10), nullable=False)
    industry = Column(String(100))
    sub_industry = Column(String(100))
    listing_date = Column(Date)
    delisting_date = Column(Date)
    status = Column(String(20), default="active")
    total_shares = Column(BigInteger)
    float_shares = Column(BigInteger)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    # ⚠️ 这里不写任何业务方法
    # def is_active(self) → 错！放到 Domain Model
```

### 3. Mapper（Domain ↔ ORM 双向转换）

```python
# src/infrastructure/repositories/mappers/stock_mapper.py

from src.domain.models.stock import Stock
from src.infrastructure.storage.sqlite.stock_orm import StockORM

class StockMapper:
    """Stock Domain ↔ StockORM 双向映射器"""

    @staticmethod
    def to_domain(orm: StockORM) -> Stock:
        """ORM → Domain"""
        return Stock(
            id=orm.id,
            code=orm.code,
            name=orm.name,
            market=orm.market,
            industry=orm.industry or "",
            sub_industry=orm.sub_industry or "",
            listing_date=orm.listing_date,
            delisting_date=orm.delisting_date,
            status=orm.status or "active",
            total_shares=orm.total_shares,
            float_shares=orm.float_shares,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def to_orm(domain: Stock) -> StockORM:
        """Domain → ORM"""
        return StockORM(
            id=domain.id,
            code=domain.code,
            name=domain.name,
            market=domain.market,
            industry=domain.industry or None,
            sub_industry=domain.sub_industry or None,
            listing_date=domain.listing_date,
            delisting_date=domain.delisting_date,
            status=domain.status,
            total_shares=domain.total_shares,
            float_shares=domain.float_shares,
            created_at=domain.created_at,
            updated_at=domain.updated_at,
        )
```

### 4. Repository（对外只暴露 Domain）

```python
# src/infrastructure/repositories/stock_repository.py

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.domain.models.stock import Stock
from src.domain.ports.repository_port import RepositoryPort
from src.infrastructure.storage.sqlite.stock_orm import StockORM
from src.infrastructure.repositories.mappers.stock_mapper import StockMapper

class StockRepository(RepositoryPort[Stock]):
    """股票仓储 —— 外部只看到 Stock (Domain)"""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._mapper = StockMapper()

    async def find_by_id(self, entity_id: int) -> Stock | None:
        # 1. 用 ORM 查询
        result = await self._session.execute(
            select(StockORM).where(StockORM.id == entity_id)
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        # 2. Mapper 转换 → 返回 Domain
        return self._mapper.to_domain(orm)

    async def find_by_code(self, code: str) -> Stock | None:
        result = await self._session.execute(
            select(StockORM).where(StockORM.code == code)
        )
        orm = result.scalar_one_or_none()
        return self._mapper.to_domain(orm) if orm else None

    async def save(self, entity: Stock) -> Stock:
        # 1. Domain → ORM
        orm = self._mapper.to_orm(entity)
        # 2. 持久化
        self._session.add(orm)
        await self._session.flush()
        # 3. ORM → Domain（回填 ID）
        return self._mapper.to_domain(orm)

    async def find_all(
        self,
        filters: dict | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Stock]:
        query = select(StockORM)
        if filters:
            for key, value in filters.items():
                query = query.where(getattr(StockORM, key) == value)
        query = query.offset(offset).limit(limit)
        result = await self._session.execute(query)
        orms = result.scalars().all()
        return [self._mapper.to_domain(orm) for orm in orms]

    async def delete(self, entity_id: int) -> bool:
        result = await self._session.execute(
            select(StockORM).where(StockORM.id == entity_id)
        )
        orm = result.scalar_one_or_none()
        if orm:
            await self._session.delete(orm)
            return True
        return False

    async def count(self, filters: dict | None = None) -> int:
        from sqlalchemy import func
        query = select(func.count()).select_from(StockORM)
        if filters:
            for key, value in filters.items():
                query = query.where(getattr(StockORM, key) == value)
        result = await self._session.execute(query)
        return result.scalar_one()
```

### 5. 目录确认

```
src/infrastructure/
│
├── repositories/                  # 抽象接口 + 实现
│   ├── base.py                    #   RepositoryPort[T]
│   ├── stock_repository.py        #   对外的 StockRepository
│   ├── signal_repository.py
│   ├── report_repository.py
│   ├── research_memory_repository.py
│   ├── unit_of_work.py            #   ① UnitOfWork (v1.1)
│   └── mappers/                   #   Domain ↔ ORM 映射器
│       ├── __init__.py
│       ├── stock_mapper.py
│       ├── signal_mapper.py
│       └── ...
│
├── storage/                       # 持久化后端 (原 orm/ → 改名)
│   ├── base.py                    #   ORM Base
│   ├── sqlite/
│   │   ├── stock_orm.py
│   │   ├── signal_orm.py
│   │   └── ...
│   ├── postgresql/
│   └── duckdb/
```

---

## 边界规则（强制）

```
✅ 允许:
  UseCase         → import Stock (domain)
  DomainService   → import Stock (domain)
  Repository      → import Stock (domain) + StockORM (storage) + StockMapper
  Mapper          → import Stock (domain) + StockORM (storage)
  Stock (domain)  → import 标准库 + 领域异常

❌ 禁止:
  UseCase         → import StockORM        ← 泄漏 ORM
  DomainService   → import StockORM        ← 泄漏 ORM
  Stock (domain)  → import sqlalchemy     ← 领域污染
  Stock (domain)  → import StockORM       ← 循环依赖
  StockORM        → import Stock (domain) ← ORM 不依赖 Domain
```

---

## 目录重命名: orm/ → storage/

```
v1.0 (当前):
  infrastructure/orm/sqlite/...

v1.0 Patch (修正后):
  infrastructure/storage/sqlite/...
  infrastructure/storage/postgresql/...
  infrastructure/storage/duckdb/
  infrastructure/storage/clickhouse/

原因: DuckDB/ClickHouse 不是 ORM，storage/ 语义更准确
```

---

> **Patch 完成。Repository 只暴露 Domain Model，ORM 完全封装在内部。**
