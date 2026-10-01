"""
Campus Ambassador psychometric assessment.

Candidate intake -> attempt (randomised, server-held option order) -> answer /
violation logging -> server-side scoring -> report. The scoring key
(psy_questions.option_scores) is only ever read here, never sent to a browser.

Candidates are not Supabase users, so each attempt gets a random secret token
(only its SHA-256 hash is stored) that must accompany every later call.
Anti-cheat is violation *monitoring*, not prevention: client events are logged
with a server timestamp and combined with server-side timing checks.
"""
import datetime
import hashlib
import hmac
import random
import re
import secrets
import uuid

from config import Config
from services.supabase_client import get_supabase
from utils.timeutils import utcnow, parse_iso
from utils.validators import is_valid_email

DIMENSIONS = [
    ("communication", "Communication"),
    ("leadership", "Leadership"),
    ("student_relationship", "Student Relationship"),
    ("campus_management", "Campus Management"),
    ("responsibility", "Responsibility"),
    ("problem_solving", "Problem Solving"),
    ("teamwork_initiative", "Teamwork & Initiative"),
]
DIM_LABEL = dict(DIMENSIONS)

VIOLATION_KINDS = {
    "tab_switch", "window_blur", "fullscreen_exit", "copy", "cut", "paste",
    "right_click", "blocked_shortcut", "page_reload", "print_screen", "other",
    "phone_detected", "multiple_faces", "head_turned", "no_face", "camera_blocked",
}

STRENGTH_TEXT = {
    "communication": "Explains ideas clearly and handles difficult messages calmly.",
    "leadership": "Guides groups with clear goals, shared ownership and steady follow-through.",
    "student_relationship": "Builds genuine, lasting relationships and networks among students.",
    "campus_management": "Works constructively and professionally with faculty and campus administration.",
    "responsibility": "Reliable: meets commitments and communicates early when plans change.",
    "problem_solving": "Diagnoses problems methodically and resolves conflicts fairly.",
    "teamwork_initiative": "Collaborates well and proactively identifies and acts on opportunities.",
}
DEV_TEXT = {
    "communication": "Practise structuring messages around the audience's needs and responding to criticism calmly.",
    "leadership": "Practise setting clear goals, delegating by strengths and addressing performance issues early.",
    "student_relationship": "Invest in regular follow-ups and in connecting with student leaders across departments.",
    "campus_management": "Learn campus approval processes and build proactive relationships with coordinators and faculty.",
    "responsibility": "Build habits for tracking commitments and flagging delays before deadlines.",
    "problem_solving": "Gather evidence before acting and involve all parties when resolving disagreements.",
    "teamwork_initiative": "Balance individual ideas with the team's goals and propose improvements without waiting to be asked.",
}
INTEGRITY_LABEL = {
    "clear": "Clear - no violations recorded",
    "review": "Minor concerns - manual review suggested",
    "flagged": "Flagged - manual review recommended",
}


# ---------------------------------------------------------------- helpers

def _hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def _get_attempt(attempt_id: str, token: str):
    """Load an attempt and verify the caller holds its secret token."""
    supa = get_supabase()
    try:
        rows = supa.table("psy_attempts").select("*").eq("id", attempt_id).limit(1).execute().data or []
    except Exception:
        rows = []
    if not rows or not hmac.compare_digest(rows[0]["token_hash"], _hash(token)):
        raise PermissionError("Assessment attempt not found.")
    return rows[0]


def _remaining(attempt) -> int:
    return max(0, int((parse_iso(attempt["expires_at"]) - utcnow()).total_seconds()))


def _validate_details(d: dict) -> dict:
    def s(k, n=200):
        return str(d.get(k) or "").strip()[:n]

    out = {
        "full_name": s("full_name", 120), "email": s("email", 200).lower(), "phone": s("phone", 30),
        "college": s("college", 200), "department": s("department", 120), "year": s("year", 40),
        "city": s("city", 100), "social": s("social", 300),
    }
    labels = {"full_name": "Full name", "email": "Email", "phone": "Phone", "college": "College name",
              "department": "Department", "year": "Year of study", "city": "City",
              "social": "LinkedIn/Instagram URL"}
    missing = [labels[k] for k in labels if not out[k]]
    if missing:
        raise ValueError("Please fill in: " + ", ".join(missing))
    if not is_valid_email(out["email"]):
        raise ValueError("Invalid email address.")
    if not re.match(r"^[0-9+\-\s()]{7,20}$", out["phone"]):
        raise ValueError("Invalid phone number.")
    if not re.match(r"^(https?://|www\.|@)?[\w.\-/@%?=&+#~:]{3,}$", out["social"]):
        raise ValueError("Please enter a valid LinkedIn or Instagram URL/handle.")
    try:
        reach = int(str(d.get("reach")).strip())
        if not 0 <= reach <= 1_000_000:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("Approximate number of students you can reach must be a whole number.")
    out["reach"] = reach
    return out


# ---------------------------------------------------------------- attempts

def start_attempt(details: dict):
    supa = get_supabase()
    d = _validate_details(details)

    prev = (
        supa.table("ambassador_applications").select("id, status, assessment_status")
        .eq("email", d["email"]).order("created_at", desc=True).limit(1).execute().data or []
    )
    app_id = None
    if prev:
        p = prev[0]
        if p["status"] == "approved":
            raise ValueError("This email is already approved as a Campus Ambassador. Please use Ambassador Login.")
        if p["status"] == "pending" and p["assessment_status"] == "completed":
            raise ValueError("You have already completed the assessment. Your report is under review - use 'Check application status'.")
        if p["status"] == "pending" and p["assessment_status"] == "in_progress":
            live = supa.table("psy_attempts").select("*").eq("application_id", p["id"]).eq("status", "in_progress").execute().data or []
            for a in live:
                if _remaining(a) > 0:
                    raise ValueError("An attempt is already in progress for this email. Resume it in the browser where you started it.")
                _finalize(a)  # abandoned + timed out: score what exists so the candidate is not stuck
            if live:
                raise ValueError("Your previous attempt timed out and was submitted automatically. Your report is under review.")
        if p["status"] == "pending":  # legacy/half-created pending row: reuse it for the assessment flow
            app_id = p["id"]

    row = {**d, "status": "pending", "flow": "psychometric", "assessment_status": "in_progress"}
    try:
        if app_id:
            supa.table("ambassador_applications").update(row).eq("id", app_id).execute()
        else:
            app_id = supa.table("ambassador_applications").insert(row).execute().data[0]["id"]
    except Exception as e:
        if "23505" in str(e) or "duplicate key" in str(e).lower():
            raise ValueError("An application already exists for this email.")
        raise ValueError(f"Could not register candidate: {e}")

    pool = supa.table("psy_questions").select("id, question_text, options").eq("is_active", True).execute().data or []
    if not pool:
        raise ValueError("The assessment is not configured yet. Please try again later.")
    chosen = random.sample(pool, min(Config.PSY_QUESTION_COUNT, len(pool)))  # random order; whole bank when <= count

    option_order, questions = {}, []
    for q in chosen:
        perm = random.sample(range(len(q["options"])), len(q["options"]))  # displayed position -> original index
        option_order[q["id"]] = perm
        questions.append({"id": q["id"], "question_text": q["question_text"], "options": [q["options"][i] for i in perm]})

    token = secrets.token_urlsafe(24)
    now = utcnow()
    expires = now + datetime.timedelta(seconds=Config.PSY_TIME_LIMIT_SECONDS)
    attempt_id = str(uuid.uuid4())
    supa.table("psy_attempts").insert({
        "id": attempt_id, "application_id": app_id, "token_hash": _hash(token), "status": "in_progress",
        "question_ids": [q["id"] for q in questions], "option_order": option_order,
        "time_limit_seconds": Config.PSY_TIME_LIMIT_SECONDS,
        "started_at": now.isoformat(), "expires_at": expires.isoformat(),
    }).execute()
    supa.table("ambassador_applications").update({"latest_attempt_id": attempt_id}).eq("id", app_id).execute()

    return {"attempt_id": attempt_id, "attempt_token": token, "questions": questions, "answers": {},
            "time_remaining_seconds": Config.PSY_TIME_LIMIT_SECONDS, "violation_count": 0}


def resume_attempt(attempt_id: str, token: str):
    supa = get_supabase()
    a = _get_attempt(attempt_id, token)
    if a["status"] != "in_progress":
        raise ValueError("This attempt has already been submitted.")
    if _remaining(a) <= 0:
        raise ValueError("Time is up for this attempt.")
    log_violation(attempt_id, token, "page_reload", "Assessment reopened after page reload")
    qs = supa.table("psy_questions").select("id, question_text, options").in_("id", a["question_ids"]).execute().data or []
    qmap = {q["id"]: q for q in qs}
    questions = []
    for qid in a["question_ids"]:
        q, perm = qmap[qid], a["option_order"][qid]
        questions.append({"id": qid, "question_text": q["question_text"], "options": [q["options"][i] for i in perm]})
    saved = supa.table("psy_answers").select("question_id, selected_index").eq("attempt_id", attempt_id).execute().data or []
    return {"attempt_id": attempt_id, "questions": questions,
            "answers": {r["question_id"]: r["selected_index"] for r in saved},
            "time_remaining_seconds": _remaining(a), "violation_count": (a.get("violation_count") or 0) + 1}


def _save_answer(attempt, qid, selected_index):
    perm = attempt["option_order"].get(qid)
    if perm is None:
        raise ValueError("Question does not belong to this attempt.")
    if not isinstance(selected_index, int) or isinstance(selected_index, bool) or not 0 <= selected_index < len(perm):
        raise ValueError("Invalid option.")
    get_supabase().table("psy_answers").upsert({
        "attempt_id": attempt["id"], "question_id": qid, "selected_index": selected_index,
        "original_index": perm[selected_index], "answered_at": utcnow().isoformat(),
    }, on_conflict="attempt_id,question_id").execute()


def record_answer(attempt_id, token, question_id, selected_index):
    a = _get_attempt(attempt_id, token)
    if a["status"] != "in_progress":
        raise ValueError("This attempt is no longer active.")
    if _remaining(a) <= 0:
        raise ValueError("Time is up for this attempt.")
    _save_answer(a, question_id, selected_index)
    return {"saved": True}


def log_violation(attempt_id, token, kind, detail=None, client_ts=None):
    supa = get_supabase()
    a = _get_attempt(attempt_id, token)
    if a["status"] != "in_progress":
        return {"violation_count": a.get("violation_count") or 0}
    kind = kind if kind in VIOLATION_KINDS else "other"
    count = a.get("violation_count") or 0
    if count < Config.PSY_MAX_VIOLATION_ROWS:
        supa.table("psy_violations").insert({
            "attempt_id": attempt_id, "kind": kind, "detail": (detail or "")[:200] or None,
            "client_ts": (client_ts or "")[:40] or None, "occurred_at": utcnow().isoformat(),
        }).execute()
    count += 1
    supa.table("psy_attempts").update({"violation_count": count}).eq("id", attempt_id).execute()
    if count > Config.PROCTOR_MAX_VIOLATIONS:  # allowance used up -> auto-submit and generate the report
        _finalize({**a, "violation_count": count}, {}, auto_note=f"Auto-submitted: violation #{count} exceeded the {Config.PROCTOR_MAX_VIOLATIONS} allowed.")
        return {"violation_count": count, "auto_submitted": True}
    return {"violation_count": count, "auto_submitted": False}


def submit_attempt(attempt_id, token, answers):
    a = _get_attempt(attempt_id, token)
    if a["status"] == "in_progress":
        _finalize(a, answers or {})
    return get_candidate_report(attempt_id, token)


# ---------------------------------------------------------------- scoring

def _finalize(attempt, extra_answers=None, auto_note=None):
    """Score an in-progress attempt on the server and create its report."""
    supa = get_supabase()
    now = utcnow()
    late = now > parse_iso(attempt["expires_at"]) + datetime.timedelta(seconds=Config.PSY_SUBMIT_GRACE_SECONDS)

    if not late:  # last-moment answers are only accepted inside the time window
        for qid, idx in (extra_answers or {}).items():
            try:
                _save_answer(attempt, qid, idx)
            except ValueError:
                pass

    qs = supa.table("psy_questions").select("id, dimension, option_scores").in_("id", attempt["question_ids"]).execute().data or []
    saved = supa.table("psy_answers").select("question_id, original_index").eq("attempt_id", attempt["id"]).execute().data or []
    picked = {r["question_id"]: r["original_index"] for r in saved}

    per_dim, total_norm, answered = {}, 0.0, 0
    for q in qs:
        sc = q["option_scores"]
        lo, hi = min(sc), max(sc)
        idx = picked.get(q["id"])
        if idx is not None and 0 <= idx < len(sc):
            answered += 1
            norm = (sc[idx] - lo) / (hi - lo) if hi > lo else 1.0
            supa.table("psy_answers").update({"score": sc[idx]}).eq("attempt_id", attempt["id"]).eq("question_id", q["id"]).execute()
        else:
            norm = 0.0
        total_norm += norm
        per_dim.setdefault(q["dimension"], []).append(norm)

    total = len(qs) or 1
    dim_scores = {k: round(sum(v) / len(v) * 100) for k, v in per_dim.items()}
    overall = round(total_norm / total * 100)
    completion = round(answered / total * 100)

    # ---- integrity (client-reported violations + server-side timing checks)
    v = attempt.get("violation_count") or 0
    notes, level = [], "clear"
    if v >= Config.PSY_VIOLATIONS_REVIEW:
        level = "review"
        notes.append(f"{v} violation(s) recorded during the test.")
    if v >= Config.PSY_VIOLATIONS_FLAGGED:
        level = "flagged"
    elapsed = (now - parse_iso(attempt["started_at"])).total_seconds()
    if answered and elapsed < Config.PSY_MIN_SECONDS_PER_QUESTION * total:
        level = "flagged"
        notes.append("Test completed unusually fast for the number of questions.")
    if late:
        level = "flagged"
        notes.append("Submission arrived after the time limit.")
    if auto_note:
        level = "flagged"
        notes.append(auto_note)
    if not notes:
        notes.append("No violations recorded.")

    ranked = sorted(dim_scores.items(), key=lambda kv: kv[1], reverse=True)
    strong = [(k, s) for k, s in ranked if s >= 70][:3] or [x for x in ranked[:2] if x[1] >= 50]
    weak = [(k, s) for k, s in reversed(ranked) if s < 60][:3] or [x for x in ranked[-1:] if x[1] < 85]
    fmt = lambda items, txt: [{"dimension": k, "label": DIM_LABEL.get(k, k), "score": s, "text": txt[k]} for k, s in items if k in txt]

    band = "outstanding" if overall >= 80 else "strong" if overall >= 65 else "moderate" if overall >= 50 else "developing"
    summary = f"The candidate shows {band} Campus Ambassador potential with an overall score of {overall}%."
    if strong:
        summary += " Strongest areas: " + ", ".join(DIM_LABEL.get(k, k) for k, _ in strong) + "."
    if weak:
        summary += " Main areas to develop: " + ", ".join(DIM_LABEL.get(k, k) for k, _ in weak) + "."
    if level != "clear":
        summary += " Integrity monitoring recorded concerns that the reviewer should consider."
    if completion < 100:
        summary += f" Only {completion}% of the questions were answered."
    summary += " The final selection decision rests with the review team."

    supa.table("psy_reports").insert({
        "attempt_id": attempt["id"], "application_id": attempt["application_id"], "overall_score": overall,
        "dimension_scores": dim_scores, "strengths": fmt(strong, STRENGTH_TEXT), "development_areas": fmt(weak, DEV_TEXT),
        "summary": summary, "integrity_status": level, "integrity_notes": notes, "violation_count": v,
        "completion_pct": completion, "share_token": secrets.token_urlsafe(16),
    }).execute()
    supa.table("psy_attempts").update({
        "status": "expired" if late else "submitted", "submitted_at": now.isoformat(),
    }).eq("id", attempt["id"]).execute()
    supa.table("ambassador_applications").update({"assessment_status": "completed", "latest_attempt_id": attempt["id"]}) \
        .eq("id", attempt["application_id"]).execute()


# ---------------------------------------------------------------- reports

def _build_report(attempt_id: str, private: bool = False):
    supa = get_supabase()
    rep = (supa.table("psy_reports").select("*").eq("attempt_id", attempt_id).limit(1).execute().data or [None])[0]
    if not rep:
        raise ValueError("Report not found.")
    att = supa.table("psy_attempts").select("started_at, submitted_at, status, time_limit_seconds").eq("id", attempt_id).limit(1).execute().data[0]
    app = supa.table("ambassador_applications").select("*").eq("id", rep["application_id"]).limit(1).execute().data[0]

    dims = [{"key": k, "label": lbl, "score": rep["dimension_scores"].get(k, 0)} for k, lbl in DIMENSIONS]
    if rep["completion_pct"] >= 100:
        completion = "Completed - all questions answered"
    else:
        completion = f"Submitted - {rep['completion_pct']}% of questions answered"
    if att["status"] == "expired":
        completion += " (time limit exceeded)"
    out = {
        "attempt_id": attempt_id, "candidate_name": app["full_name"], "overall_score": rep["overall_score"],
        "dimensions": dims, "strengths": rep["strengths"], "development_areas": rep["development_areas"],
        "summary": rep["summary"], "integrity_status": rep["integrity_status"],
        "integrity_label": INTEGRITY_LABEL.get(rep["integrity_status"], rep["integrity_status"]),
        "completion_pct": rep["completion_pct"], "completion_status": completion,
        "assessment_date": att["submitted_at"] or rep["generated_at"], "share_path": f"/r/{rep['share_token']}",
    }
    if private:  # admin only
        viol = supa.table("psy_violations").select("kind, detail, occurred_at").eq("attempt_id", attempt_id).order("occurred_at").execute().data or []
        out.update({
            "application_id": app["id"], "status": app["status"], "rejection_reason": app.get("rejection_reason"),
            "integrity_notes": rep["integrity_notes"], "violation_count": rep["violation_count"], "violations": viol,
            "started_at": att["started_at"],
            "candidate": {k: app.get(k) for k in ("full_name", "email", "phone", "college", "department", "year", "city", "social", "reach")},
        })
    return out


def get_candidate_report(attempt_id, token):
    _get_attempt(attempt_id, token)
    return _build_report(attempt_id)


def get_public_report(share_token: str):
    """Public view: name, scores and narrative only - never email/phone/college/social/violations."""
    supa = get_supabase()
    rows = supa.table("psy_reports").select("attempt_id").eq("share_token", share_token).limit(1).execute().data or []
    if not rows:
        raise ValueError("Report not found.")
    return _build_report(rows[0]["attempt_id"])


# ---------------------------------------------------------------- admin

def list_candidates(status=None, search=None):
    supa = get_supabase()
    q = supa.table("ambassador_applications").select("*").eq("flow", "psychometric").eq("assessment_status", "completed") \
        .order("created_at", desc=True)
    if status and status != "all":
        q = q.eq("status", status)
    if search:
        like = "%" + re.sub(r"[^\w@.\- ]", "", search) + "%"
        q = q.or_(f"full_name.ilike.{like},email.ilike.{like},college.ilike.{like}")
    apps = q.execute().data or []
    reps = {}
    if apps:
        for r in supa.table("psy_reports").select("*").in_("application_id", [a["id"] for a in apps]).execute().data or []:
            reps[r["application_id"]] = r
        approved_ids = [a["id"] for a in apps if a.get("status") == "approved"]
    active_application_ids = set()
    if approved_ids:
        amb_rows = supa.table("ambassadors").select("application_id").in_("application_id", approved_ids).execute().data or []
        active_application_ids = {r["application_id"] for r in amb_rows}

    rows = []
    for a in apps:
        r = reps.get(a["id"])
        if not r:
            continue
        rows.append({
            **{k: a.get(k) for k in ("id", "full_name", "email", "phone", "college", "department", "year", "city", "social", "reach", "status", "rejection_reason", "reviewed_at")},
            "attempt_id": r["attempt_id"], "overall_score": r["overall_score"], "dimension_scores": r["dimension_scores"],
            "strengths": r["strengths"], "development_areas": r["development_areas"], "integrity_status": r["integrity_status"],
            "violation_count": r["violation_count"], "completion_pct": r["completion_pct"], "test_date": r["generated_at"],
            "has_ambassador_account": (a["id"] in active_application_ids) if a.get("status") == "approved" else None,
        })
    allrows = supa.table("ambassador_applications").select("status").eq("flow", "psychometric").eq("assessment_status", "completed").execute().data or []
    counts = {s: len([x for x in allrows if x["status"] == s]) for s in ("pending", "approved", "rejected")}
    counts["total"] = len(allrows)
    return {"candidates": rows, "counts": counts}


def get_candidate_detail(application_id: str):
    supa = get_supabase()
    rows = supa.table("psy_reports").select("attempt_id").eq("application_id", application_id).order("generated_at", desc=True).limit(1).execute().data or []
    if not rows:
        raise ValueError("No completed assessment for this candidate.")
    return _build_report(rows[0]["attempt_id"], private=True)
