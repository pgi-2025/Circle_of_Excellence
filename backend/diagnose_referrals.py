"""
Diagnose the /api/ambassador/referrals 500 by calling the exact same
Supabase queries directly - no Flask, no HTTP, no JWT, no CORS in the way.

Run from your backend/ folder (same place as app.py), with your venv active:

    python diagnose_referrals.py <ambassador_id>

Get <ambassador_id> from your ambassadors table (Supabase Table Editor ->
ambassadors -> copy the "id" UUID for the ambassador account you logged in
with), or leave it blank to just list existing ambassador IDs first.

This will print the FULL traceback for whichever query actually fails.
"""
import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.supabase_client import get_supabase  # noqa: E402


def list_ambassador_ids():
    supa = get_supabase()
    rows = supa.table("ambassadors").select("id, email, ambassador_code, is_active").execute().data or []
    print(f"\nFound {len(rows)} ambassador row(s):")
    for r in rows:
        print(f"  id={r['id']}  email={r['email']}  code={r['ambassador_code']}  active={r['is_active']}")
    return rows


def run(ambassador_id: str):
    supa = get_supabase()

    print("\n--- Step 1: fetch ambassador row ---")
    try:
        amb_rows = supa.table("ambassadors").select("*").eq("id", ambassador_id).execute().data or []
        print("OK, rows returned:", len(amb_rows))
        if not amb_rows:
            print("!! No ambassador row matches this id. This is likely your root cause.")
            return
        amb = amb_rows[0]
        print("ambassador_code:", amb.get("ambassador_code"), "| xp:", amb.get("xp"))
    except Exception:
        print("!! FAILED at Step 1 (ambassadors table). Full traceback:")
        traceback.print_exc()
        return

    print("\n--- Step 2: fetch ambassador_referrals rows ---")
    try:
        refs = supa.table("ambassador_referrals").select("*").eq("ambassador_id", ambassador_id).execute().data or []
        print("OK, rows returned:", len(refs))
    except Exception:
        print("!! FAILED at Step 2 (ambassador_referrals table). Full traceback:")
        traceback.print_exc()
        return

    print("\n--- Step 3: fetch ambassador_reward_claims rows ---")
    try:
        claims = supa.table("ambassador_reward_claims").select("id").eq("ambassador_id", ambassador_id).execute().data or []
        print("OK, rows returned:", len(claims))
    except Exception:
        print("!! FAILED at Step 3 (ambassador_reward_claims table). Full traceback:")
        traceback.print_exc()
        return

    print("\n--- Step 4: run full get_referrals_summary() ---")
    try:
        from services import ambassador_service
        result = ambassador_service.get_referrals_summary(ambassador_id)
        print("SUCCESS. Result:")
        print(result)
    except Exception:
        print("!! FAILED at Step 4 (get_referrals_summary). Full traceback:")
        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("No ambassador_id given - listing existing ambassadors instead:")
        list_ambassador_ids()
        print("\nRe-run as: python diagnose_referrals.py <ambassador_id>")
    else:
        run(sys.argv[1])
