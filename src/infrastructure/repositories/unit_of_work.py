"""Unit of Work — 事务边界

UseCase 通过 UoW 操作多个 Repository，统一 commit/rollback。
Repository 不自己 commit。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.repositories.stock_repository import StockRepository


class UnitOfWork:
    """事务边界 — async context manager

    使用:
      async with UnitOfWork(session_factory) as uow:
          stock = await uow.stocks.find_by_code("000001.SZ")
          await uow.stocks.save(new_stock)
          # 自动 commit；异常自动 rollback
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

        self.stocks: StockRepository | None = None

    async def __aenter__(self) -> "UnitOfWork":
        self._session = self._session_factory()
        self.stocks = StockRepository(self._session)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._session is None:
            return
        try:
            if exc_type is not None:
                await self._session.rollback()
            else:
                await self._session.commit()
        finally:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        if self._session:
            await self._session.commit()

    async def rollback(self) -> None:
        if self._session:
            await self._session.rollback()
