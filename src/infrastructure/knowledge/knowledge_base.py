"""KnowledgeBase — 统一知识库入口

协调 Loader → Indexer → Search，支持热重载。
"""

from __future__ import annotations

from loguru import logger

from src.infrastructure.knowledge.loader import KnowledgeLoader, KnowledgeEntry
from src.infrastructure.knowledge.indexer import KnowledgeIndexer
from src.infrastructure.knowledge.search import KnowledgeSearch


class KnowledgeBase:
    """统一知识库"""

    def __init__(self, base_path: str = "knowledge"):
        self._loader = KnowledgeLoader(base_path)
        self._indexer = KnowledgeIndexer()
        self._search = KnowledgeSearch(self._indexer)
        self._loaded = False

    # ===== 加载 =====

    async def load(self) -> int:
        """加载所有知识 → 构建索引 → 返回条目数"""
        entries = await self._loader.load_all()
        count = self._indexer.build(entries)
        self._loaded = True
        logger.info("KnowledgeBase loaded: {} entries, {} categories",
                     count, len(self._indexer.categories))
        return count

    async def reload(self) -> int:
        """热重载 — 重新扫描文件 + 重建索引"""
        logger.info("KnowledgeBase reloading...")
        return await self.load()

    # ===== 搜索 =====

    def search(
        self, query: str, category: str | None = None, top_k: int = 10
    ) -> list[KnowledgeEntry]:
        """搜索知识"""
        self._ensure_loaded()
        return self._search.search(query, category, top_k)

    def search_by_tag(self, tag: str) -> list[KnowledgeEntry]:
        self._ensure_loaded()
        return self._search.search_by_tag(tag)

    def search_by_category(self, category: str) -> list[KnowledgeEntry]:
        self._ensure_loaded()
        return self._search.search_by_category(category)

    # ===== 查询 =====

    def get(self, entry_id: str) -> KnowledgeEntry | None:
        self._ensure_loaded()
        return self._indexer.get_by_id(entry_id)

    @property
    def categories(self) -> list[str]:
        self._ensure_loaded()
        return self._indexer.categories

    @property
    def tags(self) -> list[str]:
        self._ensure_loaded()
        return self._indexer.all_tags

    @property
    def entry_count(self) -> int:
        self._ensure_loaded()
        return self._indexer.entry_count

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            raise KnowledgeNotLoadedError("KnowledgeBase not loaded. Call await kb.load() first.")


class KnowledgeNotLoadedError(Exception):
    pass
