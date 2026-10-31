from typing import Dict, List, Any, Optional, Generic, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")

class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: Dict[str, List[str]] = Field(default_factory=dict)

class ErrorResponse(BaseModel):
    error: ErrorDetail

class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    page: int
    page_size: int
    total: int
    total_pages: int

class Taxon(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str] = None

class PublicSettingsResponse(BaseModel):
    site_name: str
    site_description: str
    registration_enabled: bool
    comments_enabled: bool
