"""Certificate verification — public endpoint, no auth required."""
from flask import Blueprint, jsonify
from services.enrollment_service import verify_certificate

certificates_bp = Blueprint("certificates", __name__, url_prefix="/api/certificates")


@certificates_bp.get("/verify/<code>")
def verify(code):
    try:
        data = verify_certificate(code)
        return jsonify({"success": True, "message": "Certificate verified", "data": data})
    except ValueError as e:
        return jsonify({"success": False, "message": str(e), "data": {}}), 404
