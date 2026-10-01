"""
Campus Ambassador business logic: applications, login, referral
attribution/crediting, XP, leaderboard, campaigns, events, challenges,
rewards, and the ambassador certificate.
"""
import datetime
import re
import uuid

from config import Config, get_ambassador_level
from services.supabase_client import get_supabase
from utils.security import hash_password, verify_password, random_ambassador_code, random_code
from utils.auth import issue_ambassador_token
from services.email_service import send_ambassador_credentials_email
from services.email_service import send_ambassador_credentials_email
from utils.timeutils import utcnow


# ---------------- Applications ----------------

def submit_application(payload: dict):
    supa = get_supabase()
    try:
        row = (
            supa.table("ambassador_applications")
            .insert(
                {
                    "full_name": payload["full_name"],
                    "email": payload["email"],
                    "phone": payload.get("phone"),
                    "college": payload["college"],
                    "department": payload.get("department"),
                    "year": payload.get("year"),
                    "city": payload.get("city"),
                    "social": payload.get("social"),
                    "reach": payload.get("reach") or None,
                    "why": payload.get("why"),
                    "referral_code_used": payload.get("referral_code"),
                    "status": "pending",
                }
            )
            .execute()
            .data[0]
        )
        return row
    except Exception as e:
        msg = str(e)
        if "23505" in msg or "duplicate key" in msg.lower() or "uq_amb_app_email_active" in msg:
            raise ValueError(
                "You already have a pending or approved ambassador application with this email."
            )
        raise ValueError(f"Could not submit application: {msg}")


def review_application(
    application_id: str,
    approve: bool,
    reviewer_id: str,
    temp_password: str | None = None,
    rejection_reason: str | None = None,
):
    """Admin approves/rejects an application. Approval creates the ambassador account."""
    supa = get_supabase()
    app_row = supa.table("ambassador_applications").select("*").eq("id", application_id).single().execute().data
    if not app_row:
        raise ValueError("Application not found.")
    # Assessment-flow candidates can only be reviewed after completing the test (never auto-approved).
    if app_row.get("flow") == "psychometric" and app_row.get("assessment_status") != "completed":
        raise ValueError("Candidate has not completed the assessment yet.")
    if approve and temp_password is not None and len(temp_password) < 8:
        raise ValueError("Temporary password must be at least 8 characters.")

    status = "approved" if approve else "rejected"
    update_payload = {
        "status": status,
        "reviewed_by": reviewer_id,
        "reviewed_at": utcnow().isoformat(),
        "rejection_reason": (rejection_reason or None) if not approve else None,
    }
    supa.table("ambassador_applications").update(update_payload).eq("id", application_id).execute()

    if not approve:
        # rejected candidates must not keep (or get) dashboard access
        supa.table("ambassadors").update({"is_active": False}).eq("application_id", application_id).execute()
        return {"status": status, "rejection_reason": update_payload["rejection_reason"]}

    existing = supa.table("ambassadors").select("id").eq("email", app_row["email"]).execute().data
    if existing:
        supa.table("ambassadors").update({"is_active": True}).eq("id", existing[0]["id"]).execute()
        return {"status": status, "ambassador_id": existing[0]["id"]}

    code = random_ambassador_code()
    while supa.table("ambassadors").select("id").eq("ambassador_code", code).execute().data:
        code = random_ambassador_code()

    password = temp_password or random_code(10)
    ambassador = (
        supa.table("ambassadors")
        .insert(
            {
                "application_id": application_id,
                "ambassador_code": code,
                "full_name": app_row["full_name"],
                "email": app_row["email"],
                "phone": app_row.get("phone"),
                "password_hash": hash_password(password),
                "college": app_row["college"],
                "department": app_row.get("department"),
                "year": app_row.get("year"),
                "city": app_row.get("city"),
                "social": app_row.get("social"),
                "xp": 0,
            }
        )
        .execute()
        .data[0]
    )
    email_sent = send_ambassador_credentials_email(app_row["email"], app_row["full_name"], code, password)
    return {
        "status": status,
        "ambassador_id": ambassador["id"],
        "ambassador_code": code,
        "temp_password": password,
        "email_sent": email_sent,
    }

def get_application_status(email: str):
    """Public lookup — most recent application for this email."""
    supa = get_supabase()
    rows = (
        supa.table("ambassador_applications")
        .select("status, rejection_reason, created_at, reviewed_at, assessment_status")
        .eq("email", email)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise ValueError("No ambassador application found for that email.")
    return rows[0]

# ---------------- Auth ----------------

def login(email: str, password: str):
    supa = get_supabase()
    row = supa.table("ambassadors").select("*").eq("email", email).execute().data
    if not row:
        raise ValueError("Invalid email or password.")
    amb = row[0]
    if not amb["is_active"]:
        raise ValueError("This ambassador account is inactive.")
    if not verify_password(password, amb["password_hash"]):
        raise ValueError("Invalid email or password.")

    token = issue_ambassador_token(amb["id"], amb["email"])
    return {"token": token, "name": amb["full_name"], "ambassador_id": amb["id"]}


def delete_ambassador(ambassador_id: str):
    """Permanently removes an ambassador account. Cascades to their
    referrals, rewards, campaign/event participation, and XP history
    (schema.sql declares these as ON DELETE CASCADE). The original
    ambassador_applications record is left in place as a historical
    record of the application itself."""
    supa = get_supabase()
    existing = supa.table("ambassadors").select("id, full_name, email").eq("id", ambassador_id).execute().data or []
    if not existing:
        raise ValueError("Ambassador not found.")
    supa.table("ambassadors").delete().eq("id", ambassador_id).execute()
    return {"deleted_id": ambassador_id, "email": existing[0]["email"]}


def get_profile(ambassador_id: str):
    supa = get_supabase()
    amb = supa.table("ambassadors").select("*").eq("id", ambassador_id).single().execute().data
    if not amb:
        raise ValueError("Ambassador not found.")
    return {
        "name": amb["full_name"],
        "ambassadorId": amb["ambassador_code"],
        "college": amb["college"],
        "department": amb["department"],
        "year": amb["year"],
        "city": amb["city"],
        "email": amb["email"],
        "phone": amb.get("phone"),
        "social": amb["social"],
        # True when the column is absent (migration not run) so the popup can never repeat
        "brochureSeen": bool(amb.get("ambassador_brochure_seen", True)),
    }


def mark_brochure_seen(ambassador_id: str):
    """Records that the one-time brochure welcome popup has been shown."""
    supa = get_supabase()
    supa.table("ambassadors").update({"ambassador_brochure_seen": True}).eq("id", ambassador_id).execute()
    return {"brochureSeen": True}


EDITABLE_AMBASSADOR_FIELDS = {"full_name", "phone", "college", "department", "year", "city", "social"}
_PHONE_RE = re.compile(r"^[0-9+\-\s()]{7,20}$")


def update_profile(ambassador_id: str, payload: dict):
    updates = {k: v for k, v in payload.items() if k in EDITABLE_AMBASSADOR_FIELDS}
    if not updates:
        raise ValueError("No valid fields to update.")
    if "phone" in updates:
        phone = (updates["phone"] or "").strip()
        if phone and not _PHONE_RE.match(phone):
            raise ValueError("Please enter a valid phone number (7-20 digits; +, spaces, - and () allowed).")
        updates["phone"] = phone or None  # empty string clears the number
    supa = get_supabase()
    row = supa.table("ambassadors").update(updates).eq("id", ambassador_id).execute().data
    if not row:
        raise ValueError("Ambassador not found.")
    return get_profile(ambassador_id)


# ---------------- Referral attribution & XP ----------------

def award_xp(ambassador_id: str, amount: int, reason: str, reference_id: str | None = None):
    supa = get_supabase()
    supa.table("ambassador_xp_transactions").insert(
        {"ambassador_id": ambassador_id, "amount": amount, "reason": reason, "reference_id": reference_id}
    ).execute()
    amb = supa.table("ambassadors").select("xp").eq("id", ambassador_id).single().execute().data
    new_xp = (amb["xp"] or 0) + amount
    supa.table("ambassadors").update({"xp": new_xp}).eq("id", ambassador_id).execute()
    return new_xp


def register_referral_click(ambassador_code: str, click_id: str):
    """Called (optionally) when the referral link is first opened, before signup."""
    supa = get_supabase()
    amb = supa.table("ambassadors").select("id").eq("ambassador_code", ambassador_code).execute().data
    if not amb:
        return None
    supa.table("ambassador_referrals").insert(
        {"ambassador_id": amb[0]["id"], "referral_code": ambassador_code, "click_id": click_id}
    ).execute()
    return amb[0]["id"]


def attribute_registration(user_id: str, ambassador_code: str | None):
    """Called from the student signup flow (bootstrap-profile) if a ?ref= code was captured."""
    if not ambassador_code:
        return None
    supa = get_supabase()
    amb = supa.table("ambassadors").select("id").eq("ambassador_code", ambassador_code).execute().data
    if not amb:
        return None
    ambassador_id = amb[0]["id"]

    existing = (
        supa.table("ambassador_referrals")
        .select("id")
        .eq("ambassador_id", ambassador_id)
        .eq("referred_user_id", user_id)
        .execute()
        .data
    )
    if existing:
        return ambassador_id

    supa.table("ambassador_referrals").insert(
        {
            "ambassador_id": ambassador_id,
            "referred_user_id": user_id,
            "referral_code": ambassador_code,
            "registered": True,
        }
    ).execute()
    award_xp(ambassador_id, Config.XP_PER_REGISTRATION, "referral_registration", user_id)
    return ambassador_id


def register_for_assessment(user_id: str, ambassador_code: str, click_id: str | None = None):
    """Link the student to the ambassador for the scholarship test (reuses the referral table).
    Reuses the student's existing row / the ?ref= click row instead of creating duplicates."""
    supa = get_supabase()
    code = (ambassador_code or "").strip()
    amb = supa.table("ambassadors").select("id, ambassador_code").eq("ambassador_code", code).execute().data
    if not amb and code.upper() != code:
        amb = supa.table("ambassadors").select("id, ambassador_code").eq("ambassador_code", code.upper()).execute().data
    if not amb:
        raise ValueError("Invalid ambassador referral code. Please enter a valid code.")
    ambassador_id = amb[0]["id"]
    now = utcnow().isoformat()

    mine = supa.table("ambassador_referrals").select("*").eq("referred_user_id", user_id).execute().data or []
    if any(r["ambassador_id"] != ambassador_id for r in mine):
        raise ValueError("Your account is already linked to a different ambassador referral.")
    if mine:
        ref = mine[0]
        upd = {"assessment_registered_at": now}
        if not ref["registered"]:
            upd["registered"] = True
        supa.table("ambassador_referrals").update(upd).eq("id", ref["id"]).execute()
        if not ref["registered"]:
            award_xp(ambassador_id, Config.XP_PER_REGISTRATION, "referral_registration", user_id)
        return ambassador_id

    # claim the pre-signup ?ref= click row (keeps click attribution) if there is one
    q = supa.table("ambassador_referrals").select("id").eq("ambassador_id", ambassador_id).is_("referred_user_id", "null")
    if click_id:
        q = q.eq("click_id", click_id)
    click_row = (q.order("created_at").limit(1).execute().data or []) if click_id else []
    if click_row:
        supa.table("ambassador_referrals").update(
            {"referred_user_id": user_id, "registered": True, "assessment_registered_at": now}
        ).eq("id", click_row[0]["id"]).execute()
        award_xp(ambassador_id, Config.XP_PER_REGISTRATION, "referral_registration", user_id)
        return ambassador_id

    attribute_registration(user_id, amb[0]["ambassador_code"])
    supa.table("ambassador_referrals").update({"assessment_registered_at": now}).eq(
        "ambassador_id", ambassador_id).eq("referred_user_id", user_id).execute()
    return ambassador_id


def is_registered_for_assessment(user_id: str) -> bool:
    rows = (
        get_supabase().table("ambassador_referrals").select("id")
        .eq("referred_user_id", user_id).not_.is_("assessment_registered_at", "null").limit(1).execute().data
    )
    return bool(rows)


def credit_referral_assessment(user_id: str):
    supa = get_supabase()
    refs = supa.table("ambassador_referrals").select("*").eq("referred_user_id", user_id).execute().data or []
    for ref in refs:
        if not ref["assessment_attempted"]:
            supa.table("ambassador_referrals").update({"assessment_attempted": True}).eq("id", ref["id"]).execute()
            award_xp(ref["ambassador_id"], Config.XP_PER_ASSESSMENT_ATTEMPT, "referral_assessment", user_id)


def credit_referral_enrollment(user_id: str, enrollment_id: str):
    """
    Credit the referring ambassador ONLY on a genuine, successful
    enrollment — this is the anti-fraud gate: XP for enrollment is never
    granted on registration or assessment alone, and each ambassador can
    only be credited once per unique student (enforced by the DB's
    unique index on (ambassador_id, referred_user_id)).
    """
    supa = get_supabase()
    refs = supa.table("ambassador_referrals").select("*").eq("referred_user_id", user_id).execute().data or []
    for ref in refs:
        if not ref["enrolled"]:
            supa.table("ambassador_referrals").update(
                {"enrolled": True, "applied": True, "enrollment_id": enrollment_id}
            ).eq("id", ref["id"]).execute()
            award_xp(ref["ambassador_id"], Config.XP_PER_SUCCESSFUL_ENROLLMENT, "referral_enrollment", enrollment_id)


def get_referrals_summary(ambassador_id: str):
    supa = get_supabase()
    amb_rows = supa.table("ambassadors").select("*").eq("id", ambassador_id).execute().data or []
    if not amb_rows:
        raise ValueError("Ambassador record not found")
    amb = amb_rows[0]
    refs = supa.table("ambassador_referrals").select("*").eq("ambassador_id", ambassador_id).execute().data or []

    clicks = len([r for r in refs if r.get("click_id")])
    registrations = len([r for r in refs if r["registered"]])
    assessments = len([r for r in refs if r["assessment_attempted"]])
    applications = len([r for r in refs if r["applied"]])
    enrollments = len([r for r in refs if r["enrolled"]])

    return {
        "referralCode": amb["ambassador_code"],
        "referralLink": f"/?ref={amb['ambassador_code']}",
        "xp": amb["xp"],
        "stats": {
            "totalReferrals": registrations,
            "successfulEnrollments": enrollments,
            "leaderboardRank": get_rank_for_ambassador(ambassador_id),
            "rewardsEarned": len(
                supa.table("ambassador_reward_claims").select("id").eq("ambassador_id", ambassador_id).execute().data or []
            ),
        },
        "funnel": {
            "clicks": clicks,
            "registrations": registrations,
            "assessments": assessments,
            "applications": applications,
            "enrollments": enrollments,
        },
    }


# ---------------- Leaderboard ----------------

def get_rank_for_ambassador(ambassador_id: str):
    board = get_leaderboard("overall")
    for row in board:
        if row["id"] == ambassador_id:
            return row["rank"]
    return None


def get_leaderboard(scope: str = "overall", college: str | None = None):
    supa = get_supabase()
    since = None
    if scope == "weekly":
        since = (utcnow() - datetime.timedelta(days=7)).isoformat()
    elif scope == "monthly":
        since = (utcnow() - datetime.timedelta(days=30)).isoformat()

    ambassadors = supa.table("ambassadors").select("id, full_name, college, xp").eq("is_active", True).execute().data or []
    refs = supa.table("ambassador_referrals").select("ambassador_id, registered, enrolled, created_at").execute().data or []

    if scope == "college" and college:
        ambassadors = [a for a in ambassadors if a["college"] == college]

    rows = []
    for amb in ambassadors:
        amb_refs = [r for r in refs if r["ambassador_id"] == amb["id"]]
        if since:
            amb_refs = [r for r in amb_refs if r["created_at"] >= since]
        rows.append(
            {
                "id": amb["id"],
                "name": amb["full_name"],
                "college": amb["college"],
                "referrals": len([r for r in amb_refs if r["registered"]]),
                "enrollments": len([r for r in amb_refs if r["enrolled"]]),
                "xp": amb["xp"],
            }
        )
    rows.sort(key=lambda r: r["xp"], reverse=True)
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows


# ---------------- Campaigns / Events / Challenges / Rewards ----------------

def list_campaigns(ambassador_id: str):
    supa = get_supabase()
    campaigns = supa.table("ambassador_campaigns").select("*").eq("is_active", True).execute().data or []
    participation = (
        supa.table("ambassador_campaign_participation")
        .select("*")
        .eq("ambassador_id", ambassador_id)
        .execute()
        .data
        or []
    )
    prog_by_campaign = {p["campaign_id"]: p["progress"] for p in participation}
    return [
        {
            "id": c["id"],
            "title": c["title"],
            "desc": c["description"],
            "start": c["starts_at"],
            "end": c["ends_at"],
            "target": c["target_count"],
            "progress": prog_by_campaign.get(c["id"], 0),
            "xp": c["xp_reward"],
        }
        for c in campaigns
    ]


def join_campaign(ambassador_id: str, campaign_id: str):
    supa = get_supabase()
    supa.table("ambassador_campaign_participation").upsert(
        {"campaign_id": campaign_id, "ambassador_id": ambassador_id}, on_conflict="campaign_id,ambassador_id"
    ).execute()
    return {"joined": True}


def list_events(ambassador_id: str):
    supa = get_supabase()
    events = supa.table("ambassador_events").select("*").execute().data or []
    events = [e for e in events if (e.get("status") or "active") != "cancelled"]
    targeted = {}
    for a in supa.table("ambassador_event_assignments").select("event_id, ambassador_id").execute().data or []:
        targeted.setdefault(a["event_id"], set()).add(a["ambassador_id"])
    # events with no assignments stay visible to everyone (legacy behaviour); targeted events only to invitees
    events = [e for e in events if e["id"] not in targeted or ambassador_id in targeted[e["id"]]]
    attendance = (
        supa.table("ambassador_event_attendance")
        .select("*")
        .eq("ambassador_id", ambassador_id)
        .execute()
        .data
        or []
    )
    attended_ids = {a["event_id"] for a in attendance if a["attended"]}
    return [
        {
            "id": e["id"],
            "name": e["name"],
            "college": e["college"],
            "date": e["event_date"],
            "time": e["event_time"],
            "location": e["location"],
            "desc": e["description"],
            "attendance": "attended" if e["id"] in attended_ids else "pending",
        }
        for e in events
    ]


def mark_event_attendance(ambassador_id: str, event_id: str):
    supa = get_supabase()
    supa.table("ambassador_event_attendance").upsert(
        {"event_id": event_id, "ambassador_id": ambassador_id, "attended": True, "marked_at": utcnow().isoformat()},
        on_conflict="event_id,ambassador_id",
    ).execute()
    award_xp(ambassador_id, Config.XP_PER_EVENT_ATTENDANCE, "event_attendance", event_id)
    return {"attended": True}


def list_challenges(ambassador_id: str):
    supa = get_supabase()
    assigns = supa.table("ambassador_challenge_assignments").select("challenge_id, status, due_date").eq("ambassador_id", ambassador_id).execute().data or []
    if not assigns:
        return []
    by_id = {a["challenge_id"]: a for a in assigns}
    challenges = supa.table("ambassador_challenges").select("*").eq("is_active", True).in_("id", list(by_id)).execute().data or []
    refs = supa.table("ambassador_referrals").select("registered, enrolled").eq("ambassador_id", ambassador_id).execute().data or []
    registered_count = len([r for r in refs if r["registered"]])
    enrolled_count = len([r for r in refs if r["enrolled"]])

    out = []
    for c in challenges:
        a = by_id[c["id"]]
        progress = enrolled_count if c["metric"] == "enrollments" else registered_count
        out.append(
            {"id": c["id"], "title": c["title"], "desc": c.get("description"), "progress": min(progress, c["target_count"]),
             "target": c["target_count"], "xp": c["xp_reward"], "due_date": a.get("due_date") or c.get("due_date"),
             "status": a.get("status") or "assigned"}
        )
    return out


def list_rewards(ambassador_id: str):
    supa = get_supabase()
    amb_rows = supa.table("ambassadors").select("xp").eq("id", ambassador_id).execute().data or []
    xp = amb_rows[0]["xp"] if amb_rows else 0
    refs = supa.table("ambassador_referrals").select("enrolled").eq("ambassador_id", ambassador_id).execute().data or []
    enrollments = len([r for r in refs if r["enrolled"]])

    rewards = supa.table("ambassador_rewards").select("*").eq("is_active", True).execute().data or []
    claimed = supa.table("ambassador_reward_claims").select("reward_id").eq("ambassador_id", ambassador_id).execute().data or []
    claimed_ids = {c["reward_id"] for c in claimed}

    out = []
    for r in rewards:
        if r["id"] in claimed_ids:
            status = "claimed"
        elif xp >= (r["min_xp"] or 0) and enrollments >= (r["min_enrollments"] or 0):
            status = "eligible"
        else:
            status = "locked"
        out.append({"id": r["id"], "title": r["title"], "requirement": r["requirement"], "status": status})
    return out


def claim_reward(ambassador_id: str, reward_id: str):
    rewards = list_rewards(ambassador_id)
    match = next((r for r in rewards if r["id"] == reward_id), None)
    if not match:
        raise ValueError("Reward not found.")
    if match["status"] != "eligible":
        raise ValueError("You are not yet eligible for this reward.")
    supa = get_supabase()
    supa.table("ambassador_reward_claims").insert({"reward_id": reward_id, "ambassador_id": ambassador_id}).execute()
    return {"claimed": True}


def get_certificate(ambassador_id: str):
    supa = get_supabase()
    existing = supa.table("ambassador_certificates").select("*").eq("ambassador_id", ambassador_id).execute().data
    if existing:
        cert = existing[0]
    else:
                # Unique per certificate: 8 random chars, re-rolled if the code already exists
        for _ in range(10):
            code = f"AMB-CERT-{datetime.date.today().year}-{random_code(8)}"
            if not supa.table("ambassador_certificates").select("id").eq("certificate_code", code).execute().data:
                break
        cert = (
            supa.table("ambassador_certificates")
            .insert({"ambassador_id": ambassador_id, "certificate_code": code})
            .execute()
            .data[0]
        )
    return {"id": cert["certificate_code"], "title": cert["title"], "issued": cert["issue_date"]}


def verify_certificate(code: str):
    """Public verification — no auth required."""
    supa = get_supabase()
    rows = (
        supa.table("ambassador_certificates")
        .select("*, ambassadors(full_name, college)")
        .eq("certificate_code", code)
        .execute()
        .data
        or []
    )
    if not rows:
        raise ValueError("Ambassador certificate not found.")
    cert = rows[0]
    amb = cert.get("ambassadors") or {}
    return {
        "certificate_code": cert["certificate_code"],
        "title": cert["title"],
        "issue_date": cert["issue_date"],
        "ambassador_name": amb.get("full_name"),
        "college": amb.get("college"),
        "verification_url": f"/api/ambassador/certificate/verify/{cert['certificate_code']}",
    }


# ---------------- Marketing kit ----------------

def list_marketing_assets():
    supa = get_supabase()
    rows = supa.table("ambassador_marketing_assets").select("*").order("created_at", desc=True).execute().data or []
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "asset_type": r["asset_type"],
            "caption_template": r["caption_template"],
            "download_url": r["file_url"],
        }
        for r in rows
    ]


def get_marketing_asset_download(asset_id: str):
    """Return a usable download URL for a marketing asset.

    The `marketing-assets` bucket is public-read, so if file_url is a
    storage path (not already a full URL) we resolve it to the bucket's
    public URL rather than a signed one.
    """
    supa = get_supabase()
    row = supa.table("ambassador_marketing_assets").select("*").eq("id", asset_id).single().execute().data
    if not row:
        raise ValueError("Marketing asset not found.")
    file_url = row.get("file_url")
    if not file_url:
        raise ValueError("This asset has no file attached yet.")
    if file_url.startswith("http://") or file_url.startswith("https://"):
        return {"title": row["title"], "download_url": file_url}
    public_url = supa.storage.from_(Config.ASSET_STORAGE_BUCKET).get_public_url(file_url)
    return {"title": row["title"], "download_url": public_url}
