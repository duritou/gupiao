"""StockRepository — 对外只暴露 Domain Model"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models.stock import Stock
from src.infrastructure.storage.sqlite.stock_orm import StockORM
from src.infrastructure.repositories.mappers.stock_mapper import StockMapper


class StockRepository:
    """股票仓储 — 外部只看到 Stock (Domain)，ORM 完全封装"""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._mapper = StockMapper()

    async def find_by_id(self, entity_id: int) -> Optional[Stock]:
        result = await self._session.execute(
            select(StockORM).where(StockORM.id == entity_id)
        )
        orm = result.scalar_one_or_none()
        return self._mapper.to_domain(orm) if orm else None

    async def find_by_code(self, code: str) -> Optional[Stock]:
        result = await self._session.execute(
            select(StockORM).where(StockORM.code == code)
        )
        orm = result.scalar_one_or_none()
        return self._mapper.to_domain(orm) if orm else None

    async def find_all(
        self,
        market: Optional[str] = None,
        status: str = "active",
        offset: int = 0,
        limit: int = 100,
    ) -> list[Stock]:
        query = select(StockORM).where(StockORM.status == status)
        if market:
            query = query.where(StockORM.market == market)
        query = query.offset(offset).limit(limit)
        result = await self._session.execute(query)
        return [self._mapper.to_domain(orm) for orm in result.scalars().all()]

    async def save(self, entity: Stock) -> Stock:
        orm = self._mapper.to_orm(entity)
        self._session.add(orm)
        await self._session.flush()
        return self._mapper.to_domain(orm)

    async def save_batch(self, entities: list[Stock]) -> list[Stock]:
        for entity in entities:
            orm = self._mapper.to_orm(entity)
            self._session.add(orm)
        await self._session.flush()
        return entities

    async def delete(self, entity_id: int) -> bool:
        result = await self._session.execute(
            select(StockORM).where(StockORM.id == entity_id)
        )
        orm = result.scalar_one_or_none()
        if orm:
            await self._session.delete(orm)
            return True
        return False

    async def count(self, market: Optional[str] = None) -> int:
        from sqlalchemy import func
        query = select(func.count()).select_from(StockORM)
        if market:
            query = query.where(StockORM.market == market)
        result = await self._session.execute(query)
        return result.scalar_one()
