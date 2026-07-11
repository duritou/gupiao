"""Stock detail routes — v11.1: uses ResearchSnapshotBuilder.

Single canonical implementation for research snapshots.
All consumers (Research page, Replay, Case Library) use the same builder.
"""

from fastapi import APIRouter, Query

router = APIRouter(tags=["detail"], prefix="/detail")


@router.get("/{code}")
async def get_stock_detail(code: str, include: str = Query("all")):
    """Get complete research snapshot — market data + signals + AI analysis.

    Returns ResearchSnapshotV1: a versioned DTO with fixed contract.
    Fields guaranteed by contract test in test_v11_governance.py.
    """
    from src.explain.research_builder import research_builder
    snap = await research_builder.build(code)
    return snap.to_dict()
