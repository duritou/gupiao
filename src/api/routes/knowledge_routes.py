"""Knowledge routes"""

from fastapi import APIRouter, Query

router = APIRouter(tags=["knowledge"], prefix="/knowledge")


@router.get("/categories")
async def list_categories():
    from src.infrastructure.knowledge.knowledge_base import KnowledgeBase
    kb = KnowledgeBase("knowledge")
    await kb.load()
    return {"categories": kb.categories}


@router.get("/search")
async def search_knowledge(
    q: str = Query(..., description="搜索关键词"),
    category: str = Query(None),
):
    from src.infrastructure.knowledge.knowledge_base import KnowledgeBase
    kb = KnowledgeBase("knowledge")
    await kb.load()
    results = kb.search(q, category, top_k=5)
    return {
        "query": q,
        "results": [
            {"id": r.id, "title": r.title, "category": r.category,
             "tags": r.tags, "summary": r.content[:200]}
            for r in results
        ],
    }


@router.get("/entries/{entry_id}")
async def get_entry(entry_id: str):
    from src.infrastructure.knowledge.knowledge_base import KnowledgeBase
    kb = KnowledgeBase("knowledge")
    await kb.load()
    entry = kb.get(entry_id)
    if not entry:
        return {"error": "not found"}
    return {"id": entry.id, "title": entry.title, "category": entry.category,
            "content": entry.content, "tags": entry.tags, "metadata": entry.metadata}
