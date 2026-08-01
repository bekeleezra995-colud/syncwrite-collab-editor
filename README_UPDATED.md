# SyncWrite — Real-Time Collaborative Document Editor

SyncWrite is a Flask-based collaborative document editor with real-time synchronization, version history, comments, and sharing permissions.

## What this app includes

- Secure user authentication
- Real-time collaboration using Socket.IO
- Rich text editing with Quill
- Document sharing with Viewer/Commenter/Editor permission levels
- Version history and restore support
- Comment threads with replies, resolve, delete
- Auto save and presence awareness
- Responsive editor and dashboard UI

## Project structure

- `app.py` — main Flask app and Socket.IO server
- `templates/` — HTML templates for login, dashboard, editor, history
- `static/` — CSS and client-side JavaScript
- `requirements.txt` — Python dependencies
- `docs/` — database schema, API documentation, and technical overview
- `syncwrite.db` — local SQLite database file (not committed in source control)

## Setup

1. Create and activate a Python virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the app:
   ```bash
   .venv\Scripts\python.exe app.py
   ```

4. Open the app in a browser:
   ```text
   http://127.0.0.1:5000
   ```

## Database

The app uses SQLite and auto-creates the database schema on startup.

For schema details, see `docs/database_schema.md`.

## Deployment notes

- Ensure `.env` contains any required secrets.
- The app runs on port 5000 by default.
- Use a process manager or production-ready server for deployment if needed.

## API docs

See `docs/api_documentation.md` for a full route and Socket.IO event reference.

## Testing

Run tests with:

```bash
python -m unittest discover tests
```

## Additional notes

The project is built independently and includes all core features to meet the assignment requirements. The code is intentionally kept in a single `app.py` file for the prototype, with modular helper functions and clear route separation.
