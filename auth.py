"""
Authentication Blueprint for StockPerformer.

Providers supported:
  - Email + password (local)
  - Google   (OIDC via Authlib)
  - Microsoft (OIDC via Authlib, tenant=common)
  - Facebook  (OAuth 2.0 via Authlib)
  - Apple     (Sign In with Apple — manual JWT flow)

Environment variables required per provider:
  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
  MICROSOFT_CLIENT_ID / MICROSOFT_CLIENT_SECRET
  FACEBOOK_CLIENT_ID / FACEBOOK_CLIENT_SECRET
  APPLE_CLIENT_ID / APPLE_TEAM_ID / APPLE_KEY_ID
  APPLE_PRIVATE_KEY (base64-encoded .p8) or APPLE_PRIVATE_KEY_PATH

Session tracking:
  - A LoginSession row is created on every successful login.
  - Flask's signed cookie stores the session UUID (key 'sid').
  - before_request heartbeat updates last_seen_at every 60 s.
  - /api/active-sessions counts rows with last_seen_at > now-5min.
"""

import os, uuid, base64, time, json
from datetime import datetime, timedelta
from functools import wraps

import requests as req_lib
import jwt as pyjwt

from flask import (
    Blueprint, request, session, jsonify,
    redirect, url_for, current_app, send_from_directory,
)
from authlib.integrations.flask_client import OAuth
from werkzeug.security import generate_password_hash, check_password_hash

from db import Session as DbSession, User, LoginSession, BASE_DIR

auth_bp = Blueprint('auth', __name__)
oauth   = OAuth()

# ── Active-session window (seconds) ─────────────────────────────────────────
ACTIVE_WINDOW_S  = 5 * 60   # 5 minutes — matches the 90-second JS heartbeat
HEARTBEAT_SKIP_S = 60        # only write to DB once per 60 s per session


# ── Helpers ──────────────────────────────────────────────────────────────────

def _real_ip() -> str:
    xff = request.headers.get('X-Forwarded-For', '')
    return xff.split(',')[0].strip() if xff else (request.remote_addr or '')


def _geoip(ip: str) -> dict:
    """Best-effort geolocation via ip-api.com (free, no key, 45 req/min)."""
    try:
        if not ip or ip in ('127.0.0.1', '::1', 'localhost'):
            return {'country': 'Local', 'city': 'Localhost'}
        r = req_lib.get(f'http://ip-api.com/json/{ip}?fields=status,country,city',
                        timeout=2)
        d = r.json()
        if d.get('status') == 'success':
            return {'country': d.get('country'), 'city': d.get('city')}
    except Exception:
        pass
    return {'country': None, 'city': None}


def _create_db_session(user: User, provider: str, db) -> LoginSession:
    """Persist a new LoginSession and stash its ID in the Flask cookie."""
    ip  = _real_ip()
    geo = _geoip(ip)
    ls  = LoginSession(
        id            = str(uuid.uuid4()),
        user_id       = user.id,
        ip_address    = ip,
        user_agent    = request.headers.get('User-Agent'),
        country       = geo['country'],
        city          = geo['city'],
        auth_provider = provider,
        created_at    = datetime.utcnow(),
        last_seen_at  = datetime.utcnow(),
        expires_at    = datetime.utcnow() + timedelta(days=30),
        is_active     = True,
    )
    db.add(ls)
    user.updated_at    = datetime.utcnow()
    user.is_active     = True
    db.commit()

    session['sid']    = ls.id
    session['_hb_ts'] = time.time()
    session.permanent = True
    return ls


def _current_session(db) -> LoginSession | None:
    sid = session.get('sid')
    if not sid:
        return None
    ls = db.query(LoginSession).filter_by(id=sid, is_active=True).first()
    if ls and ls.expires_at and ls.expires_at < datetime.utcnow():
        ls.is_active = False
        db.commit()
        session.pop('sid', None)
        return None
    return ls


def login_required(f):
    """Decorator for API routes that need an authenticated session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        db = DbSession()
        try:
            ls = _current_session(db)
            if not ls:
                return jsonify({'error': 'Not authenticated'}), 401
        finally:
            db.close()
        return f(*args, **kwargs)
    return decorated


def register_heartbeat(app):
    """Register a before_request hook that updates last_seen_at periodically."""
    @app.before_request
    def _heartbeat():
        sid = session.get('sid')
        if not sid:
            return
        now  = time.time()
        last = session.get('_hb_ts', 0)
        if (now - last) < HEARTBEAT_SKIP_S:
            return
        db = DbSession()
        try:
            ls = db.query(LoginSession).filter_by(id=sid, is_active=True).first()
            if ls:
                ls.last_seen_at = datetime.utcnow()
                db.commit()
                session['_hb_ts'] = now
            else:
                session.pop('sid',    None)
                session.pop('_hb_ts', None)
        except Exception:
            db.rollback()
        finally:
            db.close()


# ── OAuth provider setup ─────────────────────────────────────────────────────

def init_oauth(app):
    oauth.init_app(app)

    if os.environ.get('GOOGLE_CLIENT_ID'):
        oauth.register(
            name='google',
            client_id=os.environ['GOOGLE_CLIENT_ID'],
            client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
            server_metadata_url=(
                'https://accounts.google.com/.well-known/openid-configuration'
            ),
            client_kwargs={'scope': 'openid email profile'},
        )

    if os.environ.get('MICROSOFT_CLIENT_ID'):
        tenant = os.environ.get('MICROSOFT_TENANT', 'common')
        oauth.register(
            name='microsoft',
            client_id=os.environ['MICROSOFT_CLIENT_ID'],
            client_secret=os.environ['MICROSOFT_CLIENT_SECRET'],
            authorize_url=(
                f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize'
            ),
            access_token_url=(
                f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'
            ),
            jwks_uri=(
                f'https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys'
            ),
            client_kwargs={'scope': 'openid email profile'},
        )

    if os.environ.get('FACEBOOK_CLIENT_ID'):
        oauth.register(
            name='facebook',
            client_id=os.environ['FACEBOOK_CLIENT_ID'],
            client_secret=os.environ['FACEBOOK_CLIENT_SECRET'],
            authorize_url='https://www.facebook.com/dialog/oauth',
            access_token_url='https://graph.facebook.com/oauth/access_token',
            api_base_url='https://graph.facebook.com/',
            client_kwargs={'scope': 'email,public_profile'},
        )
    # Apple is handled manually (POST callback + dynamic JWT client_secret)


def _apple_client_secret() -> str | None:
    """Generate a short-lived JWT used as the Apple client_secret."""
    key_b64  = os.environ.get('APPLE_PRIVATE_KEY')
    key_path = os.environ.get('APPLE_PRIVATE_KEY_PATH')
    team_id  = os.environ.get('APPLE_TEAM_ID')
    key_id   = os.environ.get('APPLE_KEY_ID')
    client_id = os.environ.get('APPLE_CLIENT_ID')

    if not all([team_id, key_id, client_id]):
        return None
    try:
        if key_b64:
            private_key = base64.b64decode(key_b64).decode()
        elif key_path:
            with open(key_path) as f:
                private_key = f.read()
        else:
            return None

        now = int(time.time())
        return pyjwt.encode(
            {'iss': team_id, 'iat': now, 'exp': now + 86400 * 180,
             'aud': 'https://appleid.apple.com', 'sub': client_id},
            private_key,
            algorithm='ES256',
            headers={'kid': key_id},
        )
    except Exception as e:
        print(f'[WARN] Apple client secret generation failed: {e}')
        return None


# ── Routes: static pages ──────────────────────────────────────────────────────

@auth_bp.route('/login')
def login_page():
    return send_from_directory(BASE_DIR, 'login.html')


# ── Routes: email + password ──────────────────────────────────────────────────

@auth_bp.route('/auth/register', methods=['POST'])
def register():
    data  = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    pwd   = data.get('password', '')
    name  = (data.get('display_name') or '').strip() or email.split('@')[0]

    if not email or not pwd:
        return jsonify({'ok': False, 'error': 'Email and password are required.'}), 400
    if len(pwd) < 8:
        return jsonify({'ok': False, 'error': 'Password must be at least 8 characters.'}), 400

    db = DbSession()
    try:
        if db.query(User).filter_by(email=email).first():
            return jsonify({'ok': False, 'error': 'An account with this email already exists.'}), 409
        user = User(
            id=str(uuid.uuid4()), email=email,
            password_hash=generate_password_hash(pwd),
            display_name=name,
        )
        db.add(user)
        db.commit()
        _create_db_session(user, 'email', db)
        return jsonify({'ok': True, 'user': user.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        db.close()


@auth_bp.route('/auth/login', methods=['POST'])
def login():
    data  = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    pwd   = data.get('password', '')

    if not email or not pwd:
        return jsonify({'ok': False, 'error': 'Email and password are required.'}), 400

    db = DbSession()
    try:
        user = db.query(User).filter_by(email=email, is_active=True).first()
        if not user or not user.password_hash:
            return jsonify({'ok': False, 'error': 'Invalid email or password.'}), 401
        if not check_password_hash(user.password_hash, pwd):
            return jsonify({'ok': False, 'error': 'Invalid email or password.'}), 401
        _create_db_session(user, 'email', db)
        return jsonify({'ok': True, 'user': user.to_dict()})
    finally:
        db.close()


@auth_bp.route('/auth/logout', methods=['POST', 'GET'])
def logout():
    sid = session.get('sid')
    if sid:
        db = DbSession()
        try:
            ls = db.query(LoginSession).filter_by(id=sid).first()
            if ls:
                ls.is_active = False
                db.commit()
        finally:
            db.close()
    session.clear()
    return jsonify({'ok': True})


# ── Routes: Google OAuth ──────────────────────────────────────────────────────

@auth_bp.route('/auth/google/login')
def google_login():
    if not os.environ.get('GOOGLE_CLIENT_ID'):
        return jsonify({'error': 'Google OAuth not configured'}), 503
    cb = url_for('auth.google_callback', _external=True)
    return oauth.google.authorize_redirect(cb)


@auth_bp.route('/auth/google/callback')
def google_callback():
    try:
        token    = oauth.google.authorize_access_token()
        userinfo = token.get('userinfo') or oauth.google.userinfo()
    except Exception as e:
        return redirect(f'/login?error={e}')

    email    = (userinfo.get('email') or '').lower()
    g_id     = userinfo.get('sub')
    name     = userinfo.get('name') or email.split('@')[0]
    picture  = userinfo.get('picture')

    return _upsert_and_redirect(
        provider='google', provider_field='google_id',
        provider_id=g_id, email=email, name=name, picture=picture,
    )


# ── Routes: Microsoft OAuth ───────────────────────────────────────────────────

@auth_bp.route('/auth/microsoft/login')
def microsoft_login():
    if not os.environ.get('MICROSOFT_CLIENT_ID'):
        return jsonify({'error': 'Microsoft OAuth not configured'}), 503
    cb = url_for('auth.microsoft_callback', _external=True)
    return oauth.microsoft.authorize_redirect(cb)


@auth_bp.route('/auth/microsoft/callback')
def microsoft_callback():
    try:
        token    = oauth.microsoft.authorize_access_token()
        userinfo = token.get('userinfo') or {}
        if not userinfo:
            # Fall back to Graph API
            resp     = oauth.microsoft.get(
                'https://graph.microsoft.com/v1.0/me', token=token
            )
            userinfo = resp.json()
    except Exception as e:
        return redirect(f'/login?error={e}')

    email   = (userinfo.get('email') or userinfo.get('mail') or
               userinfo.get('userPrincipalName') or '').lower()
    ms_id   = userinfo.get('sub') or userinfo.get('id')
    name    = userinfo.get('name') or userinfo.get('displayName') or email.split('@')[0]

    return _upsert_and_redirect(
        provider='microsoft', provider_field='microsoft_id',
        provider_id=ms_id, email=email, name=name, picture=None,
    )


# ── Routes: Facebook OAuth ────────────────────────────────────────────────────

@auth_bp.route('/auth/facebook/login')
def facebook_login():
    if not os.environ.get('FACEBOOK_CLIENT_ID'):
        return jsonify({'error': 'Facebook OAuth not configured'}), 503
    cb = url_for('auth.facebook_callback', _external=True)
    return oauth.facebook.authorize_redirect(cb)


@auth_bp.route('/auth/facebook/callback')
def facebook_callback():
    try:
        token    = oauth.facebook.authorize_access_token()
        resp     = oauth.facebook.get(
            'me?fields=id,name,email,picture.width(200)',
            token=token,
        )
        userinfo = resp.json()
    except Exception as e:
        return redirect(f'/login?error={e}')

    fb_id   = userinfo.get('id')
    email   = (userinfo.get('email') or f'{fb_id}@facebook.invalid').lower()
    name    = userinfo.get('name') or email.split('@')[0]
    picture = (userinfo.get('picture', {}).get('data', {}).get('url'))

    return _upsert_and_redirect(
        provider='facebook', provider_field='facebook_id',
        provider_id=fb_id, email=email, name=name, picture=picture,
    )


# ── Routes: Apple Sign In ─────────────────────────────────────────────────────

@auth_bp.route('/auth/apple/login')
def apple_login():
    client_id  = os.environ.get('APPLE_CLIENT_ID')
    if not client_id:
        return jsonify({'error': 'Apple Sign In not configured'}), 503

    state = str(uuid.uuid4())
    session['apple_state'] = state
    cb    = url_for('auth.apple_callback', _external=True)
    params = (
        f'https://appleid.apple.com/auth/authorize'
        f'?client_id={client_id}'
        f'&redirect_uri={cb}'
        f'&response_type=code'
        f'&scope=name%20email'
        f'&response_mode=form_post'
        f'&state={state}'
    )
    return redirect(params)


@auth_bp.route('/auth/apple/callback', methods=['POST'])
def apple_callback():
    """Apple sends a POST with code, state, and (first-login-only) user JSON."""
    state      = request.form.get('state')
    code       = request.form.get('code')
    user_json  = request.form.get('user')   # only on first sign-in
    error      = request.form.get('error')

    if error or not code:
        return redirect(f'/login?error={error or "apple_cancelled"}')
    if state != session.pop('apple_state', None):
        return redirect('/login?error=state_mismatch')

    client_id     = os.environ.get('APPLE_CLIENT_ID')
    client_secret = _apple_client_secret()
    if not client_secret:
        return redirect('/login?error=apple_misconfigured')

    cb = url_for('auth.apple_callback', _external=True)
    try:
        resp = req_lib.post('https://appleid.apple.com/auth/token', data={
            'client_id':     client_id,
            'client_secret': client_secret,
            'code':          code,
            'grant_type':    'authorization_code',
            'redirect_uri':  cb,
        }, timeout=10)
        token_data = resp.json()
        id_token   = token_data.get('id_token')
        if not id_token:
            return redirect('/login?error=apple_no_token')

        # Decode without signature verification for claims (Apple's JWKS can be
        # used for full verification; here we trust the HTTPS token endpoint).
        claims = pyjwt.decode(id_token, options={'verify_signature': False})
        apple_id = claims.get('sub')
        email    = (claims.get('email') or '').lower()

        # Apple only sends name on the very first sign-in
        name = None
        if user_json:
            try:
                ud   = json.loads(user_json)
                fn   = ud.get('name', {}).get('firstName', '')
                ln   = ud.get('name', {}).get('lastName', '')
                name = f'{fn} {ln}'.strip() or None
            except Exception:
                pass
        name = name or email.split('@')[0]

    except Exception as e:
        return redirect(f'/login?error=apple_token_exchange')

    return _upsert_and_redirect(
        provider='apple', provider_field='apple_id',
        provider_id=apple_id, email=email, name=name, picture=None,
    )


# ── Shared OAuth upsert helper ────────────────────────────────────────────────

def _upsert_and_redirect(*, provider, provider_field,
                          provider_id, email, name, picture):
    """
    Find or create a User row for an OAuth login, then create a session.
    Merges accounts if the same email already exists under a different provider.
    """
    db = DbSession()
    try:
        # 1. Look up by provider ID
        user = db.query(User).filter(
            getattr(User, provider_field) == provider_id
        ).first()

        if not user and email:
            # 2. Fall back to email match (allows linking multiple providers)
            user = db.query(User).filter_by(email=email).first()
            if user:
                setattr(user, provider_field, provider_id)

        if not user:
            # 3. New user
            user = User(
                id=str(uuid.uuid4()),
                email=email or f'{provider_id}@{provider}.invalid',
                display_name=name,
                avatar_url=picture,
            )
            setattr(user, provider_field, provider_id)
            db.add(user)
            db.commit()
        else:
            # Update changeable fields
            if picture and not user.avatar_url:
                user.avatar_url = picture
            if name and not user.display_name:
                user.display_name = name
            db.commit()

        _create_db_session(user, provider, db)
        return redirect('/')
    except Exception as e:
        db.rollback()
        return redirect(f'/login?error={e}')
    finally:
        db.close()


# ── API: current user ─────────────────────────────────────────────────────────

@auth_bp.route('/api/me')
def api_me():
    db = DbSession()
    try:
        ls = _current_session(db)
        if not ls:
            return jsonify({'logged_in': False})
        u = ls.user
        return jsonify({
            'logged_in':    True,
            'id':           u.id,
            'email':        u.email,
            'display_name': u.display_name or u.email.split('@')[0],
            'avatar_url':   u.avatar_url,
        })
    finally:
        db.close()


# ── API: active sessions count ────────────────────────────────────────────────

@auth_bp.route('/api/active-sessions')
def api_active_sessions():
    db  = DbSession()
    try:
        cutoff = datetime.utcnow() - timedelta(seconds=ACTIVE_WINDOW_S)
        count  = db.query(LoginSession).filter(
            LoginSession.is_active    == True,
            LoginSession.last_seen_at >= cutoff,
        ).count()
        return jsonify({'active': count})
    finally:
        db.close()


# ── API: current user's login history ────────────────────────────────────────

@auth_bp.route('/api/user/sessions')
@login_required
def api_user_sessions():
    db  = DbSession()
    try:
        sid    = session['sid']
        ls_now = db.query(LoginSession).filter_by(id=sid).first()
        rows   = (
            db.query(LoginSession)
            .filter_by(user_id=ls_now.user_id)
            .order_by(LoginSession.created_at.desc())
            .limit(50)
            .all()
        )
        return jsonify({'sessions': [r.to_dict(sid) for r in rows]})
    finally:
        db.close()


# ── API: all users (admin — protect in production) ────────────────────────────

@auth_bp.route('/api/users')
def api_users():
    db = DbSession()
    try:
        cutoff = datetime.utcnow() - timedelta(seconds=ACTIVE_WINDOW_S)
        users  = db.query(User).filter_by(is_active=True).all()
        result = []
        for u in users:
            active_count = sum(
                1 for s in u.sessions
                if s.is_active and s.last_seen_at and s.last_seen_at >= cutoff
            )
            result.append({
                **u.to_dict(),
                'active_sessions': active_count,
                'total_sessions':  len(u.sessions),
            })
        return jsonify({'users': result, 'total': len(result)})
    finally:
        db.close()
