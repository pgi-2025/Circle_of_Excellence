# Circle of Excellence — Scholarship Test & Campus Ambassador Platform

> **Core correctness pass (this build):** fixed naive `datetime.utcnow()`
> usage project-wide (now timezone-aware), made resume storage private
> with signed URLs instead of public URLs, made coupon redemption +
> enrollment atomic via a Postgres RPC, expanded the student profile to
> the full field set (SSLC%, HSC%, college, CGPA, area of interest, year
> of passout), stopped "Certificate issued" from being a manually
> completed milestone, standardized error responses, made Flask serve
> the frontend at `/` with config sourced from environment variables via
> `/config.js`, and removed the Campus Ambassador dashboard's demo-mode
> login/data/alerts in favor of real API calls (including previously
> missing endpoints: ambassador profile PATCH, referral-click tracking,
> marketing-kit listing/download, and ambassador certificate
> verification). Payment (Razorpay), the Job Portal, and the Admin
> frontend are still outstanding — see "Remaining issues" below.

Full-stack build of the Circle of Excellence (Circle Of Excellence) frontend:
a scholarship-test-gated internship program with a Campus Ambassador
referral system on top.

- **Frontend:** the original `circle-of-excellence.html`, split into
  `frontend/index.html`. UI/CSS/animations are untouched — only the
  JavaScript that talks to the backend was added (it already shipped
  with `apiFetch()` / `ambApiFetch()` helpers wired to `API_BASE`).
- **Backend:** Python + Flask, talking to Supabase PostgreSQL.
- **Database:** Supabase PostgreSQL with Row Level Security.
- **Auth:** Students authenticate via Supabase Auth (email/password).
  Ambassadors are a separate system with their own email/password table
  and a short-lived JWT issued by the Flask backend.

## Project structure

```
circle-of-excellence/
├── frontend/
│   └── index.html              # the original UI, wired to the API
├── backend/
│   ├── app.py                  # Flask app factory / entrypoint
│   ├── config.py               # ALL business rules live here (tiers, XP, limits)
│   ├── requirements.txt
│   ├── .env.example
│   ├── schema.sql              # full Supabase schema + RLS policies + seed data
│   ├── routes/                 # thin HTTP layer, one blueprint per domain
│   ├── services/                # business logic, talks to Supabase
│   └── utils/                  # auth, security, validators
├── tests/                      # pytest smoke + unit tests
├── README.md
└── .gitignore
```

## 1. Create your Supabase project

1. Go to [supabase.com](https://supabase.com) and create a new project.
2. In the SQL Editor, paste and run the entire contents of
   `backend/schema.sql`. This creates every table, enum, index, RLS
   policy, and a small amount of seed data (3 programs, 3 ambassador
   reward tiers).
3. Under **Storage**, create two buckets: `resumes` (private) and
   `marketing-assets` (public).
4. Under **Authentication → Providers**, make sure Email is enabled.
5. Add at least a few rows to `assessment_questions` (via the Table
   Editor or the admin API once it's running) — the scholarship test
   has nothing to serve until questions exist. Each row needs
   `question_text`, `options` (a JSON array of strings), and
   `correct_index` (0-based index into `options`).
6. To make yourself an admin: after signing up once through the
   frontend, find your row in `public.users` and set `role` to `admin`.

## 2. Configure environment variables

```bash
cd backend
cp .env.example .env
```

Fill in `.env`:

```
SUPABASE_URL=https://YOUR-PROJECT.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-role-key      # NEVER expose this to the frontend
FLASK_SECRET_KEY=some-long-random-string
JWT_SECRET_KEY=another-long-random-string        # signs the ambassador JWT
FRONTEND_URL=http://localhost:5000
API_BASE=http://localhost:5000
```

You do **not** need to edit `frontend/index.html` or hardcode any keys
there. Flask serves a `/config.js` endpoint (built from the environment
variables above) that the frontend loads at startup — this is the only
place `SUPABASE_URL`/`SUPABASE_ANON_KEY`/`API_BASE` come from. Never put
`SUPABASE_SERVICE_KEY`, `FLASK_SECRET_KEY`, `JWT_SECRET_KEY`, or
`RAZORPAY_KEY_SECRET` in the frontend or in `frontend/config.js` — those
stay server-side only.

## 3. Backend setup (Windows)

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

The API now runs at `http://localhost:5000`. Check it with:

```
GET http://localhost:5000/api/health
-> {"success": true, "message": "API is running", "data": {}}
```

(macOS/Linux: use `python3 -m venv venv` and `source venv/bin/activate`.)

## 4. Run the frontend

Flask serves the frontend directly — once `python app.py` is running,
just open **`http://localhost:5000/`** in your browser. There is no
separate frontend server or build step, and `/` no longer 404s.

(You can still serve `frontend/` with a separate static server during
development if you prefer; in that case point `frontend/config.js` at
your Flask API's URL and make sure `FRONTEND_URL` in `backend/.env`
matches whatever origin you're serving it from, or CORS will block
requests.)

## 5. Test the flow end to end

1. Sign up as a student (top-right **Sign Up**).
2. Take the Scholarship Test — questions come from `assessment_questions`,
   are served without their correct answers, graded server-side, and
   timed server-side.
3. Score ≥50% and you'll get a coupon (50% / 80% / 100% off depending
   on tier), valid for 24 hours, shown with a live countdown.
4. Click **Apply Coupon & Enroll** to enroll in the first active
   program and open the student dashboard.
5. Apply to become a Campus Ambassador, or log in with the demo
   credentials shown in that modal (`ambassador@demo.com` /
   `Ambassador123`) to preview the ambassador dashboard against demo
   data if no real ambassador API/account exists yet — once a real
   backend + ambassador account is set up, the same login flow talks
   to `/api/ambassador/login` instead.

## Key design decisions

- **The correct answer never reaches the browser.** Questions are
  served with only `id`, `question_text`, and (shuffled) `options`.
  Grading happens entirely in `services/assessment_service.py`.
- **The timer is server-authoritative.** `expires_at` is computed and
  stored server-side at `/api/test/start`; `/api/test/submit` checks
  the wall-clock against it, so a client-side clock can't be spoofed to
  buy extra time.
- **Anti-cheat violations gate coupon eligibility**, not the score
  itself — 3+ flagged violations (tab switches, etc.) make an attempt
  ineligible for a coupon even with a passing score, per
  `Config.ASSESSMENT_MAX_VIOLATIONS_FOR_COUPON`.
- **Scholarship tiers and XP rules are centralized** in `config.py` —
  nothing in `routes/` or `services/` hardcodes a percentage or XP
  amount, so tuning the program only ever means editing one file.
- **Ambassador referral credit requires a genuine enrollment**, not
  just a click or signup, and a DB-level unique index prevents the same
  student being credited to the same ambassador twice — this is the
  fraud gate the spec asked for.
- **Ambassadors are not Supabase Auth users.** They have their own
  `ambassadors` table (bcrypt-style hashed password via Werkzeug) and a
  separate JWT (`utils/auth.py: issue_ambassador_token` /
  `require_ambassador_auth`), kept fully independent of student
  sessions — mirroring how the frontend already keeps `amb_session` in
  its own `localStorage` key, separate from the Supabase session.
- **RLS is defense-in-depth.** The Flask backend uses the Supabase
  service-role key and enforces authorization in application code
  (`utils/auth.py`); `schema.sql`'s RLS policies protect the same data
  if it's ever queried directly via PostgREST with a user's own token.

## Running tests

```bash
pip install pytest
python -m pytest tests/ -v
```

The included tests are smoke/unit tests that don't require a live
Supabase project (health check, 404/401 handling, tier-boundary math).
Full integration tests against the assessment/coupon/enrollment flows
need a real or test Supabase project, since the services call out to
Supabase directly rather than through a mockable ORM.

## Deployment (Render, no Docker)

1. Push this repo to GitHub.
2. On Render: **New → Web Service**, point it at the repo,
   set **Root Directory** to `backend`.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Add all the `.env` variables above as Render environment variables.
6. Update `API_BASE` in `frontend/index.html` to your Render URL, and
   set `FRONTEND_URL` in Render's env vars to wherever you host the
   frontend (e.g. Netlify/Vercel/GitHub Pages).

## API reference (selected)

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/health` | none | `{success, message, data}` |
| POST | `/api/auth/bootstrap-profile` | student | creates `public.users` row post-signup |
| GET | `/api/auth/me` | student | |
| GET | `/api/programs` | none | bare array |
| POST | `/api/test/start` | student | starts a randomized, timed attempt |
| POST | `/api/test/answer` | student | autosave one answer |
| POST | `/api/test/flag-activity` | student | records an anti-cheat violation |
| POST | `/api/test/submit` | student | server-side grading + coupon issuance |
| POST | `/api/enroll` | student | enroll with an optional coupon code |
| GET | `/api/dashboard` | student | enrollment + milestones + coupons + certificate |
| GET | `/api/certificates/verify/<code>` | none | public certificate verification |
| POST | `/api/ambassador/apply` | none | |
| POST | `/api/ambassador/login` | none | returns ambassador JWT |
| GET | `/api/ambassador/profile`, `/referrals`, `/campaigns`, `/events`, `/challenges`, `/rewards`, `/leaderboard`, `/certificate` | ambassador | |
| `/api/admin/*` | admin | students, programs, questions, assessments, enrollments, coupons, milestones, certificates, applications, ambassadors, referrals, XP, campaigns, events, rewards, analytics |

All endpoints return `{"success": bool, "message": str, "data": ...}`
**except** the handful the frontend's already-written JavaScript reads
flat fields from directly (`/api/programs`, `/api/test/*`,
`/api/dashboard`, `/api/auth/me`, `/api/enroll`, and the `/api/ambassador/*`
data endpoints) — those return the bare object/array the frontend
expects, to avoid touching the preserved frontend JS.

## Remaining issues (not yet built)

These are real gaps, called out honestly rather than glossed over:

- **Payment (Razorpay)** — no routes, service, or schema fields yet.
  `POST /api/payment/create-order|verify|webhook` still need to be
  built, plus `razorpay_order_id`/`razorpay_payment_id` columns on
  `enrollments` and server-side signature/webhook verification.
- **Job Portal** — `companies`/`company_users`/`jobs`/`job_applications`
  tables, the `company` role, and all company/student job-flow
  endpoints are not implemented.
- **Admin frontend** — the admin *API* is complete (`/api/admin/*`), but
  there is no admin UI yet; admins currently need to call the API
  directly (e.g. via Postman) or you build a small dashboard against it.
- **Test coverage** — only health/config smoke tests exist. Section 19's
  full list (coupon expiry/ownership, payment verification, referral XP
  idempotency, admin/company authorization, etc.) is still open.
- **requirements.txt** — does not yet include `razorpay`; add it once
  the payment integration lands.
