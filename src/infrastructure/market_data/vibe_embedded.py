"""Embedded access to Vibe Research data modules.

The Vibe backend remains independently runnable, but its synchronous data
modules can also be loaded by Adaptive.  This keeps one process from needing
to make a loopback HTTP request to another process for every data read.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path
from typing import Any


class EmbeddedVibeService:
    """Lazy loader for Vibe's reusable, non-FastAPI data modules."""

    def __init__(self, backend_root: Path | None = None):
        self.backend_root = backend_root or self._discover_backend_root()
        self._modules: dict[str, Any] = {}

    @staticmethod
    def _discover_backend_root() -> Path:
        """Find the shared Vibe backend from both worktree and release layouts."""
        configured = str(
            os.getenv("VIBE_BACKEND_ROOT")
            or os.getenv("VIBE_RESEARCH_BACKEND")
            or ""
        ).strip()
        if configured:
            return Path(configured).expanduser().resolve()

        candidates = [
            parent / "vibe-research" / "backend"
            for parent in Path(__file__).resolve().parents
        ]
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return candidates[0]

    def _load_module(self, module_name: str) -> Any:
        if not self.backend_root.exists():
            raise RuntimeError(f"Vibe backend not found: {self.backend_root}")
        backend = str(self.backend_root)
        if backend not in sys.path:
            sys.path.insert(0, backend)
        module = self._modules.get(module_name)
        if module is None:
            module = importlib.import_module(module_name)
            self._modules[module_name] = module
        return module

    async def call(self, module_name: str, function_name: str, *args, **kwargs) -> Any:
        """Run a blocking Vibe data function off the Adaptive event loop."""
        def invoke():
            function = getattr(self._load_module(module_name), function_name)
            return function(*args, **kwargs)

        return await asyncio.to_thread(invoke)

    def get_function(self, module_name: str, function_name: str):
        """Return a synchronous function for routes that need file responses."""
        return getattr(self._load_module(module_name), function_name)


_service: EmbeddedVibeService | None = None


def get_embedded_vibe_service() -> EmbeddedVibeService:
    global _service
    if _service is None:
        _service = EmbeddedVibeService()
    return _service
