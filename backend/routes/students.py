"""Student profile, education details, and resume upload."""
import os
import uuid

from flask import Blueprint, request, jsonify, g

from config import Config
from services.supabase_client import get_supabase
from utils.auth import require_auth
from utils.validators import is_allowed_file, safe_filename, validate_student_profile
from utils.timeutils import utcnow
from utils.responses import ok, err

students_bp = Blueprint("students", __name__, url_prefix="/api/students")

# Fields the student is allowed to edit via PATCH /profile.
EDITABLE_PROFILE_FIELDS = {
    "full_name",
    "phone",
    "educational_qualification",
    "sslc_percentage",
    "hsc_percentage",
    "college",
    "cgpa",
    "area_of_interest",
    "year_of_passout",
}

RESUME_SIGNED_URL_TTL_SECONDS = 10 * 60  # 10 minutes


def _signed_resume_url(supa, resume_path: str | None):
    """Mint a short-lived signed URL for the owner's resume, or None."""
    if not resume_path:
        return None
    try:
        result = supa.storage.from_(Config.RESUME_STORAGE_BUCKET).create_signed_url(
            resume_path, RESUME_SIGNED_URL_TTL_SECONDS
        )
        # supabase-py has used both signedURL and signedUrl across versions.
        return result.get("signedURL") or result.get("signedUrl") or result.get("signed_url")
    except Exception:
        return None


def _profile_with_signed_resume(supa, row: dict) -> dict:
    row = dict(row or {})
    row["resume_signed_url"] = _signed_resume_url(supa, row.get("resume_path"))
    row.pop("resume_path", None)  # never leak the raw storage path to the client
    return row


@students_bp.get("/profile")
@require_auth
def get_profile():
    supa = get_supabase()
    row = supa.table("users").select("*").eq("id", g.user_id).single().execute().data
    return ok(_profile_with_signed_resume(supa, row) if row else {})


@students_bp.patch("/profile")
@require_auth
def update_profile():
    payload = request.get_json(silent=True) or {}
    updates = {k: v for k, v in payload.items() if k in EDITABLE_PROFILE_FIELDS}
    if not updates:
        return err("No valid fields to update", 400)

    validation_errors = validate_student_profile(updates)
    if validation_errors:
        return err("; ".join(validation_errors), 400)

    # normalize empty strings to null for numeric/optional fields
    for field in ("sslc_percentage", "hsc_percentage", "cgpa", "year_of_passout"):
        if updates.get(field) == "":
            updates[field] = None

    supa = get_supabase()
    row = supa.table("users").update(updates).eq("id", g.user_id).execute().data
    return ok(_profile_with_signed_resume(supa, row[0]) if row else {}, "Profile updated")


@students_bp.post("/resume")
@require_auth
def upload_resume():
    if "resume" not in request.files:
        return err("No file provided", 400)
    file = request.files["resume"]
    if file.filename == "":
        return err("Empty filename", 400)
    if not is_allowed_file(file.filename, Config.ALLOWED_RESUME_EXTENSIONS):
        return err("Unsupported file type. Only PDF, DOC, and DOCX are allowed.", 400)

    file.seek(0, os.SEEK_END)
    size_mb = file.tell() / (1024 * 1024)
    file.seek(0)
    if size_mb > Config.MAX_RESUME_SIZE_MB:
        return err(f"File exceeds {Config.MAX_RESUME_SIZE_MB}MB limit", 400)

    clean_name = safe_filename(file.filename)
    # Path is namespaced under the user's own uuid — this is what the
    # "resumes" bucket's storage RLS policies key off of (a user may
    # only read/write objects under their own auth.uid() folder).
    storage_path = f"{g.user_id}/{uuid.uuid4().hex}_{clean_name}"

    supa = get_supabase()
    file_bytes = file.read()
    supa.storage.from_(Config.RESUME_STORAGE_BUCKET).upload(
        storage_path, file_bytes, {"content-type": file.mimetype, "upsert": "true"}
    )

    # Best-effort: remove the previous resume object so we don't
    # accumulate orphaned private files for this user.
    try:
        existing = supa.table("users").select("resume_path").eq("id", g.user_id).single().execute().data
        old_path = (existing or {}).get("resume_path")
        if old_path and old_path != storage_path:
            supa.storage.from_(Config.RESUME_STORAGE_BUCKET).remove([old_path])
    except Exception:
        pass

    supa.table("users").update(
        {
            "resume_path": storage_path,
            "resume_original_name": clean_name,
            "resume_uploaded_at": utcnow().isoformat(),
        }
    ).eq("id", g.user_id).execute()

    signed_url = _signed_resume_url(supa, storage_path)
    return ok({"resume_signed_url": signed_url}, "Resume uploaded")
