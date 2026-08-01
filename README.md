# SyncWrite — Real-Time Collaborative Document Editor

SyncWrite is a Flask-based real-time collaborative editor with permissions, version history, comments, and presence awareness.

## Features

- User registration and login
- Real-time collaboration using Socket.IO
- Rich text editing via Quill.js
- Shared documents with `viewer`, `commenter`, and `editor` roles
- Live presence awareness and cursor tracking
- Autosave plus revision history
- Comment threads with reply, resolve, and delete
- Responsive editor and dashboard UI
- Dashboard document search
- Dark mode toggle in the editor

## Folder structure

```
app.py
requirements.txt
README.md
docs/
  ├── api_documentation.md
  ├── database_schema.md
  └── technical_overview.md
static/
  ├── style.css
  └── js/
templates/
  ├── dashboard.html
  ├── editor.html
  ├── history.html
  ├── index.html
```

## Setup

1. Create and activate a virtual environment:
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

2. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

3. Run the application:
   ```powershell
   .venv\Scripts\python.exe app.py
   ```

4. Open the app in your browser:
   ```text
   http://127.0.0.1:5000
   ```

## Database

This app uses SQLite. The database file is created automatically at `syncwrite.db`.

Schema details are documented in `docs/database_schema.md`.

## API documentation

See `docs/api_documentation.md` for HTTP routes and Socket.IO events.

## Testing

Run the test suite with:

```powershell
python -m unittest discover tests
```

## Notes

- The app demonstrates a lightweight but complete collaborative editing platform with real-time sync, permissions, autosave, and revision history.
- The `static/` and `templates/` folders contain reusable frontend components.
- Use a production-ready server when deploying the app in production.
