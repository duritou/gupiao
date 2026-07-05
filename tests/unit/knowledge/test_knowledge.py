"""KnowledgeBase 全套测试"""

import pytest

from src.infrastructure.knowledge.loader import KnowledgeLoader, KnowledgeEntry
from src.infrastructure.knowledge.indexer import KnowledgeIndexer
from src.infrastructure.knowledge.search import KnowledgeSearch
from src.infrastructure.knowledge.knowledge_base import KnowledgeBase, KnowledgeNotLoadedError


# ===== KnowledgeLoader Tests =====

class TestKnowledgeLoader:
    """KnowledgeLoader 测试"""

    @pytest.mark.asyncio
    async def test_load_all(self):
        loader = KnowledgeLoader("knowledge")
        entries = await loader.load_all()
        assert len(entries) >= 2  # semiconductor + banking

        # 验证 semiconductor 条目
        semi = next(e for e in entries if e.id == "semiconductor")
        assert semi.title == "半导体"
        assert semi.category == "industry"
        assert "国产替代" in str(semi.metadata)
        assert "半导体" in semi.tags
        assert "industry_chain" in semi.metadata

    @pytest.mark.asyncio
    async def test_load_category(self):
        loader = KnowledgeLoader("knowledge")
        entries = await loader.load_category("industry")
        assert len(entries) >= 2
        for e in entries:
            assert e.category == "industry"

    @pytest.mark.asyncio
    async def test_load_nonexistent_dir(self):
        loader = KnowledgeLoader("knowledge/nonexistent")
        entries = await loader.load_all()
        assert entries == []

    @pytest.mark.asyncio
    async def test_entry_has_required_fields(self):
        loader = KnowledgeLoader("knowledge")
        entries = await loader.load_all()
        for e in entries:
            assert e.id
            assert e.title
            assert e.category


# ===== KnowledgeIndexer Tests =====

class TestKnowledgeIndexer:
    """KnowledgeIndexer 测试"""

    @pytest.fixture
    def entries(self):
        return [
            KnowledgeEntry(id="e1", title="半导体行业", category="industry",
                           content="芯片设计和制造", tags=["半导体", "芯片"]),
            KnowledgeEntry(id="e2", title="银行业", category="industry",
                           content="信贷和息差", tags=["银行", "金融"]),
            KnowledgeEntry(id="e3", title="GDP分析", category="macro",
                           content="国内生产总值", tags=["宏观", "GDP"]),
        ]

    def test_build_index(self, entries):
        idx = KnowledgeIndexer()
        count = idx.build(entries)
        assert count == 3
        assert idx.entry_count == 3

    def test_get_by_id(self, entries):
        idx = KnowledgeIndexer()
        idx.build(entries)
        e = idx.get_by_id("e1")
        assert e is not None
        assert e.title == "半导体行业"

    def test_get_by_category(self, entries):
        idx = KnowledgeIndexer()
        idx.build(entries)
        industry = idx.get_by_category("industry")
        assert len(industry) == 2
        macro = idx.get_by_category("macro")
        assert len(macro) == 1

    def test_get_by_tag(self, entries):
        idx = KnowledgeIndexer()
        idx.build(entries)
        chip = idx.get_by_tag("芯片")
        assert len(chip) == 1
        assert chip[0].id == "e1"

    def test_categories(self, entries):
        idx = KnowledgeIndexer()
        idx.build(entries)
        assert set(idx.categories) == {"industry", "macro"}

    def test_update_entry(self, entries):
        idx = KnowledgeIndexer()
        idx.build(entries)
        updated = KnowledgeEntry(id="e1", title="半导体行业v2", category="industry",
                                  content="芯片设计制造封测", tags=["半导体", "芯片", "封测"])
        idx.update(updated)
        e = idx.get_by_id("e1")
        assert e is not None
        assert "封测" in e.tags


# ===== KnowledgeSearch Tests =====

class TestKnowledgeSearch:
    """KnowledgeSearch 测试"""

    @pytest.fixture
    def indexer(self):
        idx = KnowledgeIndexer()
        idx.build([
            KnowledgeEntry(id="e1", title="半导体行业", category="industry",
                           content="芯片设计和晶圆制造 光刻机", tags=["半导体", "芯片"]),
            KnowledgeEntry(id="e2", title="银行业", category="industry",
                           content="信贷和净息差 不良贷款", tags=["银行", "金融"]),
            KnowledgeEntry(id="e3", title="GDP分析", category="macro",
                           content="国内生产总值", tags=["宏观", "GDP"]),
        ])
        return idx

    def test_search_keyword(self, indexer):
        search = KnowledgeSearch(indexer)
        results = search.search("芯片")
        assert len(results) == 1
        assert results[0].id == "e1"

    def test_search_with_category_filter(self, indexer):
        search = KnowledgeSearch(indexer)
        results = search.search("芯片", category="industry")
        assert len(results) == 1
        # 但如果在 macro 中搜 "芯片" 就找不到
        results2 = search.search("芯片", category="macro")
        assert len(results2) == 0

    def test_search_by_tag(self, indexer):
        search = KnowledgeSearch(indexer)
        results = search.search_by_tag("银行")
        assert len(results) == 1
        assert results[0].id == "e2"

    def test_search_by_category(self, indexer):
        search = KnowledgeSearch(indexer)
        results = search.search_by_category("industry")
        assert len(results) == 2

    def test_search_no_match(self, indexer):
        search = KnowledgeSearch(indexer)
        results = search.search("新能源")
        assert results == []

    def test_search_multi_keyword(self, indexer):
        search = KnowledgeSearch(indexer)
        results = search.search("芯片 制造")
        assert len(results) >= 1
        assert results[0].id == "e1"


# ===== KnowledgeBase Tests =====

class TestKnowledgeBase:
    """KnowledgeBase 集成测试"""

    @pytest.mark.asyncio
    async def test_load_and_search(self):
        kb = KnowledgeBase("knowledge")
        assert kb.is_loaded is False

        count = await kb.load()
        assert count >= 2
        assert kb.is_loaded is True

    @pytest.mark.asyncio
    async def test_search_semiconductor(self):
        kb = KnowledgeBase("knowledge")
        await kb.load()
        results = kb.search("半导体")
        assert len(results) >= 1
        assert results[0].category == "industry"

    @pytest.mark.asyncio
    async def test_search_by_tag(self):
        kb = KnowledgeBase("knowledge")
        await kb.load()
        results = kb.search_by_tag("半导体")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_get_by_id(self):
        kb = KnowledgeBase("knowledge")
        await kb.load()
        entry = kb.get("semiconductor")
        assert entry is not None
        assert "产业链" in entry.content or "industry_chain" in entry.metadata

    @pytest.mark.asyncio
    async def test_categories(self):
        kb = KnowledgeBase("knowledge")
        await kb.load()
        assert "industry" in kb.categories

    @pytest.mark.asyncio
    async def test_not_loaded_raises(self):
        kb = KnowledgeBase("knowledge")
        with pytest.raises(KnowledgeNotLoadedError):
            kb.search("test")

    @pytest.mark.asyncio
    async def test_reload(self):
        kb = KnowledgeBase("knowledge")
        await kb.load()
        count = await kb.reload()
        assert count >= 2
