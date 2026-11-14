import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from src.backend.core.exceptions import AppException

SENSITIVE_COLUMN_PATTERN = re.compile(r"(password|secret|token|hash)", re.IGNORECASE)
SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(name: str) -> str:
    if not SAFE_IDENTIFIER_PATTERN.match(name):
        raise AppException(status_code=400, code="INVALID_IDENTIFIER", message="Invalid table identifier")
    return f'"{name}"'


def _serialize_cell(col_name: str, value: Any) -> Any:
    if value is None:
        return None
    if SENSITIVE_COLUMN_PATTERN.search(col_name):
        return "[REDACTED]"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, str) and len(value) > 300:
        return value[:300] + "…"
    return value


def admin_list_database_tables(db: Session) -> Dict[str, Any]:
    """List all tables in the primary database with column counts and row counts."""
    bind = db.get_bind()
    inspector = inspect(bind)
    table_names = sorted(inspector.get_table_names())

    dialect = bind.dialect.name
    db_name = None
    try:
        if dialect == "postgresql":
            db_name = db.execute(text("SELECT current_database()")).scalar()
        else:
            db_name = str(bind.url.database or "")
    except Exception:
        db_name = None

    tables: List[Dict[str, Any]] = []
    for table_name in table_names:
        cols = inspector.get_columns(table_name)
        quoted = _quote_identifier(table_name)
        row_count = db.execute(text(f"SELECT COUNT(*) FROM {quoted}")).scalar() or 0
        tables.append(
            {
                "name": table_name,
                "column_count": len(cols),
                "row_count": int(row_count),
            }
        )

    return {
        "dialect": dialect,
        "database": db_name,
        "tables": tables,
    }


def admin_get_database_table_rows(
    db: Session,
    table_name: str,
    page: int = 1,
    page_size: int = 25,
) -> Dict[str, Any]:
    """Return paginated read-only rows for a validated table with sensitive columns redacted."""
    bind = db.get_bind()
    inspector = inspect(bind)
    valid_tables = set(inspector.get_table_names())
    if table_name not in valid_tables:
        raise AppException(
            status_code=404,
            code="TABLE_NOT_FOUND",
            message=f"Table '{table_name}' does not exist",
        )

    quoted = _quote_identifier(table_name)
    raw_columns = inspector.get_columns(table_name)
    columns = [
        {
            "name": col["name"],
            "type": str(col["type"]),
            "redacted": bool(SENSITIVE_COLUMN_PATTERN.search(col["name"])),
        }
        for col in raw_columns
    ]

    total = int(db.execute(text(f"SELECT COUNT(*) FROM {quoted}")).scalar() or 0)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    offset = (page - 1) * page_size

    pk_cols = inspector.get_pk_constraint(table_name).get("constrained_columns") or []
    order_clause = ""
    if pk_cols and all(SAFE_IDENTIFIER_PATTERN.match(c) for c in pk_cols):
        order_clause = " ORDER BY " + ", ".join(f'"{c}" DESC' for c in pk_cols)

    result = db.execute(
        text(f"SELECT * FROM {quoted}{order_clause} LIMIT :limit OFFSET :offset"),
        {"limit": page_size, "offset": offset},
    )
    rows = [
        {col: _serialize_cell(col, val) for col, val in row._mapping.items()}
        for row in result
    ]

    return {
        "table": table_name,
        "columns": columns,
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
