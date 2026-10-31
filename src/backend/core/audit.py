from typing import Optional, Any, Dict
from sqlalchemy.orm import Session
from src.backend.models.system import AuditLog
from src.backend.models.auth import User

SENSITIVE_KEYS = {"password", "password_hash", "token", "token_hash", "csrf_token", "secret", "APP_SECRET"}

def redact_payload(data: Any) -> Any:
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            if any(s.lower() in k.lower() for s in SENSITIVE_KEYS):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = redact_payload(v)
        return cleaned
    elif isinstance(data, list):
        return [redact_payload(item) for item in data]
    return data

def write_audit(
    db: Session,
    actor: Optional[User],
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    before: Optional[Any] = None,
    after: Optional[Any] = None,
) -> AuditLog:
    """
    Writes an audit entry into the session without committing.
    The caller must commit this with the business mutation in the same transaction.
    """
    actor_id = actor.id if actor else None
    audit_entry = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=redact_payload(before) if before is not None else None,
        after=redact_payload(after) if after is not None else None,
    )
    db.add(audit_entry)
    return audit_entry
