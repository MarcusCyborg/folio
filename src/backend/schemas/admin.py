from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator
from src.backend.schemas.library import DocumentDetail, DocumentSummary

class AdminDocument(DocumentDetail):
    status: str  # draft | published
    created_by: Optional[str] = None
    deleted_at: Optional[datetime] = None

class DocumentPreviewRequest(BaseModel):
    content: str = Field(default="")

    model_config = ConfigDict(extra="forbid")

class DocumentPreviewResponse(BaseModel):
    rendered_content: str

class DocumentWrite(BaseModel):
    title: str = Field(..., min_length=1, max_length=240)
    content: str = Field(..., min_length=1, max_length=250000)
    summary: str = Field(..., min_length=1, max_length=1000)
    category_id: str
    tag_ids: List[str] = Field(default_factory=list)
    author: Optional[str] = Field(None, max_length=100)
    cover_image_url: Optional[str] = Field(None, max_length=1000)
    cover_image_alt: Optional[str] = Field(None, max_length=255)
    source_url: Optional[str] = Field(None, max_length=1000)
    source_license: Optional[str] = Field(None, max_length=255)
    source_attribution: Optional[str] = Field(None, max_length=500)

    model_config = ConfigDict(extra="forbid")

class DocumentUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=240)
    content: Optional[str] = Field(None, min_length=1, max_length=250000)
    summary: Optional[str] = Field(None, min_length=1, max_length=1000)
    category_id: Optional[str] = None
    tag_ids: Optional[List[str]] = None
    author: Optional[str] = Field(None, max_length=100)
    cover_image_url: Optional[str] = Field(None, max_length=1000)
    cover_image_alt: Optional[str] = Field(None, max_length=255)
    source_url: Optional[str] = Field(None, max_length=1000)
    source_license: Optional[str] = Field(None, max_length=255)
    source_attribution: Optional[str] = Field(None, max_length=500)

    model_config = ConfigDict(extra="forbid")

class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    slug: Optional[str] = Field(None, max_length=120)
    description: Optional[str] = Field(None, max_length=1000)

    model_config = ConfigDict(extra="forbid")

class TagUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    slug: Optional[str] = Field(None, max_length=120)

    model_config = ConfigDict(extra="forbid")

class DocumentStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(draft|published)$")

    model_config = ConfigDict(extra="forbid")

class SEOMetadataUpdate(BaseModel):
    seo_title: Optional[str] = Field(None, max_length=240)
    seo_description: Optional[str] = Field(None, max_length=1000)
    seo_keywords: Optional[List[str]] = Field(default_factory=list)
    cover_image_alt: Optional[str] = Field(None, max_length=255)

    model_config = ConfigDict(extra="forbid")

class CategoryWrite(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: Optional[str] = Field(None, max_length=120)
    description: Optional[str] = Field(None, max_length=1000)

    model_config = ConfigDict(extra="forbid")

class TagWrite(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: Optional[str] = Field(None, max_length=120)

    model_config = ConfigDict(extra="forbid")

class UserAdminUpdate(BaseModel):
    role_key: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None

    model_config = ConfigDict(extra="forbid")

class RolePermissionsUpdate(BaseModel):
    permissions: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

class CommentStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(visible|hidden|spam)$")
    reason: Optional[str] = Field(None, max_length=500)

    model_config = ConfigDict(extra="forbid")

class ReportResolveRequest(BaseModel):
    action: str = Field(..., pattern="^(dismiss|hide_comment|mark_spam)$")
    resolution: Optional[str] = Field(None, max_length=1000)

    model_config = ConfigDict(extra="forbid")

class SuspendCommentingRequest(BaseModel):
    suspended_until: Optional[datetime] = None
    reason: str = Field(..., max_length=500)

    model_config = ConfigDict(extra="forbid")

class AppSettingsUpdate(BaseModel):
    site_name: Optional[str] = Field(None, min_length=1, max_length=100)
    site_description: Optional[str] = Field(None, max_length=1000)
    registration_enabled: Optional[bool] = None
    comments_enabled: Optional[bool] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("site_name")
    def validate_site_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("site_name cannot be empty or whitespace only")
        return v

class AnalyticsPeriod(BaseModel):
    date_from: date
    date_to: date
    timezone: str = "UTC"

class AnalyticsTotals(BaseModel):
    published_documents: int
    search_requests: int
    result_clicks: int
    document_views: int

class AnalyticsDaily(BaseModel):
    date: str
    search_requests: int
    result_clicks: int
    document_views: int

class AnalyticsTopQuery(BaseModel):
    query_string: str
    search_requests: int
    result_clicks: int

class AnalyticsTopDocument(BaseModel):
    id: str
    title: str
    document_views: int
    result_clicks: int

class AnalyticsOverviewResponse(BaseModel):
    period: AnalyticsPeriod
    totals: AnalyticsTotals
    daily: List[AnalyticsDaily]
    top_queries: List[AnalyticsTopQuery]
    top_documents: List[AnalyticsTopDocument]
