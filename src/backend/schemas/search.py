from typing import List, Optional
from pydantic import BaseModel, Field


class SearchTaxon(BaseModel):
    id: str
    name: str
    slug: str


class SearchItem(BaseModel):
    id: str
    title: str
    summary: str
    snippet: str
    score: float
    rank: int
    author: str
    category: Optional[SearchTaxon] = None
    tags: List[SearchTaxon] = Field(default_factory=list)
    created_at: str
    published_at: Optional[str] = None
    views_count: int = 0
    likes_count: int = 0
    cover_image_url: Optional[str] = None
    cover_image_alt: Optional[str] = None
    source_url: Optional[str] = None


class SearchResponse(BaseModel):
    items: List[SearchItem]
    page: int
    page_size: int
    search_context_token: str
    expires_at: str
    snapshot_total: Optional[int] = None
    snapshot_candidate_count: int
    is_approximate_total: bool = False
    has_more: bool
    query: str
    mode: str
    engine_requested: str
    engine_used: str
    is_degraded: bool = False
    degraded_reason: Optional[str] = None
    index_generation: str
    search_event_id: str
    latency_ms: float
