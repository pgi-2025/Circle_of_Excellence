"""Coupon lookup routes (list is used by 'My Coupons' in the dashboard)."""
from flask import Blueprint, jsonify, g

from services.coupon_service import list_active_coupons
from utils.auth import require_auth

coupons_bp = Blueprint("coupons", __name__, url_prefix="/api/coupons")


@coupons_bp.get("")
@require_auth
def list_coupons():
    rows = list_active_coupons(g.user_id)
    return jsonify({"success": True, "message": "", "data": rows})
