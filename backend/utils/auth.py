"""
Auth helpers.

Students authenticate via Supabase Auth — the frontend gets a Supabase
JWT and sends it as `Authorization: Bearer <token>`. We verify that
token against Supabase (using the anon client's `get_user`) rather than
re-implementing JWT verification, which keeps us correct even if
Supabase rotates its signing keys.

Ambassadors are a *separate* auth system (see services/ambassador_service.py)
with their own email+password table and their own short-lived JWT,
signed with JWT_SECRET_KEY, since they are not Supabase auth users.
"""
import functools
import jwt
from flask import request, jsonify, g

from config import Config
from services.supabase_client import get_supabase


def _extract_bearer_token():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip()


def get_current_supabase_user():
    """Return the Supabase auth user dict for the request's bearer token, or None."""
    token = _extract_bearer_token()
    if not token:
        return None
    try:
        supa = get_supabase(use_service_role=False)
        resp = supa.auth.get_user(token)
        return resp.user
    except Exception:
        return None


def require_auth(f):
    """Require a valid Supabase student session. Populates g.user_id / g.user_email."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_supabase_user()
        if not user:
            return jsonify({"success": False, "message": "Authentication required", "data": {}}), 401
        g.user_id = user.id
        g.user_email = user.email
        return f(*args, **kwargs)
    return wrapper


def require_role(*allowed_roles):
    """Require a valid session AND that the user's row in public.users has one of allowed_roles."""
    def decorator(f):
        @functools.wraps(f)
        @require_auth
        def wrapper(*args, **kwargs):
            supa = get_supabase(use_service_role=True)
            row = supa.table("users").select("role").eq("id", g.user_id).single().execute()
            role = (row.data or {}).get("role")
            if role not in allowed_roles:
                return jsonify({"success": False, "message": "Forbidden", "data": {}}), 403
            g.user_role = role
            return f(*args, **kwargs)
        return wrapper
    return decorator


# --- Ambassador JWT (independent of Supabase auth) ---

def issue_ambassador_token(ambassador_id: str, email: str) -> str:
    import datetime
    from utils.timeutils import utcnow
    payload = {
        "sub": str(ambassador_id),
        "email": email,
        "typ": "ambassador",
        "exp": utcnow() + datetime.timedelta(hours=Config.AMBASSADOR_JWT_EXPIRY_HOURS),
        "iat": utcnow(),
    }
    return jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm=Config.JWT_ALGORITHM)


def decode_ambassador_token(token: str):
    try:
        payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=[Config.JWT_ALGORITHM])
        if payload.get("typ") != "ambassador":
            return None
        return payload
    except jwt.PyJWTError:
        return None


def require_ambassador_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        token = _extract_bearer_token()
        payload = decode_ambassador_token(token) if token else None
        if not payload:
            return jsonify({"success": False, "message": "Ambassador authentication required", "data": {}}), 401
        g.ambassador_id = payload["sub"]
        g.ambassador_email = payload["email"]
        return f(*args, **kwargs)
    return wrapper


def require_admin(f):
    """Require a Supabase session whose users.role is admin or college_coordinator."""
    return require_role("admin", "college_coordinator")(f)
