"""
Campus Ambassador routes.

Matches the exact endpoints the preserved frontend's ambApiFetch()
already calls: /api/ambassador/apply, /login, /profile, /referrals,
/campaigns, /events, /rewards, /leaderboard — plus a few extra write
endpoints (attendance, reward claim, campaign participate) that the
frontend's demo-mode `alert()` stubs describe as their real targets.
"""
from flask import Blueprint, request, jsonify, g, current_app, Response

from services import ambassador_service
from utils.auth import require_ambassador_auth
from utils.validators import require_fields, is_valid_email
from utils.responses import err

ambassadors_bp = Blueprint("ambassadors", __name__, url_prefix="/api/ambassador")


@ambassadors_bp.post("/apply")
def apply():
    """Retired: candidates now register through the psychometric assessment (/api/ambassador-assessment/start)."""
    return err("Direct applications are closed. Please complete the Campus Ambassador Assessment.", 410)

@ambassadors_bp.get("/application-status")
def application_status():
    email = request.args.get("email", "").strip()
    if not email or not is_valid_email(email):
        return err("A valid email is required", 400)
    try:
        data = ambassador_service.get_application_status(email)
        return jsonify(data)
    except ValueError as e:
        return err(str(e), 404)


@ambassadors_bp.post("/login")
def login():
    payload = request.get_json(silent=True) or {}
    missing = require_fields(payload, ["email", "password"])
    if missing:
        return err("Email and password are required", 400)
    try:
        result = ambassador_service.login(payload["email"], payload["password"])
        return jsonify(result)
    except ValueError as e:
        return err(str(e), 401)


@ambassadors_bp.get("/profile")
@require_ambassador_auth
def profile():
    data = ambassador_service.get_profile(g.ambassador_id)
    return jsonify(data)


@ambassadors_bp.patch("/profile")
@require_ambassador_auth
def update_profile():
    payload = request.get_json(silent=True) or {}
    try:
        data = ambassador_service.update_profile(g.ambassador_id, payload)
        return jsonify(data)
    except ValueError as e:
        return err(str(e), 400)


@ambassadors_bp.post("/brochure-seen")
@require_ambassador_auth
def brochure_seen():
    try:
        return jsonify(ambassador_service.mark_brochure_seen(g.ambassador_id))
    except Exception:
        current_app.logger.exception("Brochure seen update failed for ambassador_id=%s", g.ambassador_id)
        return err("Unable to save", 500)


@ambassadors_bp.post("/referral-click")
def referral_click():
    """Public — fired when a referral link is opened, before signup."""
    payload = request.get_json(silent=True) or {}
    code = payload.get("referral_code") or payload.get("code")
    click_id = payload.get("click_id")
    if not code:
        return err("referral_code is required", 400)
    ambassador_service.register_referral_click(code, click_id)
    return jsonify({"tracked": True})


@ambassadors_bp.get("/referrals")
@require_ambassador_auth
def referrals():
    try:
        data = ambassador_service.get_referrals_summary(g.ambassador_id)
    except ValueError as e:
        return err(str(e), 404)
    except Exception:
        current_app.logger.exception("Ambassador referrals query failed for ambassador_id=%s", g.ambassador_id)
        return err("Unable to load referrals", 500)
    return jsonify(data)


@ambassadors_bp.get("/campaigns")
@require_ambassador_auth
def campaigns():
    try:
        data = ambassador_service.list_campaigns(g.ambassador_id)
    except Exception:
        current_app.logger.exception("Ambassador campaigns query failed for ambassador_id=%s", g.ambassador_id)
        return err("Unable to load campaigns", 500)
    return jsonify(data)


@ambassadors_bp.post("/campaigns/participate")
@require_ambassador_auth
def campaign_participate():
    payload = request.get_json(silent=True) or {}
    if "campaign_id" not in payload:
        return err("campaign_id is required", 400)
    data = ambassador_service.join_campaign(g.ambassador_id, payload["campaign_id"])
    return jsonify(data)


@ambassadors_bp.get("/events")
@require_ambassador_auth
def events():
    try:
        data = ambassador_service.list_events(g.ambassador_id)
    except Exception:
        current_app.logger.exception("Ambassador events query failed for ambassador_id=%s", g.ambassador_id)
        return err("Unable to load events", 500)
    return jsonify(data)


@ambassadors_bp.post("/events/<event_id>/attendance")
@require_ambassador_auth
def mark_attendance(event_id):
    data = ambassador_service.mark_event_attendance(g.ambassador_id, event_id)
    return jsonify(data)


@ambassadors_bp.get("/challenges")
@require_ambassador_auth
def challenges():
    data = ambassador_service.list_challenges(g.ambassador_id)
    return jsonify(data)


@ambassadors_bp.get("/rewards")
@require_ambassador_auth
def rewards():
    try:
        data = ambassador_service.list_rewards(g.ambassador_id)
    except Exception:
        current_app.logger.exception("Ambassador rewards query failed for ambassador_id=%s", g.ambassador_id)
        return err("Unable to load rewards", 500)
    return jsonify(data)


@ambassadors_bp.post("/rewards/claim")
@require_ambassador_auth
def claim_reward():
    payload = request.get_json(silent=True) or {}
    if "reward_id" not in payload:
        return err("reward_id is required", 400)
    try:
        data = ambassador_service.claim_reward(g.ambassador_id, payload["reward_id"])
        return jsonify(data)
    except ValueError as e:
        return err(str(e), 400)


@ambassadors_bp.get("/leaderboard")
@require_ambassador_auth
def leaderboard():
    college = request.args.get("college")
    try:
        data = {
            "overall": ambassador_service.get_leaderboard("overall"),
            "weekly": ambassador_service.get_leaderboard("weekly"),
            "monthly": ambassador_service.get_leaderboard("monthly"),
            "college": ambassador_service.get_leaderboard("college", college=college),
        }
    except Exception:
        current_app.logger.exception("Ambassador leaderboard query failed")
        return err("Unable to load leaderboard", 500)
    return jsonify(data)


@ambassadors_bp.get("/certificate")
@require_ambassador_auth
def certificate():
    data = ambassador_service.get_certificate(g.ambassador_id)
    return jsonify(data)


@ambassadors_bp.get("/certificate/verify/<code>")
def verify_certificate(code):
    """Public — anyone with the code can verify an ambassador certificate."""
    try:
        data = ambassador_service.verify_certificate(code)
        return jsonify({"valid": True, **data})
    except ValueError as e:
        return err(str(e), 404)


@ambassadors_bp.get("/marketing-kit")
@require_ambassador_auth
def marketing_kit():
    data = ambassador_service.list_marketing_assets()
    return jsonify(data)


@ambassadors_bp.get("/marketing-kit/<asset_id>/download")
@require_ambassador_auth
def marketing_kit_download(asset_id):
    try:
        data = ambassador_service.get_marketing_asset_download(asset_id)
        return jsonify(data)
    except ValueError as e:
        return err(str(e), 404)


@ambassadors_bp.get("/offer-letter")
@require_ambassador_auth
def offer_letter():
    """Offer letter PDF for the signed-in campus ambassador."""
    from services.offer_letter_service import get_ambassador_offer_letter
    try:
        pdf, filename = get_ambassador_offer_letter(g.ambassador_id)
    except ValueError as e:
        return err(str(e), 404)
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})
