import sqlite3
from typing import Optional, Tuple

from flask import current_app


def get_db_connection():
    conn = sqlite3.connect(current_app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    return conn


def get_document_by_id(document_id: int):
    conn = get_db_connection()
    document = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    conn.close()
    return document


def get_permission(document_id: int, user_id: int) -> Optional[str]:
    doc = get_document_by_id(document_id)
    if not doc:
        return None
    if doc["owner_id"] == user_id:
        return "owner"
    conn = get_db_connection()
    row = conn.execute(
        "SELECT permission FROM document_permissions WHERE document_id = ? AND user_id = ?",
        (document_id, user_id),
    ).fetchone()
    conn.close()
    return row["permission"] if row else None


def can_view(document_id: int, user_id: int) -> bool:
    permission = get_permission(document_id, user_id)
    return permission in {"owner", "viewer", "commenter", "editor"}


def can_edit(document_id: int, user_id: int) -> bool:
    permission = get_permission(document_id, user_id)
    return permission in {"owner", "editor"}


def can_comment(document_id: int, user_id: int) -> bool:
    permission = get_permission(document_id, user_id)
    return permission in {"owner", "editor", "commenter"}


def validate_title(title: str) -> Tuple[bool, Optional[str]]:
    if not isinstance(title, str):
        return False, "Title must be a string."
    cleaned = title.strip()
    if not cleaned:
        return False, "Title is required."
    if len(cleaned) > 255:
        return False, "Title must be 255 characters or fewer."
    return True, None


def validate_content(content: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(content, str):
        return False, "Content must be a string."
    if len(content) > 200000:
        return False, "Content is too large."
    return True, None
