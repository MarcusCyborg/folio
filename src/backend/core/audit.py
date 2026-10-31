import re
from typing import Optional, Any, Dict
from sqlalchemy.orm import Session
from src.backend.models.system import AuditLog
from src.backend.models.auth import User

SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "token",
    "token_hash",
    "csrf_token",
    "secret",
    "app_secret",
    "authorization",
    "cookie",
    "set-cookie",
    "database_url",
    "api_key",
    "credential",
}

CONNECTION_STRING_PATTERN = re.compile(
    r'(postgresql(?:\+[a-z0-9]+)?://)([^:]+):(.*?)@([^/\s:]+(?::\d+)?/[^\s\?]+)',
    re.IGNORECASE
)

TOKEN_PATTERN = re.compile(
    r'(?i)(token|bearer|password|secret|key|cookie)\s*[:=]\s*["\']?([a-zA-Z0-9_\-\.]{8,})["\']?'
)

def redact_sensitive_text(text: str) -> str:
    """
    Scans a string and redacts connection strings and sensitive credential assignments.
    """
    if not isinstance(text, str):
        return str(text)
    
    # Redact connection string user:password
    result = CONNECTION_STRING_PATTERN.sub(r'\1[REDACTED_USER]:[REDACTED_PASSWORD]@\4', text)
    # Redact tokens and passwords
    result = TOKEN_PATTERN.sub(r'\1=[REDACTED]', result)
    return result

def redact_payload(data: Any) -> Any:
    """
    Recursively redacts dictionary keys and strings containing sensitive data.
    """
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            if any(s in k.lower() for s in SENSITIVE_KEYS):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = redact_payload(v)
        return cleaned
    elif isinstance(data, list):
        return [redact_payload(item) for item in data]
    elif isinstance(data, str):
        return redact_sensitive_text(data)
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
