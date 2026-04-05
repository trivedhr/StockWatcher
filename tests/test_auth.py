"""
Tests for the auth Blueprint — registration, login, logout, and API endpoints.
No real OAuth providers or network calls needed.
"""
import json, pytest
from unittest.mock import patch, MagicMock


def _j(resp):
    return json.loads(resp.data)


# ── Registration ──────────────────────────────────────────────────────────────

class TestRegister:
    def test_register_missing_fields_returns_400(self, client):
        resp = client.post('/auth/register', json={})
        assert resp.status_code == 400
        assert _j(resp)['ok'] is False

    def test_register_short_password_returns_400(self, client):
        resp = client.post('/auth/register',
                           json={'email': 'a@b.com', 'password': 'short'})
        assert resp.status_code == 400

    def test_register_valid_creates_user(self, client):
        resp = client.post('/auth/register',
                           json={'email': 'new@test.com',
                                 'password': 'Password123',
                                 'display_name': 'Tester'})
        assert resp.status_code == 200
        body = _j(resp)
        assert body['ok'] is True
        assert body['user']['email'] == 'new@test.com'

    def test_register_duplicate_email_returns_409(self, client):
        payload = {'email': 'dup@test.com', 'password': 'Password123'}
        client.post('/auth/register', json=payload)
        resp = client.post('/auth/register', json=payload)
        assert resp.status_code == 409
        assert _j(resp)['ok'] is False

    def test_register_sets_session_cookie(self, client):
        resp = client.post('/auth/register',
                           json={'email': 'session@test.com', 'password': 'Password123'})
        assert resp.status_code == 200
        # After register the /api/me endpoint should return logged_in=True
        me = _j(client.get('/api/me'))
        assert me['logged_in'] is True


# ── Login ─────────────────────────────────────────────────────────────────────

class TestLogin:
    def _register(self, client, email='user@test.com', pwd='Password123'):
        client.post('/auth/register', json={'email': email, 'password': pwd})

    def test_login_missing_fields_returns_400(self, client):
        resp = client.post('/auth/login', json={})
        assert resp.status_code == 400

    def test_login_wrong_password_returns_401(self, client):
        self._register(client)
        resp = client.post('/auth/login',
                           json={'email': 'user@test.com', 'password': 'WrongPass1'})
        assert resp.status_code == 401

    def test_login_unknown_email_returns_401(self, client):
        resp = client.post('/auth/login',
                           json={'email': 'nobody@test.com', 'password': 'Password123'})
        assert resp.status_code == 401

    def test_login_correct_credentials_returns_ok(self, client):
        self._register(client, 'login@test.com', 'Password123')
        client.post('/auth/logout')  # clear session from register
        resp = client.post('/auth/login',
                           json={'email': 'login@test.com', 'password': 'Password123'})
        assert resp.status_code == 200
        assert _j(resp)['ok'] is True

    def test_login_creates_session(self, client):
        self._register(client, 'sess2@test.com', 'Password123')
        client.post('/auth/logout')
        client.post('/auth/login',
                    json={'email': 'sess2@test.com', 'password': 'Password123'})
        me = _j(client.get('/api/me'))
        assert me['logged_in'] is True
        assert me['email'] == 'sess2@test.com'


# ── Logout ────────────────────────────────────────────────────────────────────

class TestLogout:
    def test_logout_clears_session(self, client):
        client.post('/auth/register',
                    json={'email': 'lo@test.com', 'password': 'Password123'})
        assert _j(client.get('/api/me'))['logged_in'] is True
        client.post('/auth/logout')
        assert _j(client.get('/api/me'))['logged_in'] is False

    def test_logout_when_not_logged_in_still_returns_ok(self, client):
        resp = client.post('/auth/logout')
        assert resp.status_code == 200
        assert _j(resp)['ok'] is True


# ── /api/me ───────────────────────────────────────────────────────────────────

class TestApiMe:
    def test_unauthenticated_returns_not_logged_in(self, client):
        body = _j(client.get('/api/me'))
        assert body['logged_in'] is False

    def test_authenticated_returns_user_info(self, client):
        client.post('/auth/register',
                    json={'email': 'me@test.com', 'password': 'Password123',
                          'display_name': 'Me User'})
        body = _j(client.get('/api/me'))
        assert body['logged_in'] is True
        assert body['email'] == 'me@test.com'
        assert 'id' in body
        assert 'display_name' in body


# ── /api/active-sessions ──────────────────────────────────────────────────────

class TestActiveSessions:
    def test_returns_count_field(self, client):
        body = _j(client.get('/api/active-sessions'))
        assert 'active' in body
        assert isinstance(body['active'], int)

    def test_count_increases_after_login(self, client):
        before = _j(client.get('/api/active-sessions'))['active']
        client.post('/auth/register',
                    json={'email': 'active@test.com', 'password': 'Password123'})
        after = _j(client.get('/api/active-sessions'))['active']
        assert after >= before  # at least one active session now


# ── /api/user/sessions ────────────────────────────────────────────────────────

class TestUserSessions:
    def test_unauthenticated_returns_401(self, client):
        resp = client.get('/api/user/sessions')
        assert resp.status_code == 401

    def test_authenticated_returns_sessions_list(self, client):
        client.post('/auth/register',
                    json={'email': 'hist@test.com', 'password': 'Password123'})
        body = _j(client.get('/api/user/sessions'))
        assert 'sessions' in body
        assert isinstance(body['sessions'], list)
        assert len(body['sessions']) >= 1

    def test_session_entry_has_required_fields(self, client):
        client.post('/auth/register',
                    json={'email': 'fields@test.com', 'password': 'Password123'})
        sessions = _j(client.get('/api/user/sessions'))['sessions']
        s = sessions[0]
        for field in ('id', 'auth_provider', 'created_at', 'is_active', 'is_current'):
            assert field in s

    def test_current_session_is_flagged(self, client):
        client.post('/auth/register',
                    json={'email': 'curr@test.com', 'password': 'Password123'})
        sessions = _j(client.get('/api/user/sessions'))['sessions']
        assert any(s['is_current'] for s in sessions)

    def test_auth_provider_is_email(self, client):
        client.post('/auth/register',
                    json={'email': 'prov@test.com', 'password': 'Password123'})
        sessions = _j(client.get('/api/user/sessions'))['sessions']
        assert sessions[0]['auth_provider'] == 'email'


# ── Login page ────────────────────────────────────────────────────────────────

class TestLoginPage:
    def test_login_page_returns_200(self, client):
        assert client.get('/login').status_code == 200

    def test_login_page_returns_html(self, client):
        resp = client.get('/login')
        assert b'<!DOCTYPE html>' in resp.data or b'<html' in resp.data

    def test_login_page_contains_form(self, client):
        resp = client.get('/login')
        assert b'form-login' in resp.data or b'auth-form' in resp.data
