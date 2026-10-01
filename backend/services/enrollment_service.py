"""Program enrollment, milestone seeding, and certificate issuance."""
import datetime

from services.supabase_client import get_supabase
from services.coupon_service import get_active_coupon_by_code
from services.ambassador_service import credit_referral_enrollment
from utils.security import random_code
from utils.timeutils import utcnow

# NOTE: certificate issuance is intentionally NOT one of these — it is
# never something a student "completes" as a milestone. It is generated
# automatically (see issue_certificate_if_needed) once every milestone
# below is complete.
DEFAULT_MILESTONES = [
    ("Enrollment confirmed", "Your seat in the program is confirmed."),
    ("Onboarding call completed", "1-to-1 kickoff with your mentor."),
    ("Project milestone 1 submitted", "First checkpoint project delivered."),
    ("Project milestone 2 submitted", "Second checkpoint project delivered."),
    ("Final project submitted", "Capstone project delivered for review."),
]


def _pg_error_message(exc: Exception) -> str:
    """Best-effort extraction of a readable message from a Supabase/PostgREST
    RPC exception, since the exact exception shape varies by client version."""
    msg = getattr(exc, "message", None)
    if not msg:
        details = getattr(exc, "args", None)
        msg = details[0] if details else str(exc)
    return str(msg)


def enroll_in_program(user_id: str, program_id: str, coupon_code: str | None):
    supa = get_supabase()

    try:
        program = supa.table("programs").select("*").eq("id", program_id).single().execute().data
    except Exception:  # noqa: BLE001 — unknown / malformed program id
        program = None
    if not program or program.get("is_active") is False:
        raise ValueError("Program not found.")

    final_price_cents = program["base_price_cents"]
    coupon_id = None
    if coupon_code:
        # Friendly, fast-fail validation up front (nice error messages).
        # The RPC below re-validates the coupon *inside the same
        # transaction as the enrollment insert*, which is what actually
        # closes the race window between "coupon looks valid" and
        # "coupon gets marked used" — two requests racing on the same
        # coupon can no longer both succeed.
        try:
            coupon_row = get_active_coupon_by_code(user_id, coupon_code)
        except (ValueError, PermissionError):
            raise
        except Exception:  # noqa: BLE001 — .single() raises when the code isn't this user's
            raise ValueError("Coupon not found.")
        # price the *selected* program with the coupon's discount (coupon was issued against a default base price)
        final_price_cents = round(program["base_price_cents"] * (100 - coupon_row["discount_percent"]) / 100)
        coupon_id = coupon_row["id"]

    milestones_payload = [{"title": title, "detail": detail} for title, detail in DEFAULT_MILESTONES]

    try:
        result = supa.rpc(
            "create_enrollment_with_coupon",
            {
                "p_user_id": user_id,
                "p_program_id": program_id,
                "p_coupon_id": coupon_id,
                "p_final_price_cents": final_price_cents,
                "p_milestones": milestones_payload,
            },
        ).execute()
    except Exception as e:  # noqa: BLE001 — translate PostgREST/RPC errors into our own ValueError
        raise ValueError(_pg_error_message(e))

    enrollment = result.data
    if not enrollment:
        raise ValueError("Enrollment could not be created.")

    # credit any pending ambassador referral for this user — this is
    # outside the atomic RPC on purpose: referral crediting must never
    # block enrollment (it's a "best effort" side effect, not part of
    # the enrollment+coupon consistency guarantee).
    try:
        credit_referral_enrollment(user_id, enrollment["id"])
    except Exception:
        pass

    return get_dashboard(user_id)


def complete_milestone(user_id: str, enrollment_id: str, milestone_id: str):
    supa = get_supabase()
    enrollment = supa.table("enrollments").select("id, user_id").eq("id", enrollment_id).single().execute().data
    if not enrollment or enrollment["user_id"] != user_id:
        raise PermissionError("Enrollment not found for this user.")

    supa.table("milestones").update(
        {"status": "complete", "completed_at": utcnow().isoformat()}
    ).eq("id", milestone_id).eq("enrollment_id", enrollment_id).execute()

    milestones = supa.table("milestones").select("status").eq("enrollment_id", enrollment_id).execute().data or []
    if milestones and all(m["status"] == "complete" for m in milestones):
        issue_certificate_if_needed(user_id, enrollment_id)

    return get_dashboard(user_id)


def issue_certificate_if_needed(user_id: str, enrollment_id: str):
    supa = get_supabase()
    existing = supa.table("certificates").select("id").eq("enrollment_id", enrollment_id).execute().data
    if existing:
        return existing[0]
    code = f"IH-{datetime.date.today().year}-{random_code(5)}"
    row = (
        supa.table("certificates")
        .insert(
            {
                "enrollment_id": enrollment_id,
                "user_id": user_id,
                "certificate_code": code,
                "issue_date": datetime.date.today().isoformat(),
                "verification_url": f"/api/certificates/verify/{code}",
            }
        )
        .execute()
        .data[0]
    )
    return row


def get_dashboard(user_id: str):
    supa = get_supabase()

    enrollment = (
        supa.table("enrollments")
        .select("*, programs(*)")
        .eq("user_id", user_id)
        .order("enrolled_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    enrollment = enrollment[0] if enrollment else None

    milestones = []
    certificate = None
    if enrollment:
        milestones = (
            supa.table("milestones")
            .select("*")
            .eq("enrollment_id", enrollment["id"])
            .order("sort_order")
            .execute()
            .data
            or []
        )
        cert_rows = supa.table("certificates").select("*").eq("enrollment_id", enrollment["id"]).execute().data
        certificate = cert_rows[0] if cert_rows else None

    from services.coupon_service import list_active_coupons

    active_coupons = list_active_coupons(user_id)  # also flips lapsed coupons to 'expired'
    last_coupon_status = None
    if not active_coupons:
        last = (
            supa.table("coupons").select("status").eq("user_id", user_id)
            .order("issued_at", desc=True).limit(1).execute().data
        )
        last_coupon_status = last[0]["status"] if last else None

    return {
        "enrollment": enrollment,
        "milestones": milestones,
        "certificate": certificate,
        "active_coupons": active_coupons,
        "last_coupon_status": last_coupon_status,
    }


def verify_certificate(code: str):
    supa = get_supabase()
    cert = supa.table("certificates").select("*, users(full_name), enrollments(programs(name, duration_weeks))").eq(
        "certificate_code", code
    ).execute().data
    if not cert:
        raise ValueError("Certificate not found.")
    return cert[0]
