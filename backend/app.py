"""
Circle of Excellence — Flask application factory & entrypoint.

Run locally with:
    python app.py
Or in production with:
    gunicorn app:app
"""
import logging
import os

from flask import Flask, jsonify, send_from_directory, Response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("circle_of_excellence")

# backend/app.py -> ../frontend
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)

    # --- CORS: only allow the configured frontend origin, with credentials ---
    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": [
                    Config.FRONTEND_URL,
                    Config.API_BASE,
                    "http://localhost:5500",
                    "http://127.0.0.1:5500",
                    "http://localhost:5000",
                    "http://127.0.0.1:5000",
                ]
            }
        },
        supports_credentials=True,
    )

    # --- Rate limiting ---
    limiter = Limiter(get_remote_address, app=app, default_limits=[Config.RATE_LIMIT_DEFAULT])

    # --- Blueprints ---
    from routes.auth import auth_bp
    from routes.students import students_bp
    from routes.programs import programs_bp
    from routes.assessment import assessment_bp
    from routes.enrollment import enrollment_bp
    from routes.coupons import coupons_bp
    from routes.certificates import certificates_bp
    from routes.ambassadors import ambassadors_bp
    from routes.admin import admin_bp
    from routes.payments import payments_bp
    from routes.psychometric import psy_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(assessment_bp)
    app.register_blueprint(enrollment_bp)
    app.register_blueprint(coupons_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(ambassadors_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(psy_bp)

    # --- Tighter rate limits on sensitive endpoints ---
    limiter.limit(Config.RATE_LIMIT_AUTH)(auth_bp)
    limiter.limit(Config.RATE_LIMIT_AUTH)(app.view_functions["ambassadors.login"])
    # Scholarship test: start/submit keep the tight cap; answer/flag-activity get headroom because a
    # test sends an autosave per question and anti-cheat pings (a blanket blueprint-level cap of
    # 10/hour would silently drop autosaves after the 10th answer). The registered view function
    # must be swapped for the wrapped one, otherwise a per-route limit is never enforced.
    for _endpoint, _limit in (
        ("assessment.start", Config.RATE_LIMIT_ASSESSMENT_SUBMIT),
        ("assessment.submit", Config.RATE_LIMIT_ASSESSMENT_SUBMIT),
        ("assessment.answer", Config.RATE_LIMIT_ASSESSMENT_ACTIVITY),
        ("assessment.flag_activity", Config.RATE_LIMIT_ASSESSMENT_ACTIVITY),
    ):
        app.view_functions[_endpoint] = limiter.limit(_limit, methods=["POST"])(app.view_functions[_endpoint])
    limiter.limit(Config.RATE_LIMIT_PSY)(psy_bp)  # many answer/violation pings per test; shared campus IPs

    # --- Health check ---
    @app.get("/api/health")
    def health():
        return jsonify({"success": True, "message": "API is running", "data": {}})

    # --- Public frontend configuration ---
    # Serves ONLY public, safe-to-expose values (never the service role
    # key, JWT secret, or any other server secret). The frontend loads
    # this before its own script instead of hardcoding Supabase config.
    @app.get("/config.js")
    def frontend_config():
        js = (
            "window.APP_CONFIG = {\n"
            f"  SUPABASE_URL: {Config.SUPABASE_URL!r},\n"
            f"  SUPABASE_ANON_KEY: {Config.SUPABASE_ANON_KEY!r},\n"
            f"  API_BASE: {Config.API_BASE!r}\n"
            "};\n"
        )
        return Response(js, mimetype="application/javascript")

    # --- Serve the frontend itself ---
    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/r/<share_token>")
    def shared_report_page(share_token):
        """Public report page: serves the SPA plus Open Graph tags so WhatsApp/LinkedIn show a preview."""
        from html import escape
        from services import psychometric_service as psy
        with open(os.path.join(FRONTEND_DIR, "index.html"), encoding="utf-8") as f:
            page = f.read()
        try:
            rep = psy.get_public_report(share_token)
            title = escape(f"{rep['candidate_name']} - Campus Ambassador Assessment: {rep['overall_score']}%", quote=True)
            og = (f'<meta property="og:title" content="{title}">'
                  '<meta property="og:description" content="Psychometric performance report - Circle of Excellence">'
                  '<meta property="og:type" content="website"><meta name="robots" content="noindex">')
            page = page.replace("</head>", og + "</head>", 1)
        except Exception:
            pass
        return Response(page, mimetype="text/html")

    @app.get("/<path:path>")
    def frontend_assets(path):
        # Never let this catch-all swallow API routes or a missing file
        # under /api — those should hit the JSON 404 handler instead.
        if path.startswith("api/"):
            return jsonify({"success": False, "message": "Not found", "data": {}}), 404
        full_path = os.path.join(FRONTEND_DIR, path)
        if os.path.isfile(full_path):
            return send_from_directory(FRONTEND_DIR, path)
        # SPA-style fallback for any other frontend route
        return send_from_directory(FRONTEND_DIR, "index.html")

    # --- Error handlers ---
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"success": False, "message": "Not found", "data": {}}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"success": False, "message": "Method not allowed", "data": {}}), 405

    @app.errorhandler(429)
    def rate_limited(e):
        return jsonify({"success": False, "message": "Too many requests — please slow down", "data": {}}), 429

    from werkzeug.exceptions import HTTPException

    @app.errorhandler(Exception)
    def unhandled(e):
        if isinstance(e, HTTPException):
            return e
        logger.exception("Unhandled server error")
        msg = f"{type(e).__name__}: {e}" if app.debug else "Internal server error"
        return jsonify({"success": False, "message": msg, "error": msg, "data": {}}), 500

    @app.errorhandler(500)
    def server_error(e):
        logger.exception("Unhandled server error")
        return jsonify({"success": False, "message": "Internal server error", "data": {}}), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
