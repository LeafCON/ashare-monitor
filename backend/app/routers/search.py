"""Symbol search for the quote page."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..services.eastmoney import search_symbols

router = APIRouter(prefix="/api/search", tags=["search"])


class SearchHit(BaseModel):
    symbol: str
    name: str
    market: str
    secid: str


@router.get("", response_model=List[SearchHit])
def search(q: str = Query("", min_length=0), limit: int = Query(8, le=20)):
    """Search A-shares and US tickers by code or name."""
    return search_symbols(q, limit)
