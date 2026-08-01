# Technical Overview

## Architecture

- **Backend:** Flask application in `app.py`.
- **Real-time:** Flask-SocketIO for WebSocket-based collaboration.
- **Frontend:** Jinja templates with Quill for rich-text editing.
- **Database:** SQLite with a local DB file (`syncwrite.db`).
- **Authentication:** Session-based login and current user lookup using Flask session cookies.

## Key Modules

- `app.py` contains:
  - authentication routes
  - document management
  - permission checks
  - revision history
  - comment handling
  - collaborative Socket.IO broadcasting

- `templates/` contains the UI views:
  - `dashboard.html`
  - `editor.html`
  - `history.html`
  - `index.html`

- `static/` contains supporting assets:
  - `style.css`
  - frontend JavaScript files

## Design Decisions

- **Single-file prototype:** The current implementation is in one Flask app file for simplicity, while still separating concerns logically with helper functions.
- **Reusable helpers:** Common operations like permission checks, database access, autosave, and revision creation are implemented in reusable helper functions.
- **Responsive UI:** Templates are built with responsive layout patterns and modern panel design.
- **Safe defaults:** SQL parameters are parameterized, and session cookies use `HttpOnly` and `SameSite=Lax`.
- **Collaboration consistency:** Socket.IO room broadcasting ensures all connected users receive updates without page refresh.

## Deployment

- Use Python 3.11+.
- Install dependencies from `requirements.txt`.
- Run the app from the project root with:
  ```bash
  .venv/Scripts/python.exe app.py
  ```
- Access the app in a browser at `http://127.0.0.1:5000`.
