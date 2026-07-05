"""通用类型定义"""

from typing import TypeVar, Generic

T = TypeVar("T")


class Result(Generic[T]):
    """统一结果类型 — 成功或失败"""

    def __init__(self, value: T | None = None, error: str | None = None):
        if value is not None and error is not None:
            raise ValueError("Result cannot have both value and error")
        if value is None and error is None:
            raise ValueError("Result must have either value or error")
        self._value = value
        self._error = error

    @classmethod
    def ok(cls, value: T) -> "Result[T]":
        return cls(value=value)

    @classmethod
    def fail(cls, error: str) -> "Result[T]":
        return cls(error=error)

    @property
    def is_ok(self) -> bool:
        return self._error is None

    @property
    def is_fail(self) -> bool:
        return self._error is not None

    @property
    def value(self) -> T:
        if self._error is not None:
            raise ValueError(f"Cannot get value from failed result: {self._error}")
        return self._value  # type: ignore

    @property
    def error(self) -> str:
        if self._error is None:
            raise ValueError("Cannot get error from successful result")
        return self._error


# 常用类型别名
StockCode = str
DateStr = str  # "2026-07-05"
Market = str   # "SH" / "SZ" / "BJ"
