import json
import os
import secrets
import smtplib
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import check_password_hash, generate_password_hash

from services.document_service import (
    can_comment,
    can_edit,
    can_view,
    get_permission,
    validate_content,
    validate_title,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "syncwrite-dev-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["FIREBASE_API_KEY"] = os.environ.get("FIREBASE_API_KEY", "AIzaSyD6uplO-rXInBhbqGgoeJVd08-qjwHijjs")

socketio = SocketIO(app, cors_allowed_origins="*")
DB_PATH = os.path.join(os.path.dirname(__file__), "syncwrite.db")
app.config["DATABASE"] = DB_PATH
PRESENCE = {}


def get_db():
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            owner_id INTEGER NOT NULL,
            content TEXT NOT NULL DEFAULT '<p></p>',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_opened_at TEXT,
            FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS document_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            permission TEXT NOT NULL CHECK(permission IN ('viewer', 'commenter', 'editor')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(document_id, user_id),
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            revision_number INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            summary TEXT NOT NULL DEFAULT 'Autosave',
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            parent_id INTEGER DEFAULT NULL,
            message TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
            FOREIGN KEY(author_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(parent_id) REFERENCES comments(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(email) REFERENCES users(email) ON DELETE CASCADE
        );
        """
    )
    conn.commit()
    conn.close()


def ensure_comment_columns():
    conn = get_db()
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(comments)').fetchall()}
    if 'parent_id' not in columns:
        conn.execute('ALTER TABLE comments ADD COLUMN parent_id INTEGER DEFAULT NULL')
    if 'resolved' not in columns:
        conn.execute('ALTER TABLE comments ADD COLUMN resolved INTEGER NOT NULL DEFAULT 0')
    conn.commit()
    conn.close()


init_db()
ensure_comment_columns()


def current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


def get_user_by_email(email):
    if not email:
        return None
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email = ?', ((email or '').strip().lower(),)).fetchone()
    conn.close()
    return user


def get_document(document_id):
    conn = get_db()
    doc = conn.execute('SELECT * FROM documents WHERE id = ?', (document_id,)).fetchone()
    conn.close()
    return doc


def get_document_permission(document_id, user_id):
    return get_permission(document_id, user_id)


def can_view_document(document_id, user_id):
    return can_view(document_id, user_id)


def can_edit_document(document_id, user_id):
    return can_edit(document_id, user_id)


def can_comment_document(document_id, user_id):
    return can_comment(document_id, user_id)


def create_document_snapshot(document_id, created_by_user_id, content, summary='Autosave'):
    conn = get_db()
    revision_number = conn.execute('SELECT COALESCE(MAX(revision_number), 0) + 1 FROM revisions WHERE document_id = ?', (document_id,)).fetchone()[0]
    conn.execute(
        'INSERT INTO revisions (document_id, revision_number, content, created_by, created_at, summary) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)',
        (document_id, revision_number, content, created_by_user_id, summary),
    )
    conn.commit()
    conn.close()


def save_document_content(document_id, content, edited_by_user_id, summary='Autosave'):
    conn = get_db()
    existing = conn.execute('SELECT content FROM documents WHERE id = ?', (document_id,)).fetchone()
    if existing and existing['content'] != content:
        create_document_snapshot(document_id, edited_by_user_id, content, summary)
    conn.execute('UPDATE documents SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (content, document_id))
    conn.commit()
    conn.close()


def get_recent_documents(user_id, search_query=None, limit=5):
    conn = get_db()
    if search_query:
        like_query = f'%{search_query}%'
        rows = conn.execute(
            '''
            SELECT d.*, u.name AS owner_name
            FROM documents d
            JOIN users u ON u.id = d.owner_id
            LEFT JOIN document_permissions p ON p.document_id = d.id AND p.user_id = ?
            WHERE (d.owner_id = ? OR p.user_id = ?) AND d.title LIKE ?
            ORDER BY COALESCE(d.last_opened_at, d.updated_at) DESC
            LIMIT ?
            ''',
            (user_id, user_id, user_id, like_query, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            '''
            SELECT d.*, u.name AS owner_name
            FROM documents d
            JOIN users u ON u.id = d.owner_id
            LEFT JOIN document_permissions p ON p.document_id = d.id AND p.user_id = ?
            WHERE d.owner_id = ? OR p.user_id = ?
            ORDER BY COALESCE(d.last_opened_at, d.updated_at) DESC
            LIMIT ?
            ''',
            (user_id, user_id, user_id, limit),
        ).fetchall()
    conn.close()
    return rows


def is_strong_password(password):
    import re
    if not isinstance(password, str):
        return False
    return bool(re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=[\]{};\':"\\|,.<>/?~`])[A-Za-z\d!@#$%^&*()_+\-=[\]{};\':"\\|,.<>/?~`]{8,}$').fullmatch(password))


def is_valid_email(email):
    import re
    if not isinstance(email, str):
        return False
    return bool(re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').fullmatch(email.strip()))


def send_password_reset_email(email, token):
    smtp_host = os.environ.get('SMTP_HOST')
    smtp_port = int(os.environ.get('SMTP_PORT', '465'))
    sender = os.environ.get('SMTP_SENDER')
    username = os.environ.get('SMTP_USERNAME')
    password = os.environ.get('SMTP_PASSWORD')

    if not all([smtp_host, sender, username, password]):
        return False

    reset_url = url_for('reset_password', token=token, _external=True)
    message = EmailMessage()
    message['Subject'] = 'SyncWrite Password Reset'
    message['From'] = sender
    message['To'] = email
    message.set_content(
        'Use the following link to reset your SyncWrite password:\n\n'
        f'{reset_url}\n\n'
        'If you did not request this, you can ignore this email.'
    )

    try:
        if smtp_port == 587:
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        server.login(username, password)
        server.send_message(message)
        server.quit()
        return True
    except Exception:
        return False


def get_presence_for_document(document_id):
    users = PRESENCE.get(str(document_id), {})
    return [
        {
            'user_id': user_id,
            'name': payload['name'],
            'cursor': payload.get('cursor'),
            'typing': payload.get('typing', False),
            'status': 'online',
        }
        for user_id, payload in users.items()
    ]


def update_presence(document_id, user_id, name, socket_id, cursor=None, typing=None):
    key = str(document_id)
    PRESENCE.setdefault(key, {})
    entry = PRESENCE[key].get(str(user_id), {})
    entry['name'] = name
    entry['socket_id'] = socket_id
    if cursor is not None:
        entry['cursor'] = cursor
    if typing is not None:
        entry['typing'] = typing
    PRESENCE[key][str(user_id)] = entry


@app.template_global()
def initials(name):
    if not name:
        return ''
    parts = [part for part in name.split() if part]
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def get_notification():
    notification = session.pop('notification', None)
    return notification


@app.context_processor
def inject_notification():
    return {'notification_message': get_notification()}


@app.route('/')
def landing():
    if current_user():
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not name:
            return render_template('index.html', error='Name is required.', show_register=True)
        if len(name) < 3:
            return render_template('index.html', error='Name must contain at least 3 characters.', show_register=True)
        if not email:
            return render_template('index.html', error='Email is required.', show_register=True)
        if not is_valid_email(email):
            return render_template('index.html', error='Please enter a valid email address.', show_register=True)
        if not password:
            return render_template('index.html', error='Password is required.', show_register=True)
        if confirm_password and password != confirm_password:
            return render_template('index.html', error='Passwords do not match.', show_register=True)
        if not is_strong_password(password):
            return render_template('index.html', error='Password must include uppercase, lowercase, number and special character.', show_register=True)
        if get_user_by_email(email):
            return render_template('index.html', error='Email already exists.', show_register=True)

        conn = get_db()
        conn.execute('INSERT INTO users (name, email, password) VALUES (?, ?, ?)', (name, email, generate_password_hash(password)))
        conn.commit(); conn.close()
        return redirect(url_for('login'))

    return render_template('index.html', show_register=True)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = get_user_by_email(email)

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('dashboard'))

        return render_template('index.html', error='Invalid email or password.', show_register=False)

    return render_template('index.html', show_register=False)


@app.route('/google-login', methods=['POST'])
def google_login():
    data = request.get_json(silent=True) or {}
    id_token = data.get('token')

    if not id_token:
        return jsonify(error='Missing Google token'), 400

    api_key = app.config.get('FIREBASE_API_KEY')
    if not api_key:
        return jsonify(error='Firebase API key is not configured'), 500

    verify_url = f'https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={api_key}'
    payload = json.dumps({'idToken': id_token}).encode('utf-8')

    try:
        req = urllib.request.Request(verify_url, data=payload, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            token_data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        try:
            error_body = json.loads(exc.read().decode('utf-8'))
            message = error_body.get('error', {}).get('message', 'Invalid token')
        except Exception:
            message = 'Invalid token'
        return jsonify(error=f'Google token verification failed: {message}'), 400
    except Exception:
        return jsonify(error='Unable to verify Google token'), 500

    users = token_data.get('users')
    if not users:
        return jsonify(error='Invalid Google sign-in token'), 400

    user_info = users[0]
    email = (user_info.get('email') or '').strip().lower()
    display_name = user_info.get('displayName') or email.split('@')[0]

    if not email:
        return jsonify(error='Unable to read email from Google account'), 400

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()

    if not user:
        password_hash = generate_password_hash(secrets.token_urlsafe(32))
        conn.execute('INSERT INTO users (name, email, password) VALUES (?, ?, ?)', (display_name, email, password_hash))
        conn.commit()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()

    conn.close()

    session['user_id'] = user['id']
    session['user_name'] = user['name']
    return jsonify(success=True)


@app.route('/home')
@login_required
def home():
    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = get_user_by_email(email)
        if not user:
            return render_template('index.html', error='User not found.', show_register=False, show_forgot_password=True)

        token = secrets.token_urlsafe(24)
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()

        conn = get_db()
        conn.execute('DELETE FROM password_reset_tokens WHERE email = ?', (email,))
        conn.execute(
            'INSERT INTO password_reset_tokens (email, token, expires_at) VALUES (?, ?, ?)',
            (email, token, expires_at),
        )
        conn.commit()
        conn.close()

        email_sent = send_password_reset_email(email, token)
        if email_sent:
            return render_template(
                'index.html',
                message='Password reset link sent to your email.',
                show_register=False,
                show_forgot_password=True,
            )

        return render_template(
            'index.html',
            message=f'Password reset link generated. Use the token: {token} (demo mode).',
            show_register=False,
            show_forgot_password=True,
        )

    return render_template('index.html', show_register=False, show_forgot_password=True)


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    conn = get_db()
    row = conn.execute('SELECT * FROM password_reset_tokens WHERE token = ?', (token,)).fetchone()
    if not row:
        conn.close()
        return render_template('index.html', error='Invalid or expired password reset token.', show_register=False, show_forgot_password=True)

    expires_at = datetime.fromisoformat(row['expires_at'])
    if datetime.now(timezone.utc) > expires_at:
        conn.execute('DELETE FROM password_reset_tokens WHERE token = ?', (token,))
        conn.commit()
        conn.close()
        return render_template('index.html', error='Password reset token has expired.', show_register=False, show_forgot_password=True)

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not password:
            conn.close()
            return render_template('index.html', error='Password is required.', show_register=False, show_forgot_password=True)
        if password != confirm_password:
            conn.close()
            return render_template('index.html', error='Passwords do not match.', show_register=False, show_forgot_password=True)
        if not is_strong_password(password):
            conn.close()
            return render_template('index.html', error='Password must include uppercase, lowercase, number and special character.', show_register=False, show_forgot_password=True)

        conn.execute('UPDATE users SET password = ? WHERE email = ?', (generate_password_hash(password), row['email']))
        conn.execute('DELETE FROM password_reset_tokens WHERE token = ?', (token,))
        conn.commit()
        conn.close()
        return render_template('index.html', message='Password updated successfully. Please login with your new password.', show_register=False)

    conn.close()
    return render_template(
        'index.html',
        show_register=False,
        show_forgot_password=True,
        reset_token=token,
    )


@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    search_query = request.args.get('q', '').strip()
    conn = get_db()

    if search_query:
        like_query = f'%{search_query}%'
        owned = conn.execute(
            'SELECT d.*, u.name AS owner_name FROM documents d JOIN users u ON u.id = d.owner_id WHERE d.owner_id = ? AND d.title LIKE ? ORDER BY d.updated_at DESC',
            (user['id'], like_query),
        ).fetchall()
        shared = conn.execute(
            '''
            SELECT d.*, u.name AS owner_name, p.permission
            FROM document_permissions p
            JOIN documents d ON d.id = p.document_id
            JOIN users u ON u.id = d.owner_id
            WHERE p.user_id = ? AND d.title LIKE ?
            ORDER BY d.updated_at DESC
            ''',
            (user['id'], like_query),
        ).fetchall()
    else:
        owned = conn.execute('SELECT d.*, u.name AS owner_name FROM documents d JOIN users u ON u.id = d.owner_id WHERE d.owner_id = ? ORDER BY d.updated_at DESC', (user['id'],)).fetchall()
        shared = conn.execute(
            '''
            SELECT d.*, u.name AS owner_name, p.permission
            FROM document_permissions p
            JOIN documents d ON d.id = p.document_id
            JOIN users u ON u.id = d.owner_id
            WHERE p.user_id = ?
            ORDER BY d.updated_at DESC
            ''',
            (user['id'],),
        ).fetchall()
    recent = get_recent_documents(user['id'], search_query)
    conn.close()
    return render_template('dashboard.html', user=user, owned_docs=owned, shared_docs=shared, recent_docs=recent, search_query=search_query)


@app.route('/documents/new', methods=['POST'])
@login_required
def create_document():
    title = request.form.get('title', 'Untitled Document').strip() or 'Untitled Document'
    user = current_user()
    conn = get_db()
    cursor = conn.execute('INSERT INTO documents (title, owner_id, content, created_at, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)', (title, user['id'], '<p></p>'))
    doc_id = cursor.lastrowid
    conn.commit(); conn.close()
    create_document_snapshot(doc_id, user['id'], '<p></p>', 'Initial document')
    return redirect(url_for('document_detail', document_id=doc_id))


@app.route('/documents/<int:document_id>')
@login_required
def document_detail(document_id):
    doc = get_document(document_id)
    if not doc:
        abort(404)
    user = current_user()
    permission = get_document_permission(document_id, user['id'])
    if permission is None and doc['owner_id'] != user['id']:
        abort(403)
    permission = permission or 'owner'

    conn = get_db()
    owner = conn.execute('SELECT name FROM users WHERE id = ?', (doc['owner_id'],)).fetchone()
    comments = conn.execute('SELECT c.*, u.name AS author_name FROM comments c JOIN users u ON u.id = c.author_id WHERE c.document_id = ? ORDER BY c.parent_id IS NOT NULL, c.created_at ASC', (document_id,)).fetchall()
    revisions = conn.execute('SELECT r.*, u.name AS editor_name FROM revisions r JOIN users u ON u.id = r.created_by WHERE r.document_id = ? ORDER BY r.created_at DESC', (document_id,)).fetchall()
    conn.execute('UPDATE documents SET last_opened_at = CURRENT_TIMESTAMP WHERE id = ?', (document_id,))
    conn.commit(); conn.close()

    active_users = get_presence_for_document(document_id)
    if not any(str(entry['user_id']) == str(user['id']) for entry in active_users):
        active_users.insert(0, {
            'user_id': user['id'],
            'name': user['name'],
            'cursor': None,
            'typing': False,
            'status': 'online',
        })

    return render_template('editor.html', document=doc, permission=permission, comments=comments, revisions=revisions, current_user=user, active_users=active_users, owner_name=owner['name'] if owner else 'Unknown')


@app.route('/documents/<int:document_id>/rename', methods=['POST'])
@login_required
def rename_document(document_id):
    doc = get_document(document_id)
    if not doc:
        abort(404)
    if not can_edit_document(document_id, current_user()['id']):
        abort(403)

    new_title = request.form.get('title', '').strip()
    is_valid, error = validate_title(new_title)
    if not is_valid:
        return jsonify({'error': error}), 400

    conn = get_db(); conn.execute('UPDATE documents SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (new_title, document_id)); conn.commit(); conn.close()
    session['notification'] = 'Document renamed successfully.'
    return redirect(url_for('document_detail', document_id=document_id))


@app.route('/documents/<int:document_id>/duplicate', methods=['POST'])
@login_required
def duplicate_document(document_id):
    doc = get_document(document_id)
    if not doc:
        abort(404)
    if not can_edit_document(document_id, current_user()['id']):
        abort(403)

    copied_title = f'{doc["title"]} (Copy)'
    if len(copied_title) > 255:
        copied_title = f'{doc["title"][:252]} (Copy)'

    conn = get_db(); cursor = conn.execute('INSERT INTO documents (title, owner_id, content, created_at, updated_at, last_opened_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)', (copied_title, current_user()['id'], doc['content'])); new_id = cursor.lastrowid; conn.commit(); conn.close(); create_document_snapshot(new_id, current_user()['id'], doc['content'], 'Duplicated document'); session['notification'] = 'Document duplicated successfully.'; return redirect(url_for('document_detail', document_id=new_id))


@app.route('/documents/<int:document_id>/delete', methods=['POST'])
@login_required
def delete_document(document_id):
    doc = get_document(document_id)
    if not doc:
        abort(404)
    if doc['owner_id'] != current_user()['id']:
        abort(403)
    conn = get_db(); conn.execute('DELETE FROM documents WHERE id = ?', (document_id,)); conn.commit(); conn.close(); session['notification'] = 'Document deleted.'; return redirect(url_for('dashboard'))


@app.route('/documents/<int:document_id>/share', methods=['POST'])
@login_required
def share_document(document_id):
    doc = get_document(document_id)
    if not doc:
        abort(404)
    if doc['owner_id'] != current_user()['id']:
        abort(403)

    email = request.form.get('email', '').strip().lower()
    permission = request.form.get('permission', 'viewer')
    if permission not in {'viewer', 'commenter', 'editor'}:
        abort(400)
    target = get_user_by_email(email)
    if not target:
        return redirect(url_for('document_detail', document_id=document_id))

    conn = get_db(); conn.execute('INSERT INTO document_permissions (document_id, user_id, permission) VALUES (?, ?, ?) ON CONFLICT(document_id, user_id) DO UPDATE SET permission = excluded.permission', (document_id, target['id'], permission)); conn.commit(); conn.close(); session['notification'] = f'User shared with {email}.'; return redirect(url_for('document_detail', document_id=document_id))


@app.route('/documents/<int:document_id>/autosave', methods=['POST'])
@login_required
def autosave_document(document_id):
    if not can_edit_document(document_id, current_user()['id']):
        abort(403)
    payload = request.get_json(silent=True) or {}
    content = payload.get('content', '')
    is_valid, error = validate_content(content)
    if not is_valid:
        return jsonify({'error': error}), 400
    save_document_content(document_id, content, current_user()['id'], 'Autosave')
    return jsonify({'status': 'saved'})


@app.route('/documents/<int:document_id>/comments', methods=['POST'])
@login_required
def add_comment(document_id):
    if not can_comment_document(document_id, current_user()['id']):
        abort(403)
    payload = request.get_json(silent=True) or {}
    message = (payload.get('message') or '').strip()
    parent_id = payload.get('parent_id')
    if not message:
        return jsonify({'error': 'Comment cannot be empty.'}), 400
    if parent_id is not None and not str(parent_id).isdigit():
        return jsonify({'error': 'Invalid parent comment id.'}), 400

    conn = get_db()
    if parent_id:
        parent = conn.execute('SELECT id FROM comments WHERE id = ? AND document_id = ?', (parent_id, document_id)).fetchone()
        if not parent:
            conn.close(); return jsonify({'error': 'Reply target not found.'}), 404
    cursor = conn.execute(
        'INSERT INTO comments (document_id, author_id, parent_id, message, resolved, created_at) VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP)',
        (document_id, current_user()['id'], parent_id, message),
    )
    comment = conn.execute('SELECT c.*, u.name AS author_name FROM comments c JOIN users u ON u.id = c.author_id WHERE c.id = ?', (cursor.lastrowid,)).fetchone()
    conn.commit(); conn.close()
    socketio.emit('comment_update', {'document_id': document_id, 'comment': dict(comment)}, room=f'document_{document_id}')
    return jsonify({'status': 'ok', 'comment': dict(comment)})


@app.route('/documents/<int:document_id>/comments/<int:comment_id>/resolve', methods=['POST'])
@login_required
def resolve_comment(document_id, comment_id):
    if not can_comment_document(document_id, current_user()['id']):
        abort(403)
    conn = get_db()
    comment = conn.execute('SELECT c.*, u.name AS author_name FROM comments c JOIN users u ON u.id = c.author_id WHERE c.id = ? AND c.document_id = ?', (comment_id, document_id)).fetchone()
    if not comment:
        conn.close(); abort(404)
    conn.execute('UPDATE comments SET resolved = 1 WHERE id = ? AND document_id = ?', (comment_id, document_id))
    updated = conn.execute('SELECT c.*, u.name AS author_name FROM comments c JOIN users u ON u.id = c.author_id WHERE c.id = ?', (comment_id,)).fetchone()
    conn.commit(); conn.close()
    socketio.emit('comment_update', {'document_id': document_id, 'comment': dict(updated), 'action': 'resolve'}, room=f'document_{document_id}')
    return jsonify({'status': 'resolved', 'comment': dict(updated)})


@app.route('/documents/<int:document_id>/comments/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(document_id, comment_id):
    if not can_comment_document(document_id, current_user()['id']):
        abort(403)
    conn = get_db()
    comment = conn.execute('SELECT * FROM comments WHERE id = ? AND document_id = ?', (comment_id, document_id)).fetchone()
    if not comment:
        conn.close(); abort(404)
    if comment['author_id'] != current_user()['id'] and get_document(document_id)['owner_id'] != current_user()['id']:
        conn.close(); abort(403)
    conn.execute('DELETE FROM comments WHERE id = ? AND document_id = ?', (comment_id, document_id))
    conn.commit(); conn.close()
    socketio.emit('comment_deleted', {'document_id': document_id, 'comment_id': comment_id}, room=f'document_{document_id}')
    return jsonify({'status': 'deleted'})


@app.route('/documents/<int:document_id>/history')
@login_required
def document_history(document_id):
    doc = get_document(document_id)
    if not doc:
        abort(404)
    if get_document_permission(document_id, current_user()['id']) is None and doc['owner_id'] != current_user()['id']:
        abort(403)
    conn = get_db(); revisions = conn.execute('SELECT r.*, u.name AS editor_name FROM revisions r JOIN users u ON u.id = r.created_by WHERE r.document_id = ? ORDER BY r.created_at DESC', (document_id,)).fetchall(); conn.close(); return render_template('history.html', document=doc, revisions=revisions)


@app.route('/documents/<int:document_id>/restore/<int:revision_id>', methods=['POST'])
@login_required
def restore_revision(document_id, revision_id):
    if not can_edit_document(document_id, current_user()['id']):
        abort(403)
    conn = get_db(); revision = conn.execute('SELECT * FROM revisions WHERE id = ? AND document_id = ?', (revision_id, document_id)).fetchone();
    if not revision:
        conn.close(); abort(404)

    create_document_snapshot(document_id, current_user()['id'], revision['content'], f'Restored revision {revision["revision_number"]}')
    conn.execute('UPDATE documents SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (revision['content'], document_id))
    conn.commit(); conn.close()
    socketio.emit('document_update', {'document_id': document_id, 'content': revision['content']}, room=f'document_{document_id}')
    return redirect(url_for('document_history', document_id=document_id))


@socketio.on('join_document')
def handle_join_document(payload):
    user = current_user()
    if not user:
        return
    document_id = int(payload.get('doc_id'))
    if not can_view_document(document_id, user['id']):
        return
    room = f'document_{document_id}'
    join_room(room)
    update_presence(document_id, user['id'], user['name'], request.sid)
    emit('presence_update', {'users': get_presence_for_document(document_id)}, room=room, include_self=True)
    doc = get_document(document_id)
    if doc:
        emit('document_state', {'title': doc['title'], 'content': doc['content']})


@socketio.on('cursor_update')
def handle_cursor_update(payload):
    user = current_user()
    if not user:
        return
    document_id = int(payload.get('doc_id'))
    if not can_view_document(document_id, user['id']):
        return
    update_presence(document_id, user['id'], user['name'], request.sid, payload.get('cursor'), payload.get('typing'))
    emit('presence_update', {'users': get_presence_for_document(document_id)}, room=f'document_{document_id}')


@socketio.on('document_update')
def handle_document_update(payload):
    user = current_user()
    if not user:
        return
    document_id = int(payload.get('doc_id'))
    if not can_edit_document(document_id, user['id']):
        return
    content = payload.get('content', '')
    save_document_content(document_id, content, user['id'], 'Live collaboration sync')
    emit('document_update', {'document_id': document_id, 'content': content, 'user_id': user['id'], 'user_name': user['name']}, room=f'document_{document_id}', include_self=False)


@socketio.on('disconnect')
def handle_disconnect():
    for document_id, users in list(PRESENCE.items()):
        for user_id, payload in list(users.items()):
            if payload.get('socket_id') == request.sid:
                del users[user_id]
        if not users:
            del PRESENCE[document_id]
        else:
            emit('presence_update', {'users': get_presence_for_document(int(document_id))}, room=f'document_{int(document_id)}')


if __name__ == '__main__':
    init_db()
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
