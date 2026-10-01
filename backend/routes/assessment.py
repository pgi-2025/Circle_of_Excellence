"""
Scholarship assessment routes — start / answer / flag-activity / submit.

These endpoints match the frontend's openTest()/selectOpt()/finishTest()
calls exactly: /api/test/start, /api/test/answer, /api/test/flag-activity,
/api/test/submit — all under /api/test rather than /api/assessment, to
line up with what the preserved frontend JS already calls.
"""
from flask import Blueprint, request, jsonify, g, current_app

from services import assessment_service
from utils.auth import require_auth
from utils.validators import require_fields
from utils.responses import err

assessment_bp = Blueprint("assessment", __name__, url_prefix="/api/test")


@assessment_bp.post("/register")
@require_auth
def register():
    try:
                return jsonify(assessment_service.register_for_assessment(g.user_id, g.user_email, request.get_json(silent=True) or {}))
    except ValueError as e:
        return err(str(e), 400)
    except Exception as e:
        current_app.logger.exception("assessment register failed")
        return err(f"Registration failed: {type(e).__name__}: {e}", 500)


@assessment_bp.post("/start")
@require_auth
def start():
    try:
        data = assessment_service.start_attempt(g.user_id)
        return jsonify(data)  # frontend reads data.attempt_id / data.questions directly
    except ValueError as e:
        return err(str(e), 400)


@assessment_bp.post("/answer")
@require_auth
def answer():
    payload = request.get_json(silent=True) or {}
    missing = require_fields(payload, ["attempt_id", "question_id"])
    if missing or "selected_index" not in payload:
        return err("attempt_id, question_id, and selected_index are required", 400)
    try:
        result = assessment_service.record_answer(
            g.user_id, payload["attempt_id"], payload["question_id"], payload["selected_index"]
        )
        return jsonify(result)
    except PermissionError as e:
        return err(str(e), 403)
    except ValueError as e:
        return err(str(e), 400)


@assessment_bp.post("/flag-activity")
@require_auth
def flag_activity():
    payload = request.get_json(silent=True) or {}
    missing = require_fields(payload, ["attempt_id", "kind"])
    if missing:
        return err(f"Missing fields: {', '.join(missing)}", 400)
    try:
        result = assessment_service.flag_activity(g.user_id, payload["attempt_id"], payload["kind"], payload.get("detail"))
        return jsonify(result)
    except PermissionError as e:
        return err(str(e), 403)


@assessment_bp.post("/submit")
@require_auth
def submit():
    payload = request.get_json(silent=True) or {}
    missing = require_fields(payload, ["attempt_id"])
    if missing:
        return err("attempt_id is required", 400)
    try:
        result = assessment_service.submit_attempt(g.user_id, payload["attempt_id"], payload.get("answers") or {})
        try:
            from services.ambassador_service import credit_referral_assessment
            credit_referral_assessment(g.user_id)
        except Exception:
            pass
        return jsonify(result)
    except PermissionError as e:
        return err(str(e), 403)
    except ValueError as e:
        return err(str(e), 400)
