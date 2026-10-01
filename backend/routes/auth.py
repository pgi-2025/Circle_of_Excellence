"""
Student auth routes.

Signup/login themselves happen client-side via the Supabase JS SDK
(supabase.auth.signUp / signInWithPassword) — the frontend already does
this. This blueprint covers what the backend needs to own: creating the
matching public.users row right after signup, and returning "me".
"""
from flask import Blueprint, request, jsonify, g

from services.supabase_client import get_supabase
from services.ambassador_service import attribute_registration
from utils.auth import require_auth

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.post("/bootstrap-profile")
@require_auth
def bootstrap_profile():
    """Called right after Supabase signUp() to create the public.users row."""
    payload = request.get_json(silent=True) or {}
    supa = get_supabase()

    existing = supa.table("users").select("id").eq("id", g.user_id).execute().data
    if not existing:
        supa.table("users").insert(
            {
                "id": g.user_id,
                "email": g.user_email,
                "full_name": payload.get("full_name"),
                "role": "student",
            }
        ).execute()

    referral_code = payload.get("referral_code")
    if referral_code:
        try:
            attribute_registration(g.user_id, referral_code)
        except Exception:
            pass

    return jsonify({"success": True, "message": "Profile ready", "data": {}})


@auth_bp.get("/me")
@require_auth
def me():
    # NOTE: the frontend's apiFetch() reads this response's fields
    # directly (me.full_name, me.email) rather than under a `data` key,
    # so — unlike the admin/ambassador-management endpoints — this
    # returns the flat user object to match the preserved frontend JS.
    supa = get_supabase()
    rows = supa.table("users").select("*").eq("id", g.user_id).limit(1).execute().data
    row = rows[0] if rows else None
    if not row:
        row = {"id": g.user_id, "email": g.user_email, "full_name": None, "role": "student"}
    return jsonify(row), 200
