"""Stock Domain ↔ StockORM 双向映射器"""

from __future__ import annotations

from src.domain.models.stock import Stock
from src.infrastructure.storage.sqlite.stock_orm import StockORM


class StockMapper:
    """Stock ↔ StockORM 映射器 — 纯函数，无副作用"""

    @staticmethod
    def to_domain(orm: StockORM) -> Stock:
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
