"""Lightweight request-payload validation helpers (no external deps)."""
import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(email: str) -> bool:
    return bool(email) and bool(EMAIL_RE.match(email.strip()))


def require_fields(payload: dict, fields: list[str]) -> list[str]:
    """Return the list of missing/empty required fields."""
    missing = []
    for f in fields:
        val = payload.get(f)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(f)
    return missing


def is_allowed_file(filename: str, allowed_extensions: set[str]) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in allowed_extensions


def safe_filename(filename: str) -> str:
    """Strip path separators and dangerous characters from a filename."""
    filename = filename.replace("\\", "/").split("/")[-1]
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    return filename[:200]


def validate_student_profile(payload: dict) -> list[str]:
    """Validate the editable student-profile fields. Returns a list of
    human-readable error messages (empty list means valid)."""
    errors = []

    def _in_range(field, min_v, max_v):
        val = payload.get(field)
        if val is None or val == "":
            return
        try:
            num = float(val)
        except (TypeError, ValueError):
            errors.append(f"{field} must be a number.")
            return
        if not (min_v <= num <= max_v):
            errors.append(f"{field} must be between {min_v} and {max_v}.")

    _in_range("sslc_percentage", 0, 100)
    _in_range("hsc_percentage", 0, 100)
    _in_range("cgpa", 0, 10)

    year = payload.get("year_of_passout")
    if year not in (None, ""):
        try:
            year_int = int(year)
            if not (1980 <= year_int <= 2100):
                errors.append("year_of_passout must be a realistic year.")
        except (TypeError, ValueError):
            errors.append("year_of_passout must be a whole number.")

    phone = payload.get("phone")
    if phone not in (None, "") and not re.match(r"^[0-9+\-\s()]{7,20}$", str(phone)):
        errors.append("phone must be a valid phone number.")

    return errors
