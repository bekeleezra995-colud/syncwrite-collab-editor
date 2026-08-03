import sqlite3

import pytest

import app as app_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test-syncwrite.db"
    monkeypatch.setattr(app_module, "DB_PATH", str(db_path))
    app_module.app.config["DATABASE"] = str(db_path)
    app_module.init_db()
    app_module.ensure_comment_columns()
    return app_module.app.test_client()


def seed_user_and_document(client):
    conn = sqlite3.connect(app_module.app.config["DATABASE"])
    conn.execute(
        "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
        ("Owner", "owner@example.com", "hashed-password"),
    )
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO documents (title, owner_id, content, created_at, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        ("Test Doc", user_id, "<p>Hello</p>"),
    )
    doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO comments (document_id, author_id, message, resolved, created_at) VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP)",
        (doc_id, user_id, "Needs follow-up"),
    )
    comment_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return user_id, doc_id, comment_id


def test_resolved_comments_are_rendered_as_resolved(client):
    user_id, doc_id, comment_id = seed_user_and_document(client)

    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["user_name"] = "Owner"

    response = client.post(f"/documents/{doc_id}/comments/{comment_id}/resolve")
    assert response.status_code == 200

    conn = sqlite3.connect(app_module.app.config["DATABASE"])
    resolved_state = conn.execute("SELECT resolved FROM comments WHERE id = ?", (comment_id,)).fetchone()[0]
    conn.close()
    assert resolved_state == 1

    page_response = client.get(f"/documents/{doc_id}")
    assert page_response.status_code == 200
    body = page_response.get_data(as_text=True)
    assert "Resolved" in body
    assert 'class="comment-item resolved"' in body
