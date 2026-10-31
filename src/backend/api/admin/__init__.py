from typing import Optional, List, Dict, Any
from datetime import date
from fastapi import APIRouter, Depends, Query, Path, Response, status
from sqlalchemy.orm import Session

from src.backend.core.database import get_db
from src.backend.core.dependencies import (
    get_current_user,
    require_permission,
    require_any_permission,
)
from src.backend.core.sanitizer import render_and_sanitize_markdown
from src.backend.models.auth import User
from src.backend.schemas.admin import (
    DocumentWrite,
    DocumentUpdate,
    DocumentStatusUpdate,
    DocumentPreviewRequest,
    DocumentPreviewResponse,
    CategoryWrite,
    CategoryUpdate,
    TagWrite,
    TagUpdate,
    UserAdminUpdate,
    RolePermissionsUpdate,
    CommentStatusUpdate,
    ReportResolveRequest,
    SuspendCommentingRequest,
    AppSettingsUpdate,
    SEOMetadataUpdate,
    AnalyticsOverviewResponse,
)
from src.backend.services.admin.content_service import (
    admin_list_documents,
    admin_get_document,
    admin_create_document,
    admin_update_document,
    admin_update_document_status,
    admin_delete_document,
    admin_list_categories,
    admin_create_category,
    admin_update_category,
    admin_delete_category,
    admin_list_tags,
    admin_create_tag,
    admin_update_tag,
    admin_delete_tag,
)
from src.backend.services.admin.governance_service import (
    admin_list_users,
    admin_update_user,
    admin_list_roles,
    admin_list_permissions,
    admin_update_role_permissions,
    admin_list_audit_logs,
    admin_get_settings,
    admin_update_settings,
)
from src.backend.services.admin.moderation_service import (
    admin_list_comments,
    admin_update_comment_status,
    admin_list_reports,
    admin_resolve_report,
    admin_suspend_commenting,
)
from src.backend.services.admin.analytics_service import (
    admin_update_document_seo,
    admin_get_analytics_overview,
)

router = APIRouter(prefix="/admin", tags=["admin"])

# ==============================================================================
# Content & Taxonomy Management
# ==============================================================================

@router.get("/documents")
def get_documents(
    q: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(draft|published)$"),
    category_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_any_permission("documents:write", "seo:write")),
    db: Session = Depends(get_db),
):
    items, total = admin_list_documents(db, q=q, status_filter=status, category_id=category_id, page=page, page_size=page_size)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return {"items": items, "page": page, "page_size": page_size, "total": total, "total_pages": total_pages}

@router.get("/documents/{document_id}")
def get_document(
    document_id: str = Path(...),
    current_user: User = Depends(require_any_permission("documents:write", "seo:write")),
    db: Session = Depends(get_db),
):
    return admin_get_document(db, document_id)

@router.post("/documents", status_code=status.HTTP_201_CREATED)
def create_document(
    data: DocumentWrite,
    current_user: User = Depends(require_permission("documents:write")),
    db: Session = Depends(get_db),
):
    return admin_create_document(db, data, current_user)

@router.post("/documents/preview", response_model=DocumentPreviewResponse)
def preview_document(
    data: DocumentPreviewRequest,
    current_user: User = Depends(require_permission("documents:write")),
):
    rendered = render_and_sanitize_markdown(data.content)
    return {"rendered_content": rendered}

@router.patch("/documents/{document_id}")
def update_document(
    data: DocumentUpdate,
    document_id: str = Path(...),
    current_user: User = Depends(require_permission("documents:write")),
    db: Session = Depends(get_db),
):
    return admin_update_document(db, document_id, data.model_dump(exclude_unset=True), current_user)

@router.patch("/documents/{document_id}/status")
def update_document_status(
    data: DocumentStatusUpdate,
    document_id: str = Path(...),
    current_user: User = Depends(require_permission("documents:write")),
    db: Session = Depends(get_db),
):
    return admin_update_document_status(db, document_id, data.status, current_user)

@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str = Path(...),
    current_user: User = Depends(require_permission("documents:write")),
    db: Session = Depends(get_db),
):
    admin_delete_document(db, document_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/categories")
def get_categories(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_any_permission("taxonomy:write", "documents:write", "seo:write")),
    db: Session = Depends(get_db),
):
    items, total = admin_list_categories(db, page=page, page_size=page_size)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return {"items": items, "page": page, "page_size": page_size, "total": total, "total_pages": total_pages}

@router.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category(
    data: CategoryWrite,
    current_user: User = Depends(require_permission("taxonomy:write")),
    db: Session = Depends(get_db),
):
    return admin_create_category(db, data, current_user)

@router.patch("/categories/{category_id}")
def update_category(
    data: CategoryUpdate,
    category_id: str = Path(...),
    current_user: User = Depends(require_permission("taxonomy:write")),
    db: Session = Depends(get_db),
):
    return admin_update_category(db, category_id, data, current_user)

@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: str = Path(...),
    current_user: User = Depends(require_permission("taxonomy:write")),
    db: Session = Depends(get_db),
):
    admin_delete_category(db, category_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/tags")
def get_tags(
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_any_permission("taxonomy:write", "documents:write", "seo:write")),
    db: Session = Depends(get_db),
):
    items, total = admin_list_tags(db, q=q, page=page, page_size=page_size)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return {"items": items, "page": page, "page_size": page_size, "total": total, "total_pages": total_pages}

@router.post("/tags", status_code=status.HTTP_201_CREATED)
def create_tag(
    data: TagWrite,
    current_user: User = Depends(require_permission("taxonomy:write")),
    db: Session = Depends(get_db),
):
    return admin_create_tag(db, data, current_user)

@router.patch("/tags/{tag_id}")
def update_tag(
    data: TagUpdate,
    tag_id: str = Path(...),
    current_user: User = Depends(require_permission("taxonomy:write")),
    db: Session = Depends(get_db),
):
    return admin_update_tag(db, tag_id, data, current_user)

@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    tag_id: str = Path(...),
    current_user: User = Depends(require_permission("taxonomy:write")),
    db: Session = Depends(get_db),
):
    admin_delete_tag(db, tag_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# ==============================================================================
# Governance: Users, RBAC, Settings, Audit
# ==============================================================================

@router.get("/users")
def get_users(
    q: Optional[str] = Query(None),
    role_key: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    items, total = admin_list_users(db, q=q, role_key=role_key, is_active=is_active, page=page, page_size=page_size)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return {"items": items, "page": page, "page_size": page_size, "total": total, "total_pages": total_pages}

@router.patch("/users/{user_id}")
def update_user(
    data: UserAdminUpdate,
    user_id: str = Path(...),
    current_user: User = Depends(require_permission("users:manage")),
    db: Session = Depends(get_db),
):
    return admin_update_user(db, user_id, data.role_key, data.is_active, current_user)

@router.get("/roles")
def get_roles(
    current_user: User = Depends(require_permission("roles:manage")),
    db: Session = Depends(get_db),
):
    return {"items": admin_list_roles(db)}

@router.get("/permissions")
def get_permissions(
    current_user: User = Depends(require_permission("roles:manage")),
    db: Session = Depends(get_db),
):
    return {"items": admin_list_permissions(db)}

@router.put("/roles/{role_key}/permissions")
def update_role_permissions(
    data: RolePermissionsUpdate,
    role_key: str = Path(...),
    current_user: User = Depends(require_permission("roles:manage")),
    db: Session = Depends(get_db),
):
    return admin_update_role_permissions(db, role_key, data.permissions, current_user)

@router.get("/audit-logs")
def get_audit_logs(
    actor_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_permission("audit:read")),
    db: Session = Depends(get_db),
):
    items, total = admin_list_audit_logs(db, actor_id=actor_id, action=action, date_from=date_from, date_to=date_to, page=page, page_size=page_size)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return {"items": items, "page": page, "page_size": page_size, "total": total, "total_pages": total_pages}

@router.get("/settings")
def get_settings(
    current_user: User = Depends(require_permission("settings:write")),
    db: Session = Depends(get_db),
):
    return admin_get_settings(db)

@router.patch("/settings")
def update_settings(
    data: AppSettingsUpdate,
    current_user: User = Depends(require_permission("settings:write")),
    db: Session = Depends(get_db),
):
    return admin_update_settings(db, data.model_dump(exclude_unset=True), current_user)

# ==============================================================================
# Moderation Queue & Spam Control
# ==============================================================================

@router.get("/comments")
def get_moderation_comments(
    status: Optional[str] = Query(None, pattern="^(visible|hidden|spam|deleted)$"),
    q: Optional[str] = Query(None),
    document_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_permission("moderation:manage")),
    db: Session = Depends(get_db),
):
    items, total = admin_list_comments(db, status_filter=status, q=q, document_id=document_id, page=page, page_size=page_size)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return {"items": items, "page": page, "page_size": page_size, "total": total, "total_pages": total_pages}

@router.patch("/comments/{comment_id}/status")
def update_comment_status(
    data: CommentStatusUpdate,
    comment_id: str = Path(...),
    current_user: User = Depends(require_permission("moderation:manage")),
    db: Session = Depends(get_db),
):
    return admin_update_comment_status(db, comment_id, data.status, data.reason, current_user)

@router.get("/reports")
def get_reports(
    status: Optional[str] = Query(None, pattern="^(open|resolved|dismissed)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_permission("moderation:manage")),
    db: Session = Depends(get_db),
):
    items, total = admin_list_reports(db, status_filter=status, page=page, page_size=page_size)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    return {"items": items, "page": page, "page_size": page_size, "total": total, "total_pages": total_pages}

@router.patch("/reports/{report_id}")
def resolve_report(
    data: ReportResolveRequest,
    report_id: str = Path(...),
    current_user: User = Depends(require_permission("moderation:manage")),
    db: Session = Depends(get_db),
):
    return admin_resolve_report(db, report_id, data.action, data.resolution, current_user)

@router.patch("/users/{user_id}/commenting")
def suspend_user_commenting(
    data: SuspendCommentingRequest,
    user_id: str = Path(...),
    current_user: User = Depends(require_permission("moderation:manage")),
    db: Session = Depends(get_db),
):
    return admin_suspend_commenting(db, user_id, data.suspended_until, data.reason, current_user)

# ==============================================================================
# SEO & Analytics
# ==============================================================================

@router.patch("/documents/{document_id}/seo")
def update_document_seo(
    data: SEOMetadataUpdate,
    document_id: str = Path(...),
    current_user: User = Depends(require_permission("seo:write")),
    db: Session = Depends(get_db),
):
    return admin_update_document_seo(db, document_id, data, current_user)

@router.get("/analytics/overview", response_model=AnalyticsOverviewResponse)
def get_analytics(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: User = Depends(require_permission("analytics:read")),
    db: Session = Depends(get_db),
):
    return admin_get_analytics_overview(db, date_from=date_from, date_to=date_to)
