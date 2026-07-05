"""统一序列化基类"""

from __future__ import annotations

from abc import ABC
from dataclasses import asdict, is_dataclass
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from uuid import UUID
from pathlib import Path


class Serializable(ABC):
    """统一序列化基类 — 所有 Domain Object 继承此类

    自动处理: datetime / Decimal / UUID / Enum / Path / dataclass 嵌套
    """

    def to_dict(self) -> dict:
        return _to_dict(self)

    @classmethod
    def from_dict(cls, data: dict):
        return _from_dict(cls, data)


def _to_dict(obj) -> dict | list | str | int | float | bool | None:
    """递归序列化"""
    if isinstance(obj, Serializable):
        # Serializable 对象通过自身的 to_dict() 序列化
        # 直接遍历字段，避免与 is_dataclass 分支冲突导致无限递归
        result = {}
        for f in obj.__dataclass_fields__:
            result[f] = _to_dict(getattr(obj, f))
        return result
    if is_dataclass(obj) and not isinstance(obj, type) and not isinstance(obj, Serializable):
        result = {}
        for f in obj.__dataclass_fields__:
            result[f] = _to_dict(getattr(obj, f))
        return result
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dict(v) for v in obj]
    return obj


def _from_dict(cls, data: dict):
    """递归反序列化 — 简易版，Phase 6 后切换到 msgspec"""
    field_types = {f.name: f.type for f in cls.__dataclass_fields__.values()}
    kwargs = {}
    for key, value in data.items():
        if key in field_types:
            kwargs[key] = value
    return cls(**kwargs)
