"""
Single place that constructs Supabase clients.

use_service_role=True  -> uses SUPABASE_SERVICE_KEY (bypasses RLS; used
                           by the backend for privileged operations like
                           grading, coupon issuance, XP updates).
use_service_role=False -> uses SUPABASE_ANON_KEY (respects RLS; used
                           only for verifying a student's own JWT via
                           auth.get_user()).

The service key must NEVER be sent to the frontend.
"""
from supabase import create_client, Client
from config import Config

_service_client: Client | None = None
_anon_client: Client | None = None


def get_supabase(use_service_role: bool = True) -> Client:
    global _service_client, _anon_client
    if use_service_role:
        if _service_client is None:
            _service_client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
        return _service_client
    else:
        if _anon_client is None:
            _anon_client = create_client(Config.SUPABASE_URL, Config.SUPABASE_ANON_KEY)
        return _anon_client
