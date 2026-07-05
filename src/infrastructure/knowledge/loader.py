"""Knowledge Loader — 加载 YAML 知识文件"""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field

import yaml
from loguru import logger


@dataclass
class KnowledgeEntry:
    """知识条目 — 格式无关的中间表示"""

    id: str
    title: str = ""
    category: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    source_path: str = ""
    version: int = 1


class KnowledgeLoader:
    """知识加载器 — 只负责从文件加载为 KnowledgeEntry"""

    def __init__(self, base_path: str = "knowledge"):
        self._base_path = Path(base_path)

    async def load_all(self) -> list[KnowledgeEntry]:
        """加载所有知识文件"""
        entries = []
        if not self._base_path.exists():
            logger.warning("Knowledge base path not found: {}", self._base_path)
            return entries

        for yaml_file in self._base_path.rglob("*.yaml"):
            entry = await self._load_file(yaml_file)
            if entry:
                entries.append(entry)

        logger.info("Loaded {} knowledge entries", len(entries))
        return entries

    async def load_category(self, category: str) -> list[KnowledgeEntry]:
        """加载指定分类"""
        category_dir = self._base_path / category
        if not category_dir.exists():
            return []

        entries = []
        for yaml_file in category_dir.glob("*.yaml"):
            entry = await self._load_file(yaml_file)
            if entry:
                entry.category = category
                entries.append(entry)
        return entries

    async def _load_file(self, path: Path) -> KnowledgeEntry | None:
        """加载单个 YAML 文件"""
        try:
            content = path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if not data:
                return None

            return KnowledgeEntry(
                id=data.get("id", path.stem),
                title=data.get("name", data.get("title", path.stem)),
                category=data.get("category", path.parent.name),
                content=data.get("summary", data.get("content", "")),
                tags=data.get("tags", []),
                metadata={k: v for k, v in data.items()
                          if k not in ("id", "name", "title", "category", "summary", "content", "tags")},
                source_path=str(path),
            )
        except Exception as e:
            logger.error("Failed to load knowledge file {}: {}", path, e)
            return None
