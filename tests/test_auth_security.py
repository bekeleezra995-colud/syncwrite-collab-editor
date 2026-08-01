import os
import sqlite3
import tempfile
import unittest

from app import app, get_db, init_db


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

    def test_dashboard_search_filters_documents(self):
        self.register('Owner', 'owner3@example.com', 'StrongPass1!')
        self.login('owner3@example.com', 'StrongPass1!')
        self.client.post('/documents/new', data={'title': 'My Notes'}, follow_redirects=True)
        self.client.post('/documents/new', data={'title': 'Project Plan'}, follow_redirects=True)

        response = self.client.get('/dashboard?q=Project')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Project Plan', response.data)
        self.assertNotIn(b'My Notes', response.data)


if __name__ == '__main__':
    unittest.main()
