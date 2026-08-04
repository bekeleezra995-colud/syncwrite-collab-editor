import os
import sqlite3
import tempfile
import unittest

from app import app, get_db, init_db, socketio


class AppIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_file = tempfile.mkstemp(suffix='.db')
        app.config['DATABASE'] = self.db_file
        app.config['TESTING'] = True
        self.client = app.test_client()
        init_db()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_file)

    def register(self, name, email, password):
        return self.client.post('/register', data={'name': name, 'email': email, 'password': password}, follow_redirects=True)

    def login(self, email, password):
        return self.client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)

    def test_notification_banner_is_rendered_once(self):
        self.register('Owner', 'owner-notify@example.com', 'StrongPass1!')
        self.login('owner-notify@example.com', 'StrongPass1!')

        with self.client.session_transaction() as session:
            session['notification'] = 'Document renamed successfully.'

        response = self.client.get('/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Document renamed successfully.', response.data)

    def test_registration_and_login(self):
        response = self.register('Test User', 'test@example.com', 'StrongPass1!')
        self.assertIn(b'Login', response.data)

        response = self.login('test@example.com', 'StrongPass1!')
        self.assertIn(b'Dashboard', response.data)

    def test_document_creation_and_sharing_permissions(self):
        self.register('Owner', 'owner@example.com', 'StrongPass1!')
        self.login('owner@example.com', 'StrongPass1!')

        response = self.client.post('/documents/new', data={'title': 'Permission Doc'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Permission Doc', response.data)

        conn = get_db()
        doc = conn.execute('SELECT id FROM documents WHERE title = ?', ('Permission Doc',)).fetchone()
        conn.close()
        self.assertIsNotNone(doc)
        document_id = doc['id']

        self.register('Viewer', 'viewer@example.com', 'StrongPass1!')
        self.client.get('/logout', follow_redirects=True)
        self.login('owner@example.com', 'StrongPass1!')

        response = self.client.post(f'/documents/{document_id}/share', data={'email': 'viewer@example.com', 'permission': 'viewer'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        self.client.get('/logout', follow_redirects=True)
        self.login('viewer@example.com', 'StrongPass1!')

        blocked_response = self.client.post(f'/documents/{document_id}/autosave', json={'content': '<p>hack</p>'})
        self.assertEqual(blocked_response.status_code, 403)

        self.client.get('/logout', follow_redirects=True)
        self.login('owner@example.com', 'StrongPass1!')

        allowed_response = self.client.post(f'/documents/{document_id}/autosave', json={'content': '<p>owner save</p>'})
        self.assertEqual(allowed_response.status_code, 200)

    def test_rename_document_rejects_invalid_title(self):
        self.register('Owner', 'owner9@example.com', 'StrongPass1!')
        self.login('owner9@example.com', 'StrongPass1!')
        self.client.post('/documents/new', data={'title': 'Title Check'}, follow_redirects=True)

        conn = get_db()
        doc = conn.execute('SELECT id FROM documents WHERE title = ?', ('Title Check',)).fetchone()
        conn.close()

        response = self.client.post(f'/documents/{doc["id"]}/rename', data={'title': ''}, follow_redirects=True)
        self.assertEqual(response.status_code, 400)

    def test_autosave_rejects_oversized_content(self):
        self.register('Owner', 'owner10@example.com', 'StrongPass1!')
        self.login('owner10@example.com', 'StrongPass1!')
        self.client.post('/documents/new', data={'title': 'Oversize Doc'}, follow_redirects=True)

        conn = get_db()
        doc = conn.execute('SELECT id FROM documents WHERE title = ?', ('Oversize Doc',)).fetchone()
        conn.close()

        oversized_content = '<p>' + ('x' * 200001) + '</p>'
        response = self.client.post(f'/documents/{doc["id"]}/autosave', json={'content': oversized_content})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Content is too large', response.data)

    def test_forgot_password_flow_supports_password_reset(self):
        self.register('Owner', 'owner2@example.com', 'StrongPass1!')

        response = self.client.post('/forgot-password', data={'email': 'owner2@example.com'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'password reset', response.data.lower())

        conn = get_db()
        token_row = conn.execute('SELECT token FROM password_reset_tokens WHERE email = ?', ('owner2@example.com',)).fetchone()
        conn.close()
        self.assertIsNotNone(token_row)

        response = self.client.post(
            f"/reset-password/{token_row['token']}",
            data={'password': 'NewStrongPass1!', 'confirm_password': 'NewStrongPass1!'},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'password updated', response.data.lower())

        response = self.client.post('/login', data={'email': 'owner2@example.com', 'password': 'NewStrongPass1!'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Dashboard', response.data)

    def test_history_page_access(self):
        self.register('Owner', 'owner2@example.com', 'StrongPass1!')
        self.login('owner2@example.com', 'StrongPass1!')
        self.client.post('/documents/new', data={'title': 'History Doc'}, follow_redirects=True)

        conn = get_db()
        doc = conn.execute('SELECT id FROM documents WHERE title = ?', ('History Doc',)).fetchone()
        conn.close()
        self.assertIsNotNone(doc)

        response = self.client.get(f'/documents/{doc[0]}/history')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Version History', response.data)

    def test_registration_requires_matching_password_confirmation(self):
        response = self.client.post(
            '/register',
            data={
                'name': 'Bekele',
                'email': 'bekele@example.com',
                'password': 'StrongPass1!',
                'confirm_password': 'DifferentPass1!'
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Passwords do not match', response.data)

    def test_registration_rejects_invalid_email_format(self):
        response = self.client.post(
            '/register',
            data={
                'name': 'Bekele',
                'email': 'bekelegmail.com',
                'password': 'StrongPass1!',
                'confirm_password': 'StrongPass1!'
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Please enter a valid email address', response.data)

    def test_dashboard_search_filters_documents(self):
        self.register('Owner', 'owner3@example.com', 'StrongPass1!')
        self.login('owner3@example.com', 'StrongPass1!')
        self.client.post('/documents/new', data={'title': 'My Notes'}, follow_redirects=True)
        self.client.post('/documents/new', data={'title': 'Project Plan'}, follow_redirects=True)

        response = self.client.get('/dashboard?q=Project')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Project Plan', response.data)
        self.assertNotIn(b'My Notes', response.data)

    def test_dashboard_displays_authenticated_user_info_and_create_action(self):
        self.register('Owner', 'owner4@example.com', 'StrongPass1!')
        self.login('owner4@example.com', 'StrongPass1!')

        response = self.client.get('/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Owner', response.data)
        self.assertIn(b'owner4@example.com', response.data)
        self.assertIn(b'Create New Document', response.data)
        self.assertIn(b'No owned documents yet.', response.data)
        self.assertIn(b'No shared documents.', response.data)
        self.assertIn(b'No recent documents.', response.data)

    def test_document_view_shows_presence_summary_for_current_user(self):
        self.register('Owner', 'owner6@example.com', 'StrongPass1!')
        self.login('owner6@example.com', 'StrongPass1!')
        self.client.post('/documents/new', data={'title': 'Presence Summary Doc'}, follow_redirects=True)

        conn = get_db()
        doc = conn.execute('SELECT id FROM documents WHERE title = ?', ('Presence Summary Doc',)).fetchone()
        conn.close()
        self.assertIsNotNone(doc)

        response = self.client.get(f'/documents/{doc["id"]}')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Viewing now', response.data)
        self.assertIn(b'You are online', response.data)

    def test_socketio_collaboration_broadcasts_document_updates(self):
        self.register('Owner', 'owner6@example.com', 'StrongPass1!')
        self.login('owner6@example.com', 'StrongPass1!')
        self.client.post('/documents/new', data={'title': 'Shared Doc'}, follow_redirects=True)

        conn = get_db()
        doc = conn.execute('SELECT id FROM documents WHERE title = ?', ('Shared Doc',)).fetchone()
        conn.close()
        self.assertIsNotNone(doc)
        document_id = doc['id']

        collaborator_client = app.test_client()
        collaborator_client.post('/register', data={'name': 'Collaborator', 'email': 'collaborator@example.com', 'password': 'StrongPass1!'}, follow_redirects=True)
        collaborator_client.post('/login', data={'email': 'collaborator@example.com', 'password': 'StrongPass1!'}, follow_redirects=True)

        self.client.post(f'/documents/{document_id}/share', data={'email': 'collaborator@example.com', 'permission': 'editor'}, follow_redirects=True)

        owner_socket = socketio.test_client(app, flask_test_client=self.client)
        collaborator_socket = socketio.test_client(app, flask_test_client=collaborator_client)
        socketio.sleep(0.1)

        owner_socket.emit('join_document', {'doc_id': document_id})
        collaborator_socket.emit('join_document', {'doc_id': document_id})
        socketio.sleep(0.1)

        owner_socket.emit('document_update', {'doc_id': document_id, 'content': '<p>hello</p>'})
        socketio.sleep(0.1)

        collaborator_events = collaborator_socket.get_received()
        self.assertTrue(any(event['name'] == 'document_update' and event['args'][0]['content'] == '<p>hello</p>' for event in collaborator_events))

        owner_socket.disconnect()
        collaborator_socket.disconnect()

    def test_presence_awareness_and_autosave_persistence(self):
        self.register('Owner', 'owner7@example.com', 'StrongPass1!')
        self.login('owner7@example.com', 'StrongPass1!')
        self.client.post('/documents/new', data={'title': 'Shared Presence Doc'}, follow_redirects=True)

        conn = get_db()
        doc = conn.execute('SELECT id FROM documents WHERE title = ?', ('Shared Presence Doc',)).fetchone()
        conn.close()
        self.assertIsNotNone(doc)
        document_id = doc['id']

        collaborator_client = app.test_client()
        collaborator_client.post('/register', data={'name': 'Collaborator', 'email': 'collab7@example.com', 'password': 'StrongPass1!'}, follow_redirects=True)
        collaborator_client.post('/login', data={'email': 'collab7@example.com', 'password': 'StrongPass1!'}, follow_redirects=True)

        self.client.post(f'/documents/{document_id}/share', data={'email': 'collab7@example.com', 'permission': 'editor'}, follow_redirects=True)

        owner_socket = socketio.test_client(app, flask_test_client=self.client)
        collaborator_socket = socketio.test_client(app, flask_test_client=collaborator_client)
        socketio.sleep(0.1)

        owner_socket.emit('join_document', {'doc_id': document_id})
        collaborator_socket.emit('join_document', {'doc_id': document_id})
        socketio.sleep(0.1)

        owner_socket.emit('cursor_update', {'doc_id': document_id, 'cursor': {'index': 5, 'length': 0}, 'typing': True})
        socketio.sleep(0.1)

        presence_events = collaborator_socket.get_received()
        self.assertTrue(any(event['name'] == 'presence_update' for event in presence_events))

        autosave_response = self.client.post(
            f'/documents/{document_id}/autosave',
            json={'content': '<p>auto saved</p>', 'summary': 'Autosave verification'},
            follow_redirects=True,
        )
        self.assertEqual(autosave_response.status_code, 200)

        conn = get_db()
        saved_doc = conn.execute('SELECT content FROM documents WHERE id = ?', (document_id,)).fetchone()
        conn.close()
        self.assertEqual(saved_doc['content'], '<p>auto saved</p>')

        owner_socket.disconnect()
        collaborator_socket.disconnect()

    def test_version_history_restore_and_comments_workflow(self):
        self.register('Owner', 'owner8@example.com', 'StrongPass1!')
        self.login('owner8@example.com', 'StrongPass1!')

        self.client.post('/documents/new', data={'title': 'History Comment Doc'}, follow_redirects=True)

        conn = get_db()
        doc = conn.execute('SELECT id FROM documents WHERE title = ?', ('History Comment Doc',)).fetchone()
        conn.close()
        self.assertIsNotNone(doc)

        self.client.post(
            f'/documents/{doc["id"]}/autosave',
            json={'content': '<p>first draft</p>', 'summary': 'Initial content'},
            follow_redirects=True,
        )
        self.client.post(
            f'/documents/{doc["id"]}/autosave',
            json={'content': '<p>second draft</p>', 'summary': 'Updated content'},
            follow_redirects=True,
        )

        history_response = self.client.get(f'/documents/{doc["id"]}/history')
        self.assertEqual(history_response.status_code, 200)
        self.assertIn(b'Version History', history_response.data)

        conn = get_db()
        revisions = conn.execute('SELECT id, revision_number, content FROM revisions WHERE document_id = ? ORDER BY revision_number DESC', (doc['id'],)).fetchall()
        conn.close()
        self.assertGreaterEqual(len(revisions), 2)

        restore_response = self.client.post(f"/documents/{doc['id']}/restore/{revisions[0]['id']}", follow_redirects=True)
        self.assertEqual(restore_response.status_code, 200)

        comment_response = self.client.post(
            f'/documents/{doc["id"]}/comments',
            json={'message': 'Please update the draft.'},
            follow_redirects=True,
        )
        self.assertEqual(comment_response.status_code, 200)
        comment_payload = comment_response.get_json()
        self.assertIn('comment', comment_payload)

        reply_response = self.client.post(
            f'/documents/{doc["id"]}/comments',
            json={'message': 'This is a reply.', 'parent_id': comment_payload['comment']['id']},
            follow_redirects=True,
        )
        self.assertEqual(reply_response.status_code, 200)

        resolve_response = self.client.post(f"/documents/{doc['id']}/comments/{comment_payload['comment']['id']}/resolve", follow_redirects=True)
        self.assertEqual(resolve_response.status_code, 200)

        delete_response = self.client.post(f"/documents/{doc['id']}/comments/{comment_payload['comment']['id']}/delete", follow_redirects=True)
        self.assertEqual(delete_response.status_code, 200)

    def test_document_management_supports_rename_duplicate_and_delete(self):
        self.register('Owner', 'owner5@example.com', 'StrongPass1!')
        self.login('owner5@example.com', 'StrongPass1!')

        create_response = self.client.post('/documents/new', data={'title': 'Project Proposal'}, follow_redirects=True)
        self.assertEqual(create_response.status_code, 200)

        conn = get_db()
        doc = conn.execute('SELECT id, title, owner_id, created_at, updated_at FROM documents WHERE title = ?', ('Project Proposal',)).fetchone()
        conn.close()
        self.assertIsNotNone(doc)

        rename_response = self.client.post(f'/documents/{doc["id"]}/rename', data={'title': 'Project Proposal Updated'}, follow_redirects=True)
        self.assertEqual(rename_response.status_code, 200)
        self.assertIn(b'Project Proposal Updated', rename_response.data)

        duplicate_response = self.client.post(f'/documents/{doc["id"]}/duplicate', follow_redirects=True)
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertIn(b'Project Proposal Updated (Copy)', duplicate_response.data)

        conn = get_db()
        duplicate = conn.execute('SELECT id, title FROM documents WHERE title = ?', ('Project Proposal Updated (Copy)',)).fetchone()
        conn.close()
        self.assertIsNotNone(duplicate)

        delete_response = self.client.post(f'/documents/{duplicate["id"]}/delete', follow_redirects=True)
        self.assertEqual(delete_response.status_code, 200)

        conn = get_db()
        remaining = conn.execute('SELECT id FROM documents WHERE id = ?', (duplicate['id'],)).fetchone()
        conn.close()
        self.assertIsNone(remaining)


if __name__ == '__main__':
    unittest.main()
