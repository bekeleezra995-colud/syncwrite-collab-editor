# Database Schema

This application uses SQLite for local persistence. The schema is defined in `app.py` and includes the following tables:

## users
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `name` TEXT NOT NULL
- `email` TEXT UNIQUE NOT NULL
- `password` TEXT NOT NULL
- `created_at` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP

## documents
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `title` TEXT NOT NULL
- `owner_id` INTEGER NOT NULL
- `content` TEXT NOT NULL DEFAULT '<p></p>'
- `created_at` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
- `updated_at` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
- `last_opened_at` TEXT

## document_permissions
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `document_id` INTEGER NOT NULL
- `user_id` INTEGER NOT NULL
- `permission` TEXT NOT NULL CHECK(permission IN ('viewer', 'commenter', 'editor'))
- `created_at` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP

## revisions
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `document_id` INTEGER NOT NULL
- `revision_number` INTEGER NOT NULL
- `content` TEXT NOT NULL
- `created_by` INTEGER NOT NULL
- `created_at` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
- `summary` TEXT NOT NULL DEFAULT 'Autosave'

## comments
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `document_id` INTEGER NOT NULL
- `author_id` INTEGER NOT NULL
- `parent_id` INTEGER DEFAULT NULL
- `message` TEXT NOT NULL
- `resolved` INTEGER NOT NULL DEFAULT 0
- `created_at` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP

## Foreign keys
- `documents.owner_id` references `users.id`
- `document_permissions.document_id` references `documents.id`
- `document_permissions.user_id` references `users.id`
- `revisions.document_id` references `documents.id`
- `revisions.created_by` references `users.id`
- `comments.document_id` references `documents.id`
- `comments.author_id` references `users.id`
- `comments.parent_id` references `comments.id`
