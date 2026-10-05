"""Enrollment + dashboard routes — match the frontend's applyCouponAndEnroll() and openDashboard()."""
from flask import Blueprint, request, jsonify, g, Response

from services import enrollment_service
from utils.auth import require_auth
from utils.validators import require_fields
from utils.responses import err

enrollment_bp = Blueprint("enrollment", __name__)


@enrollment_bp.post("/api/enroll")
@require_auth
def enroll():
    payload = request.get_json(silent=True) or {}
    missing = require_fields(payload, ["program_id"])
    if missing:
        return err("program_id is required", 400)
    try:
        data = enrollment_service.enroll_in_program(g.user_id, payload["program_id"], payload.get("coupon_code"))
        return jsonify(data)
    except (ValueError, PermissionError) as e:
        return err(str(e), 400)


@enrollment_bp.get("/api/dashboard")
@require_auth
def dashboard():
    # frontend destructures dash.enrollment / dash.active_coupons / dash.certificate / dash.milestones directly
    data = enrollment_service.get_dashboard(g.user_id)
    return jsonify(data)


@enrollment_bp.post("/api/enrollment/<enrollment_id>/milestones/<milestone_id>/complete")
@require_auth
def complete_milestone(enrollment_id, milestone_id):
    try:
        data = enrollment_service.complete_milestone(g.user_id, enrollment_id, milestone_id)
        return jsonify(data)
    except PermissionError as e:
        return err(str(e), 403)


@enrollment_bp.get("/api/offer-letter")
@require_auth
def offer_letter():
    """Offer letter PDF for the signed-in intern (enrolled + paid/free only)."""
    from services.offer_letter_service import get_intern_offer_letter
    try:
        pdf, filename = get_intern_offer_letter(g.user_id)
    except PermissionError as e:
        return err(str(e), 403)
    except ValueError as e:
        return err(str(e), 404)
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})
