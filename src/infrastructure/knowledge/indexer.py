"""Knowledge Indexer — 构建内存搜索索引"""

from __future__ import annotations

from collections import defaultdict

from src.infrastructure.knowledge.loader import KnowledgeEntry


class KnowledgeIndexer:
    """知识索引器 — 内存版倒排索引

    Phase 4: 简易关键词匹配
    Phase 8+: SQLite FTS5 / Meilisearch / Vector DB
    """

    def __init__(self):
        self._entries: dict[str, KnowledgeEntry] = {}
        self._tag_index: dict[str, list[str]] = defaultdict(list)
        self._category_index: dict[str, list[str]] = defaultdict(list)
        self._keyword_index: dict[str, list[str]] = defaultdict(list)

    def build(self, entries: list[KnowledgeEntry]) -> int:
        """构建索引 — 返回索引条目数"""
        self._entries.clear()
        self._tag_index.clear()
        self._category_index.clear()
        self._keyword_index.clear()

        for entry in entries:
            self._entries[entry.id] = entry
            self._category_index[entry.category].append(entry.id)
            for tag in entry.tags:
                self._tag_index[tag.lower()].append(entry.id)
            for word in self.tokenize(entry.title + " " + entry.content):
                self._keyword_index[word].append(entry.id)

        return len(self._entries)

    def update(self, entry: KnowledgeEntry) -> None:
        """更新单个条目"""
        # 先移除旧索引
        old = self._entries.get(entry.id)
        if old:
            for tag in old.tags:
                self._tag_index[tag.lower()].remove(entry.id)
            for word in self.tokenize(old.title + " " + old.content):
                if entry.id in self._keyword_index[word]:
                    self._keyword_index[word].remove(entry.id)

        # 添加新索引
        self._entries[entry.id] = entry
        for tag in entry.tags:
            self._tag_index[tag.lower()].append(entry.id)
        for word in self.tokenize(entry.title + " " + entry.content):
            self._keyword_index[word].append(entry.id)

    def get_by_id(self, entry_id: str) -> KnowledgeEntry | None:
        return self._entries.get(entry_id)

    def get_by_category(self, category: str) -> list[KnowledgeEntry]:
        ids = self._category_index.get(category, [])
        return [self._entries[eid] for eid in ids if eid in self._entries]

    def get_by_tag(self, tag: str) -> list[KnowledgeEntry]:
        ids = self._tag_index.get(tag.lower(), [])
        return [self._entries[eid] for eid in ids if eid in self._entries]

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @property
    def categories(self) -> list[str]:
        return list(self._category_index.keys())

    @property
    def all_tags(self) -> list[str]:
        return list(self._tag_index.keys())

    def get_keyword_ids(self) -> dict[str, list[str]]:
        return dict(self._keyword_index)

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """分词 — CJK 按字符切，英文按单词切"""
        import re
        tokens = set()
        # 英文单词
        for m in re.finditer(r'[a-zA-Z]+', text.lower()):
            tokens.add(m.group())
        # CJK 单字 + 双字组合
        cjk_chars = re.findall(r'[一-鿿]', text)
        for ch in cjk_chars:
            tokens.add(ch)
        # 双字组合
        for i in range(len(cjk_chars) - 1):
            tokens.add(cjk_chars[i] + cjk_chars[i + 1])
        return list(tokens)
