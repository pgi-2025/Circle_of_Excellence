/**
 * Static fallback frontend configuration.
 *
 * When Flask serves this frontend (the normal setup — see backend/app.py),
 * it generates /config.js dynamically from environment variables and this
 * file is never used.
 *
 * If you instead host frontend/ on a separate static host (Netlify, S3,
 * GitHub Pages, etc.) and point it at a Flask API elsewhere, edit the
 * values below and make sure Flask's own /config.js route does NOT also
 * get requested (i.e. don't rely on this file being replaced at runtime).
 *
 * Only public, safe-to-expose values belong here — the Supabase URL and
 * ANON key are meant to be public. NEVER put SUPABASE_SERVICE_KEY,
 * FLASK_SECRET_KEY, JWT_SECRET_KEY, or RAZORPAY_KEY_SECRET here or
 * anywhere in the frontend.
 */
window.APP_CONFIG = {
  SUPABASE_URL: "",       // e.g. "https://xxxxxxxx.supabase.co"
  SUPABASE_ANON_KEY: "",  // the public anon key from your Supabase project settings
  API_BASE: "http://localhost:5000"
};
