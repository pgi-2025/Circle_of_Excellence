"""Razorpay payments. Amount is ALWAYS read from the enrollment row server-side; the client never sends a price."""
import hashlib
import hmac
import json

import httpx
from flask import Blueprint, request, jsonify, g, current_app

from config import Config
from services.supabase_client import get_supabase
from utils.auth import require_auth
from utils.responses import err

payments_bp = Blueprint("payments", __name__)
RZP_API = "https://api.razorpay.com/v1"


def _configured():
    return bool(Config.RAZORPAY_KEY_ID and Config.RAZORPAY_KEY_SECRET)


def _mark_paid(enrollment_id, order_id, payment_id):
    """Idempotent: only a pending/failed enrollment with the matching order id flips to paid."""
    supa = get_supabase()
    supa.table("enrollments").update({"payment_status": "paid", "razorpay_payment_id": payment_id}) \
        .eq("id", enrollment_id).eq("razorpay_order_id", order_id).in_("payment_status", ["pending", "failed"]).execute()


@payments_bp.get("/api/payments/razorpay/config")
def rzp_config():
    return jsonify({"key_id": Config.RAZORPAY_KEY_ID if _configured() else None})


@payments_bp.post("/api/payments/razorpay/order")
@require_auth
def create_order():
    if not _configured():
        return err("Online payment is not configured.", 503)
    enrollment_id = (request.get_json(silent=True) or {}).get("enrollment_id")
    supa = get_supabase()
    rows = supa.table("enrollments").select("id, user_id, payment_status, final_price_cents, programs(name)") \
        .eq("id", enrollment_id or "").eq("user_id", g.user_id).limit(1).execute().data
    if not rows:
        return err("Enrollment not found.", 404)
    e = rows[0]
    if e["payment_status"] in ("paid", "free"):
        return err("This enrollment is already paid.", 400)
    if not e["final_price_cents"] or e["final_price_cents"] < 100:
        return err("Nothing to pay for this enrollment.", 400)
    try:
        r = httpx.post(f"{RZP_API}/orders", auth=(Config.RAZORPAY_KEY_ID, Config.RAZORPAY_KEY_SECRET), timeout=15,
                       json={"amount": e["final_price_cents"], "currency": "INR", "receipt": str(e["id"])[:40],
                             "notes": {"enrollment_id": str(e["id"]), "user_id": str(g.user_id)}})
        r.raise_for_status()
        order = r.json()
    except Exception:
        current_app.logger.exception("Razorpay order creation failed")
        return err("Could not start payment. Please try again.", 502)
    supa.table("enrollments").update({"razorpay_order_id": order["id"]}).eq("id", e["id"]).execute()
    me = supa.table("users").select("full_name, email, phone").eq("id", g.user_id).limit(1).execute().data or [{}]
    return jsonify({"order_id": order["id"], "amount": order["amount"], "currency": order["currency"],
                    "key_id": Config.RAZORPAY_KEY_ID, "program": (e.get("programs") or {}).get("name"),
                    "prefill": {"name": me[0].get("full_name"), "email": me[0].get("email"), "contact": me[0].get("phone")}})


@payments_bp.post("/api/payments/razorpay/verify")
@require_auth
def verify_payment():
    p = request.get_json(silent=True) or {}
    order_id, payment_id, sig = p.get("razorpay_order_id"), p.get("razorpay_payment_id"), p.get("razorpay_signature")
    if not (order_id and payment_id and sig):
        return err("Missing payment details.", 400)
    expected = hmac.new(Config.RAZORPAY_KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return err("Payment verification failed.", 400)
    rows = get_supabase().table("enrollments").select("id").eq("razorpay_order_id", order_id).eq("user_id", g.user_id).limit(1).execute().data
    if not rows:
        return err("Order not found for this user.", 404)
    _mark_paid(rows[0]["id"], order_id, payment_id)
    from services.enrollment_service import get_dashboard
    return jsonify(get_dashboard(g.user_id))


@payments_bp.post("/api/payments/razorpay/webhook")
def webhook():
    """Backup confirmation if the student closes the tab after paying. Signature checked with the webhook secret."""
    raw = request.get_data()
    sig = request.headers.get("X-Razorpay-Signature", "")
    if not Config.RAZORPAY_WEBHOOK_SECRET:
        return "", 503
    expected = hmac.new(Config.RAZORPAY_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return "", 400
    event = json.loads(raw or b"{}")
    if event.get("event") in ("payment.captured", "order.paid"):
        ent = (event.get("payload", {}).get("payment", {}) or {}).get("entity", {})
        order_id, payment_id = ent.get("order_id"), ent.get("id")
        rows = get_supabase().table("enrollments").select("id, final_price_cents").eq("razorpay_order_id", order_id or "").limit(1).execute().data
        if rows and ent.get("amount") == rows[0]["final_price_cents"]:
            _mark_paid(rows[0]["id"], order_id, payment_id)
    return "", 200
