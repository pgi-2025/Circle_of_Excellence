"""
Central configuration for the Circle of Excellence backend.
All scholarship-tier / coupon / anti-cheat business rules live HERE so
they are easy to audit and change without touching route logic.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # --- Supabase ---
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
    SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

    # --- Flask / JWT ---
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-jwt-secret-change-me")
    JWT_ALGORITHM = "HS256"
    AMBASSADOR_JWT_EXPIRY_HOURS = 24 * 7  # ambassador login token lifetime

    # --- Razorpay (key id is public; secret + webhook secret stay server-side) ---
    RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

    # --- CORS ---
    FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5500")

   # --- Public frontend config (served via /config.js, never secrets) ---
    API_BASE = os.environ.get("API_BASE", "http://localhost:5000")

    # --- Email (ambassador credential notifications) ---
    SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "Circle Of Excellence")

    # --- Assessment rules ---
    ASSESSMENT_QUESTION_COUNT = 20
    ASSESSMENT_TIME_LIMIT_SECONDS = 40 * 60  # 40 minutes
    ASSESSMENT_MAX_VIOLATIONS_FOR_COUPON = 3  # 3+ violations => no coupon
    ASSESSMENT_ONE_ACTIVE_ATTEMPT = True
    ASSESSMENT_TECHNICAL_SHARE = 0.5          # share of each attempt drawn from category 'technical' (rest: 'non_technical')

    # --- Scholarship test anti-cheat (server-side risk scoring) ---
    # Every client-reported flag adds its weight to the attempt's risk score.
    ASSESSMENT_FLAG_WEIGHTS = {
        "dev_tools": 4,
        "tab_switch": 3,
        "fullscreen_exit": 3,
        "copy_paste": 2,
        "window_blur": 1,
        "other": 1,
        "phone_detected": 3,
        "multiple_faces": 3,
        "head_turned": 3,
        "no_face": 3,
        "camera_blocked": 3,
    }
    PROCTOR_MAX_VIOLATIONS = 3   # 3 violations are allowed; the next one auto-submits the test
    ASSESSMENT_RISK_REVIEW = 6                # risk >= this  => 'review': no automatic coupon
    ASSESSMENT_RISK_DISQUALIFY = 12           # risk >= this  => 'disqualified': attempt is ended
    ASSESSMENT_MAX_FLAG_ROWS = 100            # cap stored flag rows per attempt (spam guard)
    ASSESSMENT_MIN_SECONDS_PER_QUESTION = 6   # finishing faster than this on average is suspicious
    ASSESSMENT_FAST_ANSWER_SECONDS = 2        # answers recorded closer together than this count as "rapid"
    ASSESSMENT_FAST_ANSWER_RATIO = 0.5        # >= this share of rapid answers is suspicious

    # --- Campus Ambassador psychometric assessment ---
    PSY_QUESTION_COUNT = 20
    PSY_TIME_LIMIT_SECONDS = 25 * 60
    PSY_SUBMIT_GRACE_SECONDS = 30          # network slack for the auto-submit at time-up
    PSY_VIOLATIONS_REVIEW = 1              # >= this many violations => integrity "review"
    PSY_VIOLATIONS_FLAGGED = 3             # >= this many violations => integrity "flagged"
    PSY_MIN_SECONDS_PER_QUESTION = 3       # finishing faster than this on average is flagged
    PSY_MAX_VIOLATION_ROWS = 200           # cap stored rows per attempt (spam guard)

    # --- Scholarship tiers: (min_score_percent, max_score_percent, discount_percent, coupon_prefix) ---
    SCHOLARSHIP_TIERS = [
        {"min": 100, "max": 100, "discount_percent": 100, "prefix": "FULLSCHOLARSHIP"},
        {"min": 80, "max": 99, "discount_percent": 80, "prefix": "80OFF"},
        {"min": 50, "max": 79, "discount_percent": 50, "prefix": "50OFF"},
    ]

    # --- Coupons ---
    COUPON_EXPIRY_HOURS = 24
    COUPON_CODE_LENGTH = 8

    # --- Ambassador XP rules ---
    XP_PER_REGISTRATION = 20
    XP_PER_ASSESSMENT_ATTEMPT = 10
    XP_PER_SUCCESSFUL_ENROLLMENT = 100
    XP_PER_EVENT_ATTENDANCE = 50

    AMBASSADOR_LEVELS = [
        {"name": "Campus Starter", "min_xp": 0},
        {"name": "Campus Promoter", "min_xp": 300},
        {"name": "Campus Leader", "min_xp": 750},
        {"name": "Campus Champion", "min_xp": 1500},
        {"name": "Campus Star", "min_xp": 3000},
    ]

    # --- File uploads ---
    ALLOWED_RESUME_EXTENSIONS = {"pdf", "doc", "docx"}
    MAX_RESUME_SIZE_MB = 5
    RESUME_STORAGE_BUCKET = "resumes"
    ASSET_STORAGE_BUCKET = "marketing-assets"

    # --- Rate limiting defaults ---
    RATE_LIMIT_DEFAULT = "200 per hour"
    RATE_LIMIT_AUTH = "20 per hour"
    RATE_LIMIT_ASSESSMENT_SUBMIT = "10 per hour"      # /api/test/start and /api/test/submit
    RATE_LIMIT_ASSESSMENT_ACTIVITY = "600 per hour"   # /api/test/answer and /api/test/flag-activity (many pings per test)
    RATE_LIMIT_PSY = "600 per hour"


def get_scholarship_tier(score_percent: int):
    """Return the matching tier dict for a given score, or None."""
    for tier in Config.SCHOLARSHIP_TIERS:
        if tier["min"] <= score_percent <= tier["max"]:
            return tier
    return None


def get_ambassador_level(xp: int):
    """Return the highest level dict the ambassador's XP qualifies for."""
    current = Config.AMBASSADOR_LEVELS[0]
    for level in Config.AMBASSADOR_LEVELS:
        if xp >= level["min_xp"]:
            current = level
    return current
