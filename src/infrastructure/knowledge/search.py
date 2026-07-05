"""Knowledge Search — 搜索接口"""

from __future__ import annotations

from src.infrastructure.knowledge.loader import KnowledgeEntry
from src.infrastructure.knowledge.indexer import KnowledgeIndexer


class KnowledgeSearch:
    """知识搜索 — 基于内存索引"""

    def __init__(self, indexer: KnowledgeIndexer):
        self._indexer = indexer

    def search(
        self,
        query: str,
        category: str | None = None,
        top_k: int = 10,
    ) -> list[KnowledgeEntry]:
        """关键词搜索"""
        words = self._indexer.tokenize(query)
        if not words:
            return []

        scored: dict[str, int] = {}
        keyword_index = self._indexer.get_keyword_ids()

        for word in words:
            for entry_id in keyword_index.get(word, []):
                # 类别过滤
                if category:
                    entry = self._indexer.get_by_id(entry_id)
                    if entry and entry.category != category:
                        continue
                scored[entry_id] = scored.get(entry_id, 0) + 1

        sorted_ids = sorted(scored.items(), key=lambda x: x[1], reverse=True)
        results = []
        for eid, score in sorted_ids[:top_k]:
            entry = self._indexer.get_by_id(eid)
            if entry:
                entry.metadata["_search_score"] = score
                results.append(entry)

        return results

    def search_by_tag(self, tag: str) -> list[KnowledgeEntry]:
        """按标签搜索"""
        return self._indexer.get_by_tag(tag)

    def search_by_category(self, category: str) -> list[KnowledgeEntry]:
        """按分类搜索"""
        return self._indexer.get_by_category(category)
