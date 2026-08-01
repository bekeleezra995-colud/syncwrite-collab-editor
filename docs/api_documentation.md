# API Documentation

This document describes the web routes and WebSocket events used by the SyncWrite app.

## HTTP Routes

### Authentication

- `GET /login`
  - Returns the login page.

- `POST /login`
  - Form fields: `email`, `password`
  - Authenticates the user and redirects to `/dashboard`.

- `GET /logout`
  - Clears the session and redirects to `/login`.

### Dashboard

- `GET /dashboard`
  - Returns the user dashboard with owned, shared, and recent documents.

### Document Management

- `POST /documents/new`
  - Form fields: `title`
  - Creates a new document and redirects to `/documents/<id>`.

- `GET /documents/<document_id>`
  - Returns the editor page for the requested document.

- `POST /documents/<document_id>/rename`
  - Form fields: `title`
  - Renames the document.

- `POST /documents/<document_id>/duplicate`
  - Duplicates the document for the current user.

- `POST /documents/<document_id>/delete`
  - Deletes the document if the current user is the owner.

- `POST /documents/<document_id>/share`
  - Form fields: `email`, `permission`
  - Shares the document with another user as `viewer`, `commenter`, or `editor`.

### Autosave

- `POST /documents/<document_id>/autosave`
  - JSON body: `{"content": "<p>...</p>"}`
  - Saves document content automatically for editors/owners.

### Comments

- `POST /documents/<document_id>/comments`
  - JSON body: `{"message": "...", "parent_id": optional}`
  - Adds a comment or a reply.

- `POST /documents/<document_id>/comments/<comment_id>/resolve`
  - Resolves the specified comment.

- `POST /documents/<document_id>/comments/<comment_id>/delete`
  - Deletes the specified comment if owned by the current user or by the document owner.

### Revision History

- `GET /documents/<document_id>/history`
  - Shows past revisions for the document.

- `POST /documents/<document_id>/restore/<revision_id>`
  - Restores the document content to the selected revision.

## WebSocket Events

The editor uses Socket.IO for collaborative document editing and presence.

- `join_document`
  - Payload: `{ doc_id: <document_id> }`
  - Joins the user to the document room and emits the current document state.

- `document_update`
  - Payload: `{ doc_id: <document_id>, content: <html> }`
  - Broadcasts updated document content to other connected users.

- `cursor_update`
  - Payload: `{ doc_id: <document_id>, cursor: <cursor_info> }`
  - Updates presence information for connected users.

- `presence_update`
  - Server-emitted event with current connected users.

- `document_state`
  - Server-emitted event with the latest content for the room.

- `comment_update`
  - Server-emitted event when a comment is added or resolved.

- `comment_deleted`
  - Server-emitted event when a comment is deleted.
