"""Public program listing — matches the frontend's loadPrograms()."""
from flask import Blueprint, jsonify
from services.supabase_client import get_supabase

programs_bp = Blueprint("programs", __name__, url_prefix="/api/programs")


@programs_bp.get("")
def list_programs():
    # NOTE: the frontend does `programs.map(...)` directly on this
    # response, so it must be a bare JSON array (not the {success,
    # message, data} envelope used elsewhere).
    supa = get_supabase()
    rows = supa.table("programs").select("*").eq("is_active", True).order("created_at").execute().data or []
    return jsonify(rows)


@programs_bp.get("/<program_id>")
def get_program(program_id):
    supa = get_supabase()
    row = supa.table("programs").select("*").eq("id", program_id).single().execute().data
    if not row:
        return jsonify({"success": False, "message": "Program not found", "data": {}}), 404
    return jsonify({"success": True, "message": "", "data": row})
