"""Shared deterministic evidence dossier with explicit failure semantics."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

Fetcher = Callable[[], Awaitable[Any]]
SCHEMA_VERSION = 1


def _has_content(payload: Any) -> bool:
    if payload is None:
        return False
    if isinstance(payload, list | tuple | set | str):
        return bool(payload)
    if isinstance(payload, dict):
        content = {key: value for key, value in payload.items() if key != "_meta"}
        meaningful = [
            value for key, value in content.items()
            if key not in {"count", "updated_at"}
        ]
        return any(bool(value) for value in meaningful)
    return True


def normalize_evidence(label: str, payload: Any) -> dict[str, Any]:
    """Distinguish valid content, legitimate empty results, and source failure."""
    now = datetime.now().astimezone().isoformat()
    metadata = payload.get("_meta") if isinstance(payload, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    error = str(metadata.get("error") or "")
    explicitly_available = metadata.get("available")
    content_available = _has_content(payload)
    if error or explicitly_available is False:
        status = "unavailable"
    elif content_available:
        status = "available"
    else:
        status = "empty"
    return {
        "label": label,
        "status": status,
        "available": status == "available",
        "stale": False,
        "fetched_at": str(metadata.get("fetched_at") or now),
        "error": error,
        "payload": payload,
    }


class EvidenceDossierCache:
    """Atomic last-good cache; failed reads never overwrite good evidence."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema_version") == SCHEMA_VERSION:
                return payload
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        return {"schema_version": SCHEMA_VERSION, "items": {}}

    def remember_or_stale(self, key: str, evidence: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            cache = self._read()
            if evidence["status"] == "available":
                cache["items"][key] = deepcopy(evidence)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(self.path.suffix + ".tmp")
                temporary.write_text(
                    json.dumps(cache, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                os.replace(temporary, self.path)
                return evidence
            previous = (cache.get("items") or {}).get(key)
            if previous and evidence["status"] == "unavailable":
                stale = deepcopy(previous)
                stale.update({
                    "status": "stale",
                    "stale": True,
                    "current_error": evidence.get("error") or "source_unavailable",
                })
                return stale
            return evidence


async def collect_evidence_dossier(
    stock_code: str,
    fetchers: list[tuple[str, Fetcher]],
    cache: EvidenceDossierCache,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Collect serially so every downstream role sees one frozen dossier."""
    items: dict[str, Any] = {}
    for label, fetch in fetchers:
        try:
            payload = await asyncio.wait_for(fetch(), timeout=timeout)
            normalized = normalize_evidence(label, payload)
        except Exception as exc:
            normalized = normalize_evidence(
                label,
                {"_meta": {"available": False, "error": f"{type(exc).__name__}: {exc}"}},
            )
        items[label] = cache.remember_or_stale(f"{stock_code}:{label}", normalized)
    return {
        "schema_version": SCHEMA_VERSION,
        "stock_code": stock_code,
        "frozen_at": datetime.now().astimezone().isoformat(),
        "items": items,
        "summary": {
            status: sum(item["status"] == status for item in items.values())
            for status in ("available", "empty", "unavailable", "stale")
        },
    }
