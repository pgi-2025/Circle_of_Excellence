"""
Scholarship assessment business logic: starting attempts, randomizing
questions, recording answers/flags server-side, and grading.

The client NEVER receives correct_index. Grading and timing are both
validated server-side (an expired attempt cannot be submitted for
credit; it is auto-graded as 'expired' instead).

Question selection
    Each attempt draws a balanced mix from the bank: half 'technical' and
    half 'non_technical' (Config.ASSESSMENT_TECHNICAL_SHARE), spread
    round-robin across topics, preferring questions the student has not
    seen in a previous attempt. Option order is shuffled per attempt and
    the order is stored on the attempt (option_orders) so answers can be
    mapped back to the real option when grading.

Anti-cheat (server side; the client is never trusted on its own)
    * Every flag adds a weighted amount to attempt.risk_score
      (Config.ASSESSMENT_FLAG_WEIGHTS). Reaching ASSESSMENT_RISK_DISQUALIFY
      ends the attempt immediately (status 'disqualified').
    * At submit, timing is analysed from server-side answer timestamps:
      implausibly fast completion, bursts of answers recorded closer
      together than a human could read them, and answers that were only
      delivered in bulk at submit time all add risk.
    * integrity_status: 'clean' (< REVIEW), 'review' (>= REVIEW: no automatic
      coupon), 'disqualified' (>= DISQUALIFY). The pre-existing rule
      (violation_count >= ASSESSMENT_MAX_VIOLATIONS_FOR_COUPON => no coupon)
      still applies on top.
"""
import collections
import re
import datetime
import random
import uuid

from config import Config, get_scholarship_tier
from services.supabase_client import get_supabase
from services.coupon_service import issue_coupon_for_attempt
from utils.timeutils import utcnow, parse_iso

_FLAG_KINDS = {"tab_switch", "fullscreen_exit", "copy_paste", "dev_tools", "window_blur", "other",
               "phone_detected", "multiple_faces", "head_turned", "no_face", "camera_blocked"}
_SECTION_LABEL = {"technical": "Technical", "non_technical": "Non-technical"}

_MSG_DISQUALIFIED = (
    "This attempt was ended because repeated or serious integrity violations were recorded, "
    "so it isn't eligible for a scholarship coupon."
)
_MSG_REVIEW = (
    "Our integrity checks flagged activity on this attempt, so it isn't eligible for an "
    "automatic scholarship coupon. Our team may review it."
)


def _now():
    return utcnow()


# ---------------------------------------------------------------- selection

def _round_robin_pick(pool: list, n: int) -> list:
    """Pick up to n questions, cycling through topics so no topic dominates."""
    if n <= 0 or not pool:
        return []
    by_topic = {}
    for q in pool:
        by_topic.setdefault(q.get("topic") or "general", []).append(q)
    for items in by_topic.values():
        random.shuffle(items)
    topics = list(by_topic)
    random.shuffle(topics)
    picked = []
    while len(picked) < n and any(by_topic[t] for t in topics):
        for t in topics:
            if by_topic[t] and len(picked) < n:
                picked.append(by_topic[t].pop())
    return picked


def _select_questions(pool: list, count: int, seen_ids: set) -> list:
    unseen = [q for q in pool if q["id"] not in seen_ids]
    candidates = unseen if len(unseen) >= count else pool  # fresh questions on retakes when the bank allows

    tech = [q for q in candidates if q.get("category") == "technical"]
    non_tech = [q for q in candidates if q.get("category") == "non_technical"]
    chosen = []
    if tech and non_tech:
        n_tech = max(0, min(count, int(round(count * Config.ASSESSMENT_TECHNICAL_SHARE))))
        chosen = _round_robin_pick(tech, n_tech) + _round_robin_pick(non_tech, count - n_tech)

    # top up (uncategorised questions, or one category running short), then from the full pool
    for source in (candidates, pool):
        if len(chosen) >= count:
            break
        taken = {q["id"] for q in chosen}
        chosen += _round_robin_pick([q for q in source if q["id"] not in taken], count - len(chosen))

    random.shuffle(chosen)
    return chosen[:count]


REGISTRATION_REQUIRED_MSG = "Please complete the Assessment Registration (with a valid ambassador referral code) before starting the test."


def register_for_assessment(user_id: str, user_email: str | None, payload: dict):
    from services.ambassador_service import register_for_assessment as _link
    name = (payload.get("full_name") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    phone = re.sub(r"[\s\-()]", "", str(payload.get("phone") or ""))
    college = (payload.get("college") or "").strip()
    code = (payload.get("referral_code") or "").strip()
    if not (name and email and phone and college and code):
        raise ValueError("Full name, email, phone, college and ambassador referral code are all required.")
    if user_email and email != user_email.lower():
        raise ValueError("Email must match the account you are logged in with.")
    if not re.fullmatch(r"\+?\d{10,15}", phone):
        raise ValueError("Enter a valid phone number.")
    supa = get_supabase()
    # the public.users row may be missing if bootstrap-profile never ran; the referral FK needs it first
    supa.table("users").upsert(
        {"id": user_id, "email": email, "full_name": name, "phone": phone, "college": college}, on_conflict="id"
    ).execute()
    _link(user_id, code, payload.get("click_id"))  # raises the 'Invalid ambassador referral code' error
    return {"registered": True}


def start_attempt(user_id: str):
    from services.ambassador_service import is_registered_for_assessment
    if not is_registered_for_assessment(user_id):
        raise ValueError(REGISTRATION_REQUIRED_MSG)
    supa = get_supabase()

    if Config.ASSESSMENT_ONE_ACTIVE_ATTEMPT:
        existing = (
            supa.table("assessment_attempts")
            .select("id, expires_at")
            .eq("user_id", user_id)
            .eq("status", "in_progress")
            .execute()
        )
        for row in existing.data or []:
            expires_at = parse_iso(row["expires_at"])
            if expires_at > _now():
                raise ValueError("You already have an active attempt in progress.")
            else:
                supa.table("assessment_attempts").update({"status": "expired"}).eq("id", row["id"]).execute()

    all_q = (
        supa.table("assessment_questions")
        .select("id, question_text, options, category, topic")
        .eq("is_active", True)
        .execute()
    )
    pool = all_q.data or []
    if len(pool) < 1:
        raise ValueError("No active assessment questions are configured yet.")

    previous = supa.table("assessment_attempts").select("question_ids").eq("user_id", user_id).execute().data or []
    seen_ids = {qid for row in previous for qid in (row.get("question_ids") or [])}

    count = min(Config.ASSESSMENT_QUESTION_COUNT, len(pool))
    chosen = _select_questions(pool, count, seen_ids)
    question_ids = [q["id"] for q in chosen]

    # Randomize option order per question, per attempt, without ever exposing which
    # option is correct. order[i] = index (in the stored options) of the option shown at position i.
    option_orders = {}
    sanitized_questions = []
    for q in chosen:
        options = list(q["options"])
        order = list(range(len(options)))
        random.shuffle(order)
        option_orders[q["id"]] = order
        item = {"id": q["id"], "question_text": q["question_text"], "options": [options[i] for i in order]}
        section = _SECTION_LABEL.get(q.get("category"))
        if section:
            item["section"] = section
        sanitized_questions.append(item)

    started_at = _now()
    expires_at = started_at + datetime.timedelta(seconds=Config.ASSESSMENT_TIME_LIMIT_SECONDS)

    attempt = (
        supa.table("assessment_attempts")
        .insert(
            {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "status": "in_progress",
                "question_ids": question_ids,
                "option_orders": option_orders,
                "time_limit_seconds": Config.ASSESSMENT_TIME_LIMIT_SECONDS,
                "started_at": started_at.isoformat(),
                "expires_at": expires_at.isoformat(),
            }
        )
        .execute()
    )
    attempt_row = attempt.data[0]

    return {
        "attempt_id": attempt_row["id"],
        "questions": sanitized_questions,
        "time_limit_seconds": Config.ASSESSMENT_TIME_LIMIT_SECONDS,
        "expires_at": expires_at.isoformat(),
    }


# ------------------------------------------------------------------ answers

def _valid_index(value, order) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    upper = len(order) if order else 4
    return 0 <= value < upper


def record_answer(user_id: str, attempt_id: str, question_id: str, selected_index: int):
    supa = get_supabase()
    attempt = supa.table("assessment_attempts").select("*").eq("id", attempt_id).single().execute().data
    if not attempt or attempt["user_id"] != user_id:
        raise PermissionError("Attempt not found for this user.")
    if attempt["status"] != "in_progress":
        raise ValueError("This attempt is no longer active.")
    if question_id not in attempt["question_ids"]:
        raise ValueError("Question does not belong to this attempt.")
    if not _valid_index(selected_index, (attempt.get("option_orders") or {}).get(question_id)):
        raise ValueError("selected_index is not a valid option for this question.")

    expires_at = parse_iso(attempt["expires_at"])
    if _now() > expires_at:
        raise ValueError("Time is up for this attempt.")

    supa.table("assessment_answers").upsert(
        {
            "attempt_id": attempt_id,
            "question_id": question_id,
            "selected_index": selected_index,
            "answered_at": _now().isoformat(),
        },
        on_conflict="attempt_id,question_id",
    ).execute()
    return {"saved": True}


# ---------------------------------------------------------------- anti-cheat

def _flag_summary(supa, attempt_id: str) -> list:
    rows = supa.table("assessment_flags").select("kind").eq("attempt_id", attempt_id).execute().data or []
    counts = collections.Counter(r["kind"] for r in rows)
    return [f"{n} x {kind}" for kind, n in counts.most_common()]


def flag_activity(user_id: str, attempt_id: str, kind: str, detail: str | None = None):
    supa = get_supabase()
    attempt = supa.table("assessment_attempts").select("*").eq("id", attempt_id).single().execute().data
    if not attempt or attempt["user_id"] != user_id:
        raise PermissionError("Attempt not found for this user.")

    count = attempt.get("violation_count") or 0
    risk = attempt.get("risk_score") or 0
    if attempt["status"] != "in_progress":
        # finished attempts don't accumulate flags; just report where things stand
        return {"violation_count": count, "risk_score": risk, "disqualified": attempt["status"] == "disqualified"}

    kind = kind if kind in _FLAG_KINDS else "other"
    weight = Config.ASSESSMENT_FLAG_WEIGHTS.get(kind, 1)

    if count < Config.ASSESSMENT_MAX_FLAG_ROWS:
        supa.table("assessment_flags").insert(
            {"attempt_id": attempt_id, "kind": kind, "detail": (str(detail)[:200] if detail else None)}
        ).execute()

    new_count = count + 1
    new_risk = risk + weight
    updates = {"violation_count": new_count, "risk_score": new_risk}
    disqualified = new_risk >= Config.ASSESSMENT_RISK_DISQUALIFY or new_count > Config.PROCTOR_MAX_VIOLATIONS
    if disqualified:
        updates.update(
            {
                "status": "disqualified",
                "submitted_at": _now().isoformat(),
                "eligible_for_coupon": False,
                "integrity_status": "disqualified",
            }
        )
    supa.table("assessment_attempts").update(updates).eq("id", attempt_id).execute()

    if disqualified:
        _finalize_disqualified(supa, attempt_id, {**attempt, **updates})

    return {"violation_count": new_count, "risk_score": new_risk, "disqualified": disqualified}


def _timing_analysis(saved_rows: list, started_at, total: int, elapsed_seconds: float, bulk_merged: int, answered: int):
    """Returns (extra_risk_points, notes) from server-side timing of the autosaved answers."""
    points, notes = 0, []

    if total and answered >= max(3, total // 2) and elapsed_seconds < Config.ASSESSMENT_MIN_SECONDS_PER_QUESTION * total:
        points += 4
        notes.append(f"Completed in {int(elapsed_seconds)}s for {total} questions (implausibly fast)")

    stamps = sorted(parse_iso(r["answered_at"]) for r in saved_rows if r.get("answered_at"))
    if len(stamps) >= 6:
        gaps = [(stamps[0] - started_at).total_seconds()] + [
            (b - a).total_seconds() for a, b in zip(stamps, stamps[1:])
        ]
        rapid = sum(1 for g in gaps if g < Config.ASSESSMENT_FAST_ANSWER_SECONDS)
        if rapid / len(gaps) >= Config.ASSESSMENT_FAST_ANSWER_RATIO:
            points += 3
            notes.append(f"{rapid} of {len(gaps)} answers were recorded less than {Config.ASSESSMENT_FAST_ANSWER_SECONDS}s apart")

    if answered >= 5 and bulk_merged / answered >= 0.5:
        points += 2
        notes.append(f"{bulk_merged} of {answered} answers reached the server only at submit time")

    return points, notes


def _grade(supa, attempt_id: str, attempt: dict, answer_map: dict):
    """Marks each answer correct/incorrect and returns (score_percent, total).
    answer_map values are positions in the order the options were DISPLAYED; they are
    mapped back through the stored option order before comparing with correct_index."""
    questions = (
        supa.table("assessment_questions").select("id, correct_index").in_("id", attempt["question_ids"]).execute().data or []
    )
    orders = attempt.get("option_orders") or {}
    total = len(questions)
    correct = 0
    for q in questions:
        selected = answer_map.get(q["id"])
        order = orders.get(q["id"])
        if selected is not None and order and 0 <= selected < len(order):
            selected = order[selected]
        is_correct = selected is not None and selected == q["correct_index"]
        if is_correct:
            correct += 1
        if q["id"] in answer_map:
            supa.table("assessment_answers").update({"is_correct": is_correct}).eq("attempt_id", attempt_id).eq(
                "question_id", q["id"]
            ).execute()
    return (round((correct / total) * 100) if total else 0), total


def _finalize_disqualified(supa, attempt_id: str, attempt: dict) -> dict:
    """Grade (for the record) and store the integrity trail for an attempt ended for violations."""
    if attempt.get("score_percent") is None:
        saved = supa.table("assessment_answers").select("question_id, selected_index").eq("attempt_id", attempt_id).execute().data or []
        score_percent, _ = _grade(supa, attempt_id, attempt, {a["question_id"]: a["selected_index"] for a in saved})
        supa.table("assessment_attempts").update(
            {
                "score_percent": score_percent,
                "eligible_for_coupon": False,
                "integrity_status": "disqualified",
                "integrity_notes": _flag_summary(supa, attempt_id),
            }
        ).eq("id", attempt_id).execute()
    else:
        score_percent = attempt["score_percent"]
    return {"score_percent": score_percent, "coupon": None, "message": _MSG_DISQUALIFIED, "integrity_status": "disqualified"}


# -------------------------------------------------------------------- submit

def submit_attempt(user_id: str, attempt_id: str, answers: dict):
    """
    answers: {question_id: selected_index} — accepted as a fallback/merge
    with whatever was already autosaved via record_answer, so a final
    client-side payload is not required to have been sent incrementally.
    """
    supa = get_supabase()
    attempt = supa.table("assessment_attempts").select("*").eq("id", attempt_id).single().execute().data
    if not attempt or attempt["user_id"] != user_id:
        raise PermissionError("Attempt not found for this user.")
    if attempt["status"] == "disqualified":
        return _finalize_disqualified(supa, attempt_id, attempt)
    if attempt["status"] not in ("in_progress",):
        raise ValueError("This attempt has already been finalized.")

    expires_at = parse_iso(attempt["expires_at"])
    now = _now()
    is_expired = now > expires_at
    orders = attempt.get("option_orders") or {}

    # what the server saw during the test (timing evidence) - read BEFORE merging the final payload
    saved_before = (
        supa.table("assessment_answers").select("question_id, selected_index, answered_at").eq("attempt_id", attempt_id).execute().data or []
    )
    saved_map = {a["question_id"]: a["selected_index"] for a in saved_before}

    # merge last-moment answers; unchanged ones are skipped so their original timestamps survive
    bulk_merged = 0
    for qid, idx in (answers or {}).items():
        if qid not in attempt["question_ids"] or not _valid_index(idx, orders.get(qid)):
            continue
        if saved_map.get(qid) == idx:
            continue
        supa.table("assessment_answers").upsert(
            {"attempt_id": attempt_id, "question_id": qid, "selected_index": idx, "answered_at": now.isoformat()},
            on_conflict="attempt_id,question_id",
        ).execute()
        if qid not in saved_map:
            bulk_merged += 1
        saved_map[qid] = idx

    score_percent, total = _grade(supa, attempt_id, attempt, saved_map)

    # ---- integrity evaluation
    started_at = parse_iso(attempt["started_at"])
    elapsed = (min(now, expires_at) - started_at).total_seconds()
    timing_points, timing_notes = _timing_analysis(saved_before, started_at, total, elapsed, bulk_merged, len(saved_map))
    violation_count = attempt.get("violation_count") or 0
    risk = (attempt.get("risk_score") or 0) + timing_points
    if risk >= Config.ASSESSMENT_RISK_DISQUALIFY:
        integrity = "disqualified"
    elif risk >= Config.ASSESSMENT_RISK_REVIEW:
        integrity = "review"
    else:
        integrity = "clean"
    notes = _flag_summary(supa, attempt_id) + timing_notes

    if is_expired:
        final_status = "expired"
    elif integrity == "disqualified":
        final_status = "disqualified"
    else:
        final_status = "submitted"
    eligible_for_coupon = (
        (not is_expired)
        and (violation_count < Config.ASSESSMENT_MAX_VIOLATIONS_FOR_COUPON)
        and integrity == "clean"
    )

    supa.table("assessment_attempts").update(
        {
            "status": final_status,
            "submitted_at": now.isoformat(),
            "score_percent": score_percent,
            "eligible_for_coupon": eligible_for_coupon,
            "risk_score": risk,
            "integrity_status": integrity,
            "integrity_notes": notes,
        }
    ).eq("id", attempt_id).execute()

    result = {"score_percent": score_percent, "coupon": None, "message": None, "integrity_status": integrity}

    if is_expired:
        result["message"] = "Time ran out before you submitted — this attempt was auto-graded."
        return result

    if integrity == "disqualified":
        result["message"] = _MSG_DISQUALIFIED
        return result

    if violation_count >= Config.ASSESSMENT_MAX_VIOLATIONS_FOR_COUPON:
        result["message"] = "Too many anti-cheat violations were recorded, so this attempt isn't eligible for a scholarship coupon."
        return result

    if integrity == "review":
        result["message"] = _MSG_REVIEW
        return result

    tier = get_scholarship_tier(score_percent)
    if tier is None:
        result["message"] = "This score doesn't meet the minimum 50% needed for a scholarship coupon."
        return result

    coupon = issue_coupon_for_attempt(user_id=user_id, attempt_id=attempt_id, tier=tier)
    result["coupon"] = coupon
    return result
