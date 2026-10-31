from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from src.backend.schemas.shared import Taxon, PaginatedResponse

class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    summary: str
    author: str
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None
    views_count: int = 0
    likes_count: int = 0
    comments_count: int = 0
    category: Taxon
    category_id: str
    tags: List[Taxon] = Field(default_factory=list)
    cover_image_url: Optional[str] = None
    cover_image_alt: Optional[str] = None
    source_url: Optional[str] = None


class DocumentDetail(DocumentSummary):
    content: str
    rendered_content: str
    source_license: Optional[str] = None
    source_attribution: Optional[str] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    seo_keywords: Optional[List[str]] = None
    liked_by_me: bool = False

class AuthorSummary(BaseModel):
    id: str
    username: str
    display_name: str

class CommentPublic(BaseModel):
    id: str
    document_id: str
    author: AuthorSummary
    body: str
    mentions: List[AuthorSummary] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    can_edit: bool = False
    can_delete: bool = False

class DocumentListResponse(PaginatedResponse[DocumentSummary]):
    query: Optional[str] = None
    search_event_id: Optional[str] = None

class ViewEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    navigation_id: str

class ClickEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search_event_id: str
    document_id: str
    request_key: str

class CommentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(..., min_length=1, max_length=4000)

class CommentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(..., min_length=1, max_length=4000)

class ReportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., min_length=1, max_length=50)
    details: Optional[str] = Field(None, max_length=2000)
