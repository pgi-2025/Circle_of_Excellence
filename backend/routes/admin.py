"""
Admin routes — students, ambassadors, applications, programs, questions,
assessments, enrollments, coupons, milestones, certificates, referrals,
XP, campaigns, events, rewards, and basic analytics.

Every route here requires the caller's public.users.role to be 'admin'
or 'college_coordinator' (see utils.auth.require_admin).
"""
from flask import Blueprint, request, jsonify, g, current_app

from services.supabase_client import get_supabase
from services import ambassador_service, enrollment_service
from utils.timeutils import utcnow
from utils.auth import require_admin
from utils.validators import require_fields

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _envelope(data, message=""):
    return jsonify({"success": True, "message": message, "data": data})


def err(message, status=400):
    return jsonify({"success": False, "message": message, "data": {}}), status


def _log(action, target_type=None, target_id=None, details=None):
    """Audit log. Admin identity always comes from the authenticated session (g.user_id)."""
    try:
        get_supabase().table("admin_action_logs").insert(
            {"admin_user_id": g.user_id, "action": action, "target_type": target_type,
             "target_id": str(target_id) if target_id else None, "details": details or {}}
        ).execute()
    except Exception:
        current_app.logger.exception("admin audit log failed")


def _pick(payload, allowed):
    return {k: v for k, v in payload.items() if k in allowed}


def _exists(table, row_id):
    return bool(get_supabase().table(table).select("id").eq("id", row_id).limit(1).execute().data)


def _progress(ms):
    return round(100 * len([m for m in ms if m["status"] == "complete"]) / len(ms)) if ms else 0


# ---------------- Self / role check ----------------
# Lightweight endpoint for the frontend to confirm "is the current Supabase
# session an admin?" without pulling a full data list just to check access.
# require_admin still does the actual enforcement — this only reports what
# it already decided.
@admin_bp.get("/me")
@require_admin
def whoami():
    return jsonify({"success": True, "is_admin": True, "role": g.user_role})


# ---------------- Students ----------------

@admin_bp.get("/students")
@require_admin
def list_students():
    supa = get_supabase()
    rows = supa.table("users").select("*").eq("role", "student").order("created_at", desc=True).execute().data or []
    return _envelope(rows)


# ---------------- Programs ----------------

@admin_bp.get("/programs")
@require_admin
def list_all_programs():
    supa = get_supabase()
    rows = supa.table("programs").select("*").order("created_at", desc=True).execute().data or []
    enr = supa.table("enrollments").select("program_id, payment_status, final_price_cents").execute().data or []
    for r in rows:
        mine = [e for e in enr if e["program_id"] == r["id"]]
        r["enrolled_count"] = len(mine)
        r["revenue_cents"] = sum(e["final_price_cents"] or 0 for e in mine if e["payment_status"] == "paid")
    return _envelope(rows)


@admin_bp.post("/programs")
@require_admin
def create_program():
    payload = request.get_json(silent=True) or {}
    missing = require_fields(payload, ["name", "slug"])
    if missing:
        return jsonify({"success": False, "message": f"Missing fields: {', '.join(missing)}", "data": {}}), 400
    supa = get_supabase()
    row = supa.table("programs").insert(_pick(payload, {"name","slug","description","skills","mentor_title","duration_weeks","mode","base_price_cents","image_url","is_active"})).execute().data[0]
    _log("Created program", "program", row["id"], {"name": row.get("name")})
    return _envelope(row, "Program created")


@admin_bp.patch("/programs/<program_id>")
@require_admin
def update_program(program_id):
    payload = request.get_json(silent=True) or {}
    supa = get_supabase()
    row = supa.table("programs").update(_pick(payload, {"name","slug","description","skills","mentor_title","duration_weeks","mode","base_price_cents","image_url","is_active"})).eq("id", program_id).execute().data
    _log("Updated program", "program", program_id, _pick(payload, {"is_active", "name"}))
    return _envelope(row[0] if row else {}, "Program updated")


# ---------------- Assessment questions ----------------

@admin_bp.get("/questions")
@require_admin
def list_questions():
    supa = get_supabase()
    rows = supa.table("assessment_questions").select("*").order("created_at", desc=True).execute().data or []
    return _envelope(rows)


@admin_bp.post("/questions")
@require_admin
def create_question():
    payload = request.get_json(silent=True) or {}
    missing = require_fields(payload, ["question_text", "options"])
    if missing or "correct_index" not in payload:
        return jsonify({"success": False, "message": "question_text, options, and correct_index are required", "data": {}}), 400
    supa = get_supabase()
    row = supa.table("assessment_questions").insert(payload).execute().data[0]
    return _envelope(row, "Question created")


@admin_bp.patch("/questions/<question_id>")
@require_admin
def update_question(question_id):
    payload = request.get_json(silent=True) or {}
    supa = get_supabase()
    row = supa.table("assessment_questions").update(payload).eq("id", question_id).execute().data
    return _envelope(row[0] if row else {}, "Question updated")


@admin_bp.delete("/questions/<question_id>")
@require_admin
def deactivate_question(question_id):
    supa = get_supabase()
    supa.table("assessment_questions").update({"is_active": False}).eq("id", question_id).execute()
    return _envelope({}, "Question deactivated")


# ---------------- Assessments (attempts) ----------------

@admin_bp.get("/assessments")
@require_admin
def list_attempts():
    supa = get_supabase()
    rows = supa.table("assessment_attempts").select("*, users(full_name, email)").order("created_at", desc=True).limit(200).execute().data or []
    cps = {c["attempt_id"]: c for c in supa.table("coupons").select("attempt_id, code, discount_percent, expires_at, status").execute().data or [] if c.get("attempt_id")}
    for r in rows:
        r.pop("question_ids", None); r.pop("option_orders", None)
        c = cps.get(r["id"])
        r["coupon_code"] = c["code"] if c else None
        r["coupon_expires_at"] = c["expires_at"] if c else None
        r["scholarship_percent"] = c["discount_percent"] if c else None
    return _envelope(rows)


# ---------------- Enrollments ----------------

def _enrich_enrollments(rows):
    supa = get_supabase()
    ids = [r["id"] for r in rows]
    ms = supa.table("milestones").select("enrollment_id, status").in_("enrollment_id", ids).execute().data if ids else []
    certs = supa.table("certificates").select("enrollment_id, certificate_code").in_("enrollment_id", ids).execute().data if ids else []
    amb_ids = list({r["referred_by_ambassador_id"] for r in rows if r.get("referred_by_ambassador_id")})
    ambs = {a["id"]: a for a in (supa.table("ambassadors").select("id, full_name, ambassador_code").in_("id", amb_ids).execute().data if amb_ids else [])}
    for r in rows:
        mine = [m for m in ms if m["enrollment_id"] == r["id"]]
        r["progress_percent"] = _progress(mine)
        r["milestone_total"] = len(mine)
        c = next((c for c in certs if c["enrollment_id"] == r["id"]), None)
        r["certificate_code"] = c["certificate_code"] if c else None
        r["ambassador"] = ambs.get(r.get("referred_by_ambassador_id"))
        cp = r.get("coupons") or {}
        prog = r.get("programs") or {}
        r["original_price_cents"] = cp.get("base_price_cents") or prog.get("base_price_cents") or r["final_price_cents"]
        r["discount_percent"] = cp.get("discount_percent") or 0
        r["coupon_code"] = cp.get("code")
    return rows


@admin_bp.get("/enrollments")
@require_admin
def list_enrollments():
    supa = get_supabase()
    rows = supa.table("enrollments").select("*, users(full_name, email), programs(name, base_price_cents), coupons(code, discount_percent, base_price_cents)").order("created_at", desc=True).execute().data or []
    return _envelope(_enrich_enrollments(rows))


@admin_bp.get("/enrollments/<enrollment_id>")
@require_admin
def get_enrollment(enrollment_id):
    supa = get_supabase()
    rows = supa.table("enrollments").select("*, users(full_name, email, phone, college), programs(name, base_price_cents), coupons(code, discount_percent, base_price_cents, status, expires_at)").eq("id", enrollment_id).execute().data
    if not rows:
        return err("Enrollment not found", 404)
    row = _enrich_enrollments(rows)[0]
    row["milestones"] = supa.table("milestones").select("*").eq("enrollment_id", enrollment_id).order("sort_order").execute().data or []
    row["certificate"] = (supa.table("certificates").select("*").eq("enrollment_id", enrollment_id).execute().data or [None])[0]
    return _envelope(row)


@admin_bp.patch("/enrollments/<enrollment_id>")
@require_admin
def update_enrollment(enrollment_id):
    payload = request.get_json(silent=True) or {}
    # prices / discounts / coupon ownership are never writable from the client
    updates = {}
    if "payment_status" in payload:
        if payload["payment_status"] not in ("pending", "paid", "free", "failed", "refunded"):
            return err("Invalid payment_status")
        updates["payment_status"] = payload["payment_status"]
    if "status" in payload:
        if payload["status"] not in ("active", "completed", "cancelled"):
            return err("Invalid status")
        updates["status"] = payload["status"]
    if not updates:
        return err("Nothing to update")
    if not _exists("enrollments", enrollment_id):
        return err("Enrollment not found", 404)
    row = get_supabase().table("enrollments").update(updates).eq("id", enrollment_id).execute().data
    _log("Updated payment status" if "payment_status" in updates else "Updated enrollment status", "enrollment", enrollment_id, updates)
    return _envelope(row[0] if row else {}, "Enrollment updated")


@admin_bp.post("/enrollments/<enrollment_id>/certificate")
@require_admin
def issue_certificate(enrollment_id):
    supa = get_supabase()
    enr = (supa.table("enrollments").select("id, user_id").eq("id", enrollment_id).execute().data or [None])[0]
    if not enr:
        return err("Enrollment not found", 404)
    ms = supa.table("milestones").select("status").eq("enrollment_id", enrollment_id).execute().data or []
    if not ms or any(m["status"] != "complete" for m in ms):
        return err("All milestones must be complete before a certificate can be issued")
    cert = enrollment_service.issue_certificate_if_needed(enr["user_id"], enrollment_id)
    _log("Issued certificate", "enrollment", enrollment_id)
    return _envelope(cert, "Certificate issued")


@admin_bp.post("/enrollments/<enrollment_id>/milestones")
@require_admin
def add_milestone(enrollment_id):
    payload = request.get_json(silent=True) or {}
    if not (payload.get("title") or "").strip():
        return err("title is required")
    if not _exists("enrollments", enrollment_id):
        return err("Enrollment not found", 404)
    supa = get_supabase()
    last = supa.table("milestones").select("sort_order").eq("enrollment_id", enrollment_id).order("sort_order", desc=True).limit(1).execute().data
    row = supa.table("milestones").insert({"enrollment_id": enrollment_id, "title": payload["title"].strip(), "detail": payload.get("detail"),
                                           "sort_order": (last[0]["sort_order"] + 1) if last else 0}).execute().data[0]
    _log("Added milestone", "enrollment", enrollment_id, {"title": row["title"]})
    return _envelope(row, "Milestone added")


@admin_bp.patch("/milestones/item/<milestone_id>")
@require_admin
def update_milestone(milestone_id):
    payload = request.get_json(silent=True) or {}
    updates = _pick(payload, {"title", "detail", "sort_order"})
    if "status" in payload:
        if payload["status"] not in ("pending", "in_progress", "complete"):
            return err("Invalid status")
        updates["status"] = payload["status"]
        updates["completed_at"] = utcnow().isoformat() if payload["status"] == "complete" else None
    supa = get_supabase()
    rows = supa.table("milestones").update(updates).eq("id", milestone_id).execute().data if updates else []
    if not rows:
        return err("Milestone not found or nothing to update", 404)
    _log("Updated milestone", "milestone", milestone_id, updates)
    return _envelope(rows[0], "Milestone updated")


# ---------------- Coupons ----------------

@admin_bp.get("/coupons")
@require_admin
def list_all_coupons():
    supa = get_supabase()
    rows = supa.table("coupons").select("*, users(full_name, email)").order("issued_at", desc=True).execute().data or []
    now = utcnow().isoformat()
    for r in rows:  # expiry is computed server-side from expires_at
        r["effective_status"] = "expired" if r["status"] == "active" and r["expires_at"] < now else r["status"]
    return _envelope(rows)


# ---------------- Milestones ----------------

@admin_bp.get("/milestones/<enrollment_id>")
@require_admin
def list_milestones(enrollment_id):
    supa = get_supabase()
    rows = supa.table("milestones").select("*").eq("enrollment_id", enrollment_id).order("sort_order").execute().data or []
    return _envelope(rows)


# ---------------- Certificates ----------------

@admin_bp.get("/certificates")
@require_admin
def list_certificates():
    supa = get_supabase()
    rows = supa.table("certificates").select("*, users(full_name, email), enrollments(programs(name))").order("created_at", desc=True).execute().data or []
    return _envelope(rows)


# ---------------- Ambassador applications ----------------

@admin_bp.get("/ambassador-applications")
@require_admin
def list_applications():
    supa = get_supabase()
    status = request.args.get("status")
    search = request.args.get("search")

    # psychometric candidates have their own section (/psychometric-candidates)
    query = supa.table("ambassador_applications").select("*").neq("flow", "psychometric").order("created_at", desc=True)
    if status and status != "all":
        query = query.eq("status", status)
    if search:
        like = f"%{search}%"
        query = query.or_(f"full_name.ilike.{like},email.ilike.{like},college.ilike.{like}")
    rows = query.execute().data or []

    all_rows = supa.table("ambassador_applications").select("status").neq("flow", "psychometric").execute().data or []
    pending_count = len([r for r in all_rows if r["status"] == "pending"])

    return _envelope({"applications": rows, "pending_count": pending_count})


@admin_bp.get("/ambassador-applications/<application_id>")
@require_admin
def get_application(application_id):
    supa = get_supabase()
    row = supa.table("ambassador_applications").select("*").eq("id", application_id).single().execute().data
    if not row:
        return jsonify({"success": False, "message": "Application not found", "data": {}}), 404
    return _envelope(row)


@admin_bp.post("/ambassador-applications/<application_id>/review")
@require_admin
def review_application(application_id):
    payload = request.get_json(silent=True) or {}
    approve = bool(payload.get("approve"))
    try:
        result = ambassador_service.review_application(
            application_id,
            approve,
            g.user_id,
            payload.get("temp_password"),
            payload.get("rejection_reason"),
        )
    except ValueError as e:
        return jsonify({"success": False, "message": str(e), "data": {}}), 400
    return _envelope(result, "Application reviewed")


# ---------------- Psychometric assessment candidates ----------------
# Approve / reject reuses POST /ambassador-applications/<id>/review (creates the ambassador login on approval).

@admin_bp.get("/psychometric-candidates")
@require_admin
def list_psy_candidates():
    from services import psychometric_service as psy
    return _envelope(psy.list_candidates(request.args.get("status"), request.args.get("search")))


@admin_bp.get("/psychometric-candidates/<application_id>")
@require_admin
def get_psy_candidate(application_id):
    from services import psychometric_service as psy
    try:
        return _envelope(psy.get_candidate_detail(application_id))
    except ValueError as e:
        return jsonify({"success": False, "message": str(e), "data": {}}), 404


@admin_bp.get("/psychometric-candidates/<application_id>/pdf")
@require_admin
def get_psy_candidate_pdf(application_id):
    from flask import Response
    from services import psychometric_service as psy
    from services.psychometric_pdf import build_pdf
    try:
        rep = psy.get_candidate_detail(application_id)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e), "data": {}}), 404
    name = "".join(c if c.isalnum() else "_" for c in rep["candidate_name"])[:40] or "candidate"
    return Response(build_pdf(rep, private=True), mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="Ambassador_Assessment_{name}_admin.pdf"'})


# ---------------- Ambassadors ----------------

@admin_bp.get("/ambassadors")
@require_admin
def list_ambassadors():
    supa = get_supabase()
    rows = supa.table("ambassadors").select("id, ambassador_code, full_name, email, college, xp, is_active, created_at").order("created_at", desc=True).execute().data or []
    refs = supa.table("ambassador_referrals").select("ambassador_id, enrolled").execute().data or []
    for r in rows:
        mine = [x for x in refs if x["ambassador_id"] == r["id"]]
        r["referral_count"] = len(mine)
        r["enrollment_count"] = len([x for x in mine if x["enrolled"]])
    return _envelope(rows)


@admin_bp.patch("/ambassadors/<ambassador_id>")
@require_admin
def update_ambassador(ambassador_id):
    payload = request.get_json(silent=True) or {}
    allowed = {"is_active", "full_name", "college", "department", "year", "city", "social"}
    updates = {k: v for k, v in payload.items() if k in allowed}
    supa = get_supabase()
    row = supa.table("ambassadors").update(updates).eq("id", ambassador_id).execute().data
    _log("Updated ambassador", "ambassador", ambassador_id, _pick(updates, {"is_active"}))
    return _envelope(row[0] if row else {}, "Ambassador updated")


@admin_bp.delete("/ambassadors/<ambassador_id>")
@require_admin
def delete_ambassador(ambassador_id):
    try:
        result = ambassador_service.delete_ambassador(ambassador_id)
    except ValueError as e:
        return err(str(e), 404)
    except Exception:
        current_app.logger.exception("Failed to delete ambassador %s", ambassador_id)
        return err("Unable to delete ambassador", 500)
    _log("Deleted ambassador", "ambassador", ambassador_id)
    return _envelope(result, "Ambassador account removed")


# ---------------- Referrals & XP ----------------

@admin_bp.get("/referrals")
@require_admin
def list_referrals():
    supa = get_supabase()
    rows = supa.table("ambassador_referrals").select("*, ambassadors(full_name, ambassador_code), users(full_name, email), enrollments(enrolled_at, programs(name))").order("created_at", desc=True).execute().data or []
    return _envelope(rows)


@admin_bp.get("/xp-transactions")
@require_admin
def list_xp_transactions():
    supa = get_supabase()
    ambassador_id = request.args.get("ambassador_id")
    query = supa.table("ambassador_xp_transactions").select("*").order("created_at", desc=True)
    if ambassador_id:
        query = query.eq("ambassador_id", ambassador_id)
    rows = query.limit(200).execute().data or []
    return _envelope(rows)


# ---------------- Student profile ----------------

@admin_bp.get("/students/<user_id>/profile")
@require_admin
def student_profile(user_id):
    supa = get_supabase()
    u = (supa.table("users").select("*").eq("id", user_id).execute().data or [None])[0]
    if not u:
        return err("Student not found", 404)
    for k in ("password", "password_hash"):
        u.pop(k, None)
    enrs = supa.table("enrollments").select("*, programs(name), coupons(code, discount_percent)").eq("user_id", user_id).execute().data or []
    attempts = supa.table("assessment_attempts").select("id, status, score_percent, violation_count, integrity_status, submitted_at, created_at").eq("user_id", user_id).order("created_at", desc=True).execute().data or []
    coupons = supa.table("coupons").select("code, discount_percent, status, issued_at, expires_at, used_for_enrollment_id").eq("user_id", user_id).order("issued_at", desc=True).execute().data or []
    certs = supa.table("certificates").select("certificate_code, issue_date, enrollment_id").eq("user_id", user_id).execute().data or []
    refs = supa.table("ambassador_referrals").select("referral_code, registered, assessment_attempted, enrolled, ambassadors(full_name, ambassador_code)").eq("referred_user_id", user_id).execute().data or []
    _enrich_enrollments(enrs)
    return _envelope({"student": u, "enrollments": enrs, "attempts": attempts, "coupons": coupons, "certificates": certs, "referrals": refs})


# ---------------- Ambassador detail ----------------

@admin_bp.get("/ambassadors/<ambassador_id>/detail")
@require_admin
def ambassador_detail(ambassador_id):
    supa = get_supabase()
    amb = (supa.table("ambassadors").select("id, ambassador_code, full_name, email, college, xp, is_active, created_at").eq("id", ambassador_id).execute().data or [None])[0]
    if not amb:
        return err("Ambassador not found", 404)
    t = lambda name, sel: supa.table(name).select(sel).eq("ambassador_id", ambassador_id).execute().data or []
    return _envelope({
        "ambassador": amb,
        "referrals": supa.table("ambassador_referrals").select("*, users(full_name, email)").eq("ambassador_id", ambassador_id).order("created_at", desc=True).execute().data or [],
        "xp": supa.table("ambassador_xp_transactions").select("*").eq("ambassador_id", ambassador_id).order("created_at", desc=True).limit(50).execute().data or [],
        "challenges": supa.table("ambassador_challenge_assignments").select("status, due_date, ambassador_challenges(title)").eq("ambassador_id", ambassador_id).execute().data or [],
        "campaigns": supa.table("ambassador_campaign_participation").select("progress, ambassador_campaigns(title)").eq("ambassador_id", ambassador_id).execute().data or [],
        "events": supa.table("ambassador_event_attendance").select("attended, ambassador_events(name)").eq("ambassador_id", ambassador_id).execute().data or [],
        "rewards": supa.table("ambassador_reward_claims").select("claimed_at, ambassador_rewards(title)").eq("ambassador_id", ambassador_id).execute().data or [],
    })


# ---------------- Challenges ----------------
CHALLENGE_FIELDS = {"title", "description", "target_count", "xp_reward", "metric", "is_active", "due_date"}


@admin_bp.get("/challenges")
@require_admin
def list_challenges():
    supa = get_supabase()
    rows = supa.table("ambassador_challenges").select("*").order("created_at", desc=True).execute().data or []
    asg = supa.table("ambassador_challenge_assignments").select("challenge_id").execute().data or []
    for r in rows:
        r["assigned_count"] = len([a for a in asg if a["challenge_id"] == r["id"]])
    return _envelope(rows)


@admin_bp.post("/challenges")
@require_admin
def create_challenge():
    payload = request.get_json(silent=True) or {}
    if not (payload.get("title") or "").strip():
        return err("title is required")
    if payload.get("metric", "referrals") not in ("referrals", "enrollments", "campaigns"):
        return err("Invalid metric")
    row = get_supabase().table("ambassador_challenges").insert(_pick(payload, CHALLENGE_FIELDS)).execute().data[0]
    _log("Created challenge", "challenge", row["id"], {"title": row["title"]})
    return _envelope(row, "Challenge created")


@admin_bp.patch("/challenges/<challenge_id>")
@require_admin
def update_challenge(challenge_id):
    payload = request.get_json(silent=True) or {}
    if payload.get("metric", "referrals") not in ("referrals", "enrollments", "campaigns"):
        return err("Invalid metric")
    rows = get_supabase().table("ambassador_challenges").update(_pick(payload, CHALLENGE_FIELDS)).eq("id", challenge_id).execute().data
    if not rows:
        return err("Challenge not found", 404)
    _log("Updated challenge", "challenge", challenge_id, _pick(payload, {"is_active", "title"}))
    return _envelope(rows[0], "Challenge updated")


@admin_bp.get("/challenges/<challenge_id>/assignments")
@require_admin
def challenge_assignments(challenge_id):
    rows = get_supabase().table("ambassador_challenge_assignments").select("*, ambassadors(full_name, ambassador_code)").eq("challenge_id", challenge_id).execute().data or []
    return _envelope(rows)


def _target_ambassadors(payload):
    """Validated ambassador ids: explicit list, or all active. Never trusts unknown ids."""
    supa = get_supabase()
    if payload.get("all_active"):
        return [a["id"] for a in supa.table("ambassadors").select("id").eq("is_active", True).execute().data or []]
    ids = [i for i in (payload.get("ambassador_ids") or []) if isinstance(i, str)]
    return [a["id"] for a in supa.table("ambassadors").select("id").in_("id", ids).execute().data or []] if ids else []


@admin_bp.post("/challenges/<challenge_id>/assign")
@require_admin
def assign_challenge(challenge_id):
    payload = request.get_json(silent=True) or {}
    if not _exists("ambassador_challenges", challenge_id):
        return err("Challenge not found", 404)
    ids = _target_ambassadors(payload)
    if not ids:
        return err("No valid ambassadors selected")
    get_supabase().table("ambassador_challenge_assignments").upsert(
        [{"challenge_id": challenge_id, "ambassador_id": i, "assigned_by": g.user_id, "due_date": payload.get("due_date") or None} for i in ids],
        on_conflict="challenge_id,ambassador_id").execute()
    _log("Assigned challenge to ambassador", "challenge", challenge_id, {"count": len(ids)})
    return _envelope({"assigned": len(ids)}, "Challenge assigned")


@admin_bp.post("/challenges/<challenge_id>/unassign")
@require_admin
def unassign_challenge(challenge_id):
    ids = _target_ambassadors(request.get_json(silent=True) or {})
    if not ids:
        return err("No valid ambassadors selected")
    get_supabase().table("ambassador_challenge_assignments").delete().eq("challenge_id", challenge_id).in_("ambassador_id", ids).execute()
    _log("Unassigned challenge", "challenge", challenge_id, {"count": len(ids)})
    return _envelope({"unassigned": len(ids)}, "Challenge unassigned")


# ---------------- Campaigns ----------------
CAMPAIGN_FIELDS = {"title", "description", "starts_at", "ends_at", "target_count", "xp_reward", "is_active"}


@admin_bp.get("/campaigns")
@require_admin
def list_campaigns():
    supa = get_supabase()
    rows = supa.table("ambassador_campaigns").select("*").order("created_at", desc=True).execute().data or []
    part = supa.table("ambassador_campaign_participation").select("campaign_id").execute().data or []
    for r in rows:
        r["participant_count"] = len([p for p in part if p["campaign_id"] == r["id"]])
    return _envelope(rows)


@admin_bp.post("/campaigns")
@require_admin
def create_campaign():
    payload = request.get_json(silent=True) or {}
    missing = require_fields(payload, ["title"])
    if missing:
        return err("title is required")
    row = get_supabase().table("ambassador_campaigns").insert(_pick(payload, CAMPAIGN_FIELDS)).execute().data[0]
    _log("Created campaign", "campaign", row["id"], {"title": row["title"]})
    return _envelope(row, "Campaign created")


@admin_bp.patch("/campaigns/<campaign_id>")
@require_admin
def update_campaign(campaign_id):
    payload = request.get_json(silent=True) or {}
    rows = get_supabase().table("ambassador_campaigns").update(_pick(payload, CAMPAIGN_FIELDS)).eq("id", campaign_id).execute().data
    if not rows:
        return err("Campaign not found", 404)
    _log("Updated campaign", "campaign", campaign_id, _pick(payload, {"is_active", "title"}))
    return _envelope(rows[0], "Campaign updated")


@admin_bp.get("/campaigns/<campaign_id>/participants")
@require_admin
def campaign_participants(campaign_id):
    rows = get_supabase().table("ambassador_campaign_participation").select("*, ambassadors(full_name, ambassador_code)").eq("campaign_id", campaign_id).execute().data or []
    return _envelope(rows)


@admin_bp.post("/campaigns/<campaign_id>/assign")
@require_admin
def assign_campaign(campaign_id):
    if not _exists("ambassador_campaigns", campaign_id):
        return err("Campaign not found", 404)
    ids = _target_ambassadors(request.get_json(silent=True) or {})
    if not ids:
        return err("No valid ambassadors selected")
    # insert only missing rows so existing progress is never reset
    have = {p["ambassador_id"] for p in get_supabase().table("ambassador_campaign_participation").select("ambassador_id").eq("campaign_id", campaign_id).execute().data or []}
    new = [{"campaign_id": campaign_id, "ambassador_id": i} for i in ids if i not in have]
    if new:
        get_supabase().table("ambassador_campaign_participation").insert(new).execute()
    _log("Assigned campaign to ambassador", "campaign", campaign_id, {"count": len(new)})
    return _envelope({"added": len(new)}, "Ambassadors added")


@admin_bp.post("/campaigns/<campaign_id>/remove")
@require_admin
def remove_campaign_participants(campaign_id):
    ids = _target_ambassadors(request.get_json(silent=True) or {})
    if not ids:
        return err("No valid ambassadors selected")
    get_supabase().table("ambassador_campaign_participation").delete().eq("campaign_id", campaign_id).in_("ambassador_id", ids).execute()
    _log("Removed campaign participation", "campaign", campaign_id, {"count": len(ids)})
    return _envelope({}, "Participation removed")


# ---------------- Events ----------------
EVENT_FIELDS = {"name", "college", "event_date", "event_time", "location", "description", "status"}


def _valid_event_status(payload):
    return payload.get("status", "active") in ("active", "cancelled")


@admin_bp.get("/events")
@require_admin
def list_events():
    supa = get_supabase()
    rows = supa.table("ambassador_events").select("*").order("created_at", desc=True).execute().data or []
    asg = supa.table("ambassador_event_assignments").select("event_id").execute().data or []
    att = supa.table("ambassador_event_attendance").select("event_id, attended").execute().data or []
    for r in rows:
        r["assigned_count"] = len([a for a in asg if a["event_id"] == r["id"]])
        r["attended_count"] = len([a for a in att if a["event_id"] == r["id"] and a["attended"]])
    return _envelope(rows)


@admin_bp.post("/events")
@require_admin
def create_event():
    payload = request.get_json(silent=True) or {}
    missing = require_fields(payload, ["name"])
    if missing or not _valid_event_status(payload):
        return err("name is required")
    row = get_supabase().table("ambassador_events").insert(_pick(payload, EVENT_FIELDS)).execute().data[0]
    _log("Created event", "event", row["id"], {"name": row["name"]})
    return _envelope(row, "Event created")


@admin_bp.patch("/events/<event_id>")
@require_admin
def update_event(event_id):
    payload = request.get_json(silent=True) or {}
    if not _valid_event_status(payload):
        return err("Invalid status")
    rows = get_supabase().table("ambassador_events").update(_pick(payload, EVENT_FIELDS)).eq("id", event_id).execute().data
    if not rows:
        return err("Event not found", 404)
    _log("Updated event", "event", event_id, _pick(payload, {"status", "name"}))
    return _envelope(rows[0], "Event updated")


@admin_bp.get("/events/<event_id>/attendees")
@require_admin
def event_attendees(event_id):
    supa = get_supabase()
    asg = supa.table("ambassador_event_assignments").select("ambassador_id, ambassadors(full_name, ambassador_code)").eq("event_id", event_id).execute().data or []
    att = {a["ambassador_id"]: a for a in supa.table("ambassador_event_attendance").select("*, ambassadors(full_name, ambassador_code)").eq("event_id", event_id).execute().data or []}
    out = {a["ambassador_id"]: {"ambassador_id": a["ambassador_id"], "ambassadors": a["ambassadors"], "attended": False} for a in asg}
    for k, a in att.items():
        out[k] = {"ambassador_id": k, "ambassadors": a["ambassadors"], "attended": a["attended"]}
    return _envelope(list(out.values()))


@admin_bp.post("/events/<event_id>/assign")
@require_admin
def assign_event(event_id):
    if not _exists("ambassador_events", event_id):
        return err("Event not found", 404)
    ids = _target_ambassadors(request.get_json(silent=True) or {})
    if not ids:
        return err("No valid ambassadors selected")
    get_supabase().table("ambassador_event_assignments").upsert(
        [{"event_id": event_id, "ambassador_id": i, "assigned_by": g.user_id} for i in ids], on_conflict="event_id,ambassador_id").execute()
    _log("Assigned event to ambassador", "event", event_id, {"count": len(ids)})
    return _envelope({"assigned": len(ids)}, "Ambassadors invited")


@admin_bp.post("/events/<event_id>/attendance")
@require_admin
def admin_mark_attendance(event_id):
    ids = _target_ambassadors({"ambassador_ids": [(request.get_json(silent=True) or {}).get("ambassador_id")]})
    if not ids or not _exists("ambassador_events", event_id):
        return err("Event or ambassador not found", 404)
    supa = get_supabase()
    done = supa.table("ambassador_event_attendance").select("attended").eq("event_id", event_id).eq("ambassador_id", ids[0]).execute().data
    if done and done[0]["attended"]:
        return _envelope({}, "Already marked attended")
    ambassador_service.mark_event_attendance(ids[0], event_id)  # existing logic (awards XP once)
    _log("Marked event attendance", "event", event_id, {"ambassador_id": ids[0]})
    return _envelope({}, "Attendance marked")


# ---------------- Rewards ----------------
REWARD_FIELDS = {"title", "requirement", "min_xp", "min_enrollments", "is_active"}


@admin_bp.get("/rewards")
@require_admin
def list_rewards():
    supa = get_supabase()
    rows = supa.table("ambassador_rewards").select("*").order("created_at", desc=True).execute().data or []
    cl = supa.table("ambassador_reward_claims").select("reward_id").execute().data or []
    for r in rows:
        r["claim_count"] = len([c for c in cl if c["reward_id"] == r["id"]])
    return _envelope(rows)


@admin_bp.post("/rewards")
@require_admin
def create_reward():
    payload = request.get_json(silent=True) or {}
    if require_fields(payload, ["title"]):
        return err("title is required")
    row = get_supabase().table("ambassador_rewards").insert(_pick(payload, REWARD_FIELDS)).execute().data[0]
    _log("Created reward", "reward", row["id"], {"title": row["title"]})
    return _envelope(row, "Reward created")


@admin_bp.patch("/rewards/<reward_id>")
@require_admin
def update_reward(reward_id):
    payload = request.get_json(silent=True) or {}
    rows = get_supabase().table("ambassador_rewards").update(_pick(payload, REWARD_FIELDS)).eq("id", reward_id).execute().data
    if not rows:
        return err("Reward not found", 404)
    _log("Updated reward", "reward", reward_id, _pick(payload, {"is_active", "title"}))
    return _envelope(rows[0], "Reward updated")


@admin_bp.get("/rewards/<reward_id>/claims")
@require_admin
def reward_claims(reward_id):
    supa = get_supabase()
    reward = (supa.table("ambassador_rewards").select("*").eq("id", reward_id).execute().data or [None])[0]
    if not reward:
        return err("Reward not found", 404)
    claims = supa.table("ambassador_reward_claims").select("claimed_at, ambassadors(full_name, ambassador_code)").eq("reward_id", reward_id).execute().data or []
    # eligibility = same rule as ambassador_service.list_rewards
    refs = supa.table("ambassador_referrals").select("ambassador_id, enrolled").execute().data or []
    claimed = {c["ambassador_id"] for c in supa.table("ambassador_reward_claims").select("ambassador_id").eq("reward_id", reward_id).execute().data or []}
    eligible = []
    for a in supa.table("ambassadors").select("id, full_name, ambassador_code, xp").eq("is_active", True).execute().data or []:
        enr = len([x for x in refs if x["ambassador_id"] == a["id"] and x["enrolled"]])
        if a["id"] not in claimed and (a["xp"] or 0) >= (reward["min_xp"] or 0) and enr >= (reward["min_enrollments"] or 0):
            eligible.append({"full_name": a["full_name"], "ambassador_code": a["ambassador_code"]})
    return _envelope({"claims": claims, "eligible": eligible})


# ---------------- Audit log ----------------

@admin_bp.get("/action-logs")
@require_admin
def action_logs():
    supa = get_supabase()
    rows = supa.table("admin_action_logs").select("*").order("created_at", desc=True).limit(100).execute().data or []
    ids = list({r["admin_user_id"] for r in rows if r.get("admin_user_id")})
    names = {u["id"]: u.get("full_name") or u.get("email") for u in (supa.table("users").select("id, full_name, email").in_("id", ids).execute().data if ids else [])}
    for r in rows:
        r["admin_name"] = names.get(r.get("admin_user_id"))
    return _envelope(rows)


# ---------------- Analytics ----------------

@admin_bp.get("/analytics")
@require_admin
def analytics():
    supa = get_supabase()
    cnt = lambda q: q.execute().count or 0
    now = utcnow().isoformat()
    students = cnt(supa.table("users").select("id", count="exact").eq("role", "student"))
    ambassadors = cnt(supa.table("ambassadors").select("id", count="exact"))
    enrollments = cnt(supa.table("enrollments").select("id", count="exact"))
    attempts = cnt(supa.table("assessment_attempts").select("id", count="exact").eq("status", "submitted"))
    coupons_active = cnt(supa.table("coupons").select("id", count="exact").eq("status", "active").gt("expires_at", now))
    certificates = cnt(supa.table("certificates").select("id", count="exact"))
    recent_enr = supa.table("enrollments").select("id, enrolled_at, payment_status, users(full_name), programs(name)").order("created_at", desc=True).limit(5).execute().data or []
    recent_ref = supa.table("ambassador_referrals").select("created_at, registered, enrolled, ambassadors(full_name), users(full_name)").order("created_at", desc=True).limit(5).execute().data or []
    recent_att = supa.table("assessment_attempts").select("submitted_at, score_percent, users(full_name)").eq("status", "submitted").order("submitted_at", desc=True).limit(5).execute().data or []

    return _envelope(
        {
            # existing keys (unchanged)
            "total_students": students,
            "total_ambassadors": ambassadors,
            "total_enrollments": enrollments,
            "total_submitted_assessments": attempts,
            "active_coupons": coupons_active,
            "certificates_issued": certificates,
            # new keys
            "active_ambassadors": cnt(supa.table("ambassadors").select("id", count="exact").eq("is_active", True)),
            "total_programs": cnt(supa.table("programs").select("id", count="exact")),
            "pending_payments": cnt(supa.table("enrollments").select("id", count="exact").eq("payment_status", "pending")),
            "paid_enrollments": cnt(supa.table("enrollments").select("id", count="exact").in_("payment_status", ["paid", "free"])),
            "expired_coupons": cnt(supa.table("coupons").select("id", count="exact").neq("status", "used").lte("expires_at", now)),
            "recent_enrollments": recent_enr,
            "recent_referrals": recent_ref,
            "recent_assessments": recent_att,
        }
    )
