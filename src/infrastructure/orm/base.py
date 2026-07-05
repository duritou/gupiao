"""ORM 基类 — SQLAlchemy 2.0 异步引擎

Phase 0: SQLite + aiosqlite
Phase 3+: PostgreSQL + asyncpg
切换只改 DATABASE_URL
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config.settings import settings


class Base(DeclarativeBase):
    """ORM 基类 — 所有 ORM 模型继承此类"""
    pass


# 异步引擎
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DATABASE_ECHO,
    pool_size=settings.DATABASE_POOL_SIZE if "sqlite" not in settings.DATABASE_URL else 0,
)

# 异步 Session 工厂
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    """获取数据库 Session — 用于依赖注入"""
    async with async_session_factory() as session:
        yield session


async def create_all_tables() -> None:
    """创建所有表 — 开发环境使用，生产用 Alembic"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all_tables() -> None:
    """删除所有表 — 仅测试环境"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def close_engine() -> None:
    """关闭数据库引擎"""
    await engine.dispose()
