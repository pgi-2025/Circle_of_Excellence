"""Coupon issuance, lookup, and redemption."""
import datetime
from config import Config
from services.supabase_client import get_supabase
from utils.security import random_code
from utils.timeutils import utcnow, parse_iso


def _now():
    return utcnow()


def issue_coupon_for_attempt(user_id: str, attempt_id: str, tier: dict, base_price_cents: int = 999900):
    supa = get_supabase()
    discount_percent = tier["discount_percent"]
    final_price_cents = round(base_price_cents * (100 - discount_percent) / 100)

    issued_at = _now()
    expires_at = issued_at + datetime.timedelta(hours=Config.COUPON_EXPIRY_HOURS)

    code = f"{tier['prefix']}-{random_code(6)}"

    row = (
        supa.table("coupons")
        .insert(
            {
                "code": code,
                "user_id": user_id,
                "attempt_id": attempt_id,
                "discount_percent": discount_percent,
                "base_price_cents": base_price_cents,
                "final_price_cents": final_price_cents,
                "status": "active",
                "issued_at": issued_at.isoformat(),
                "expires_at": expires_at.isoformat(),
            }
        )
        .execute()
        .data[0]
    )
    return {
        "code": row["code"],
        "discount_percent": row["discount_percent"],
        "base_price_cents": row["base_price_cents"],
        "final_price_cents": row["final_price_cents"],
        "expires_at": row["expires_at"],
    }


def get_active_coupon_by_code(user_id: str, code: str):
    supa = get_supabase()
    row = supa.table("coupons").select("*").eq("user_id", user_id).eq("code", code).single().execute().data
    if not row:
        raise ValueError("Coupon not found.")
    if row["user_id"] != user_id:
        raise PermissionError("This coupon does not belong to you.")
    if row["status"] != "active":
        raise ValueError(f"This coupon is already {row['status']}.")

    expires_at = parse_iso(row["expires_at"])
    if _now() > expires_at:
        supa.table("coupons").update({"status": "expired"}).eq("id", row["id"]).execute()
        raise ValueError("This coupon has expired.")
    return row


def mark_coupon_used(coupon_id: str, enrollment_id: str):
    supa = get_supabase()
    supa.table("coupons").update(
        {"status": "used", "used_at": _now().isoformat(), "used_for_enrollment_id": enrollment_id}
    ).eq("id", coupon_id).execute()


def list_active_coupons(user_id: str):
    supa = get_supabase()
    rows = (
        supa.table("coupons")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "active")
        .order("issued_at", desc=True)
        .execute()
        .data
        or []
    )
    live = []
    for r in rows:
        expires_at = parse_iso(r["expires_at"])
        if _now() <= expires_at:
            live.append(r)
        else:
            supa.table("coupons").update({"status": "expired"}).eq("id", r["id"]).execute()
    return live


def list_coupon_history(user_id: str):
    """Every coupon ever issued to this user, newest first (dashboard history). Read-only."""
    supa = get_supabase()
    rows = (
        supa.table("coupons")
        .select("code, discount_percent, status, issued_at, expires_at, used_at")
        .eq("user_id", user_id)
        .order("issued_at", desc=True)
        .execute()
        .data
        or []
    )
    for r in rows:
        if r["status"] == "active" and _now() > parse_iso(r["expires_at"]):
            r["status"] = "expired"  # display only; the existing flow flips it in the DB
    return rows
