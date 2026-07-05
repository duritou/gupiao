"""Test adapter for unit tests."""

from src.infrastructure.plugin_registry.manifest import PluginManifest
from src.shared.plugin_protocol import BasePlugin


class TestAdapter(BasePlugin):
    """Test data source adapter."""

    def __init__(self, manifest: PluginManifest):
        super().__init__(manifest)
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self) -> bool:
        self.initialized = True
        return True

    async def health_check(self) -> bool:
        return True

    async def shutdown(self) -> None:
        self.shutdown_called = True
