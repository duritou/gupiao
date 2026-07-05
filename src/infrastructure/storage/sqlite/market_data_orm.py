"""MarketData ORM Model"""

from sqlalchemy import Column, Integer, String, DateTime, BigInteger, Numeric, Float
from src.infrastructure.orm.base import Base


class MarketDataORM(Base):
    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(20), nullable=False, index=True)
    period = Column(String(10), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    open = Column(Numeric(12, 4), nullable=False)
    high = Column(Numeric(12, 4), nullable=False)
    low = Column(Numeric(12, 4), nullable=False)
    close = Column(Numeric(12, 4), nullable=False)
    volume = Column(BigInteger, nullable=False)
    amount = Column(Numeric(18, 2), default=0)
    turnover_rate = Column(Float)
    change_pct = Column(Float)
