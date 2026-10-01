"""
Campus Ambassador psychometric assessment (candidate-facing, no login).

Every call after /start must carry the attempt's secret token
(JSON body `attempt_token`, or header `X-Attempt-Token` for GETs).
Public report endpoints use an unguessable share token and never return
email / phone / college / social / violation details.
"""
import logging

from flask import Blueprint, request, jsonify, Response

from services import psychometric_service as psy
from services.psychometric_pdf import build_pdf
from utils.responses import err

psy_bp = Blueprint("psychometric", __name__, url_prefix="/api/ambassador-assessment")


def _body():
    return request.get_json(silent=True) or {}


def _token(b=None):
    return request.headers.get("X-Attempt-Token") or (b or {}).get("attempt_token") or ""


def _guard(fn):
    try:
        return fn()
    except PermissionError as e:
        return err(str(e), 403)
    except ValueError as e:
        return err(str(e), 400)
    except Exception as e:  # DB/schema problems: return JSON instead of a bare 500
        logging.getLogger(__name__).exception("psychometric error")
        return err("Assessment database error: " + str(e)[:300] + " - run the psychometric migration in Supabase.", 503)


def _pdf_response(rep, private=False):
    name = "".join(c if c.isalnum() else "_" for c in rep["candidate_name"])[:40] or "candidate"
    return Response(build_pdf(rep, private), mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="Ambassador_Assessment_{name}.pdf"'})


@psy_bp.post("/start")
def start():
    return _guard(lambda: jsonify(psy.start_attempt(_body())))


@psy_bp.post("/resume")
def resume():
    b = _body()
    return _guard(lambda: jsonify(psy.resume_attempt(b.get("attempt_id", ""), _token(b))))


@psy_bp.post("/answer")
def answer():
    b = _body()
    if not b.get("attempt_id") or not b.get("question_id") or "selected_index" not in b:
        return err("attempt_id, question_id and selected_index are required", 400)
    return _guard(lambda: jsonify(psy.record_answer(b["attempt_id"], _token(b), b["question_id"], b["selected_index"])))


@psy_bp.post("/violation")
def violation():
    b = _body()
    if not b.get("attempt_id") or not b.get("kind"):
        return err("attempt_id and kind are required", 400)
    return _guard(lambda: jsonify(psy.log_violation(b["attempt_id"], _token(b), str(b["kind"]), b.get("detail"), b.get("client_ts"))))


@psy_bp.post("/submit")
def submit():
    b = _body()
    if not b.get("attempt_id"):
        return err("attempt_id is required", 400)
    answers = b.get("answers") if isinstance(b.get("answers"), dict) else {}
    return _guard(lambda: jsonify(psy.submit_attempt(b["attempt_id"], _token(b), answers)))


@psy_bp.get("/report/<attempt_id>")
def report(attempt_id):
    return _guard(lambda: jsonify(psy.get_candidate_report(attempt_id, _token())))


@psy_bp.get("/report/<attempt_id>/pdf")
def report_pdf(attempt_id):
    return _guard(lambda: _pdf_response(psy.get_candidate_report(attempt_id, _token())))


@psy_bp.get("/public/<share_token>")
def public_report(share_token):
    try:
        return jsonify(psy.get_public_report(share_token))
    except ValueError as e:
        return err(str(e), 404)


@psy_bp.get("/public/<share_token>/pdf")
def public_report_pdf(share_token):
    try:
        return _pdf_response(psy.get_public_report(share_token))
    except ValueError as e:
        return err(str(e), 404)