"""Stock ORM Model — 纯表映射"""

from sqlalchemy import Column, Integer, String, Date, DateTime, BigInteger
from src.infrastructure.orm.base import Base


class StockORM(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, unique=True, index=True)
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
