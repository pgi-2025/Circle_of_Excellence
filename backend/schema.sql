-- =====================================================================
-- Circle of Excellence — Supabase PostgreSQL schema
-- Run this whole file in the Supabase SQL editor (or via `psql`) on a
-- fresh project. It creates all tables, indexes, enums, and Row Level
-- Security (RLS) policies used by the Flask backend.
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------
-- ENUMS
-- ---------------------------------------------------------------------
do $$ begin
  create type user_role as enum ('student','ambassador','college_coordinator','admin');
exception when duplicate_object then null; end $$;

do $$ begin
  create type attempt_status as enum ('in_progress','submitted','expired','disqualified');
exception when duplicate_object then null; end $$;

do $$ begin
  create type coupon_status as enum ('active','used','expired');
exception when duplicate_object then null; end $$;

do $$ begin
  create type payment_status as enum ('pending','paid','free','failed','refunded');
exception when duplicate_object then null; end $$;

do $$ begin
  create type milestone_status as enum ('pending','in_progress','complete');
exception when duplicate_object then null; end $$;

do $$ begin
  create type ambassador_app_status as enum ('pending','approved','rejected');
exception when duplicate_object then null; end $$;

do $$ begin
  create type flag_kind as enum ('tab_switch','fullscreen_exit','copy_paste','dev_tools','window_blur','other');
exception when duplicate_object then null; end $$;

-- ---------------------------------------------------------------------
-- USERS  (extends Supabase auth.users 1:1 via id)
-- ---------------------------------------------------------------------
create table if not exists public.users (
  id uuid primary key references auth.users(id) on delete cascade,
  email text unique not null,
  full_name text,
  phone text,
  role user_role not null default 'student',

  -- Student profile fields (Section 2 of the spec)
  educational_qualification text,
  sslc_percentage numeric(5,2) check (sslc_percentage is null or (sslc_percentage >= 0 and sslc_percentage <= 100)),
  hsc_percentage numeric(5,2) check (hsc_percentage is null or (hsc_percentage >= 0 and hsc_percentage <= 100)),
  college text,
  cgpa numeric(5,2) check (cgpa is null or (cgpa >= 0 and cgpa <= 10)),
  area_of_interest text,
  year_of_passout int check (year_of_passout is null or (year_of_passout between 1980 and 2100)),

  -- Resume: stored PRIVATELY in Supabase Storage. We keep only the
  -- storage path here, never a public URL — the backend mints a
  -- short-lived signed URL on demand for the authenticated owner.
  resume_path text,
  resume_original_name text,
  resume_uploaded_at timestamptz,

  -- kept for backward compatibility with any historical rows/data that
  -- used the old free-text jsonb blob before the columns above existed
  education_details jsonb default '{}'::jsonb,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_users_role on public.users(role);

-- Idempotent migration for databases that already had an earlier
-- version of this table (safe to re-run; no-ops if already applied).
alter table public.users add column if not exists educational_qualification text;
alter table public.users add column if not exists sslc_percentage numeric(5,2);
alter table public.users add column if not exists hsc_percentage numeric(5,2);
alter table public.users add column if not exists college text;
alter table public.users add column if not exists cgpa numeric(5,2);
alter table public.users add column if not exists area_of_interest text;
alter table public.users add column if not exists year_of_passout int;
alter table public.users add column if not exists resume_path text;
alter table public.users add column if not exists resume_original_name text;
-- SECURITY FIX: earlier versions stored a public resume URL. Resumes
-- must be private; drop that column in favor of resume_path (a
-- storage object path the backend turns into short-lived signed URLs).
alter table public.users drop column if exists resume_url;

-- ---------------------------------------------------------------------
-- PROGRAMS
-- ---------------------------------------------------------------------
create table if not exists public.programs (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text unique not null,
  description text,
  skills text,
  mentor_title text,
  duration_weeks int not null default 8,
  mode text not null default 'Remote',
  base_price_cents bigint not null default 999900, -- ₹9,999.00
  image_url text,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- ASSESSMENT: questions / attempts / answers / flags
-- ---------------------------------------------------------------------
create table if not exists public.assessment_questions (
  id uuid primary key default gen_random_uuid(),
  question_text text not null,
  options jsonb not null,              -- ["opt A","opt B","opt C","opt D"]
  correct_index int not null,          -- NEVER sent to the client
  difficulty text default 'medium',
  topic text,
  code text,                           -- stable id used by the question-bank seed
  category text,                       -- 'technical' | 'non_technical'
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);
create unique index if not exists uq_assessment_questions_code on public.assessment_questions(code);

create table if not exists public.assessment_attempts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  status attempt_status not null default 'in_progress',
  question_ids uuid[] not null,        -- the randomized set drawn for this attempt
  time_limit_seconds int not null,
  started_at timestamptz not null default now(),
  expires_at timestamptz not null,
  submitted_at timestamptz,
  score_percent int,
  violation_count int not null default 0,
  eligible_for_coupon boolean,
  option_orders jsonb,                 -- per-question shuffled option order for this attempt
  risk_score int not null default 0,   -- anti-cheat risk (weighted flags + timing analysis)
  integrity_status text,               -- 'clean' | 'review' | 'disqualified'
  integrity_notes jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_attempts_user on public.assessment_attempts(user_id);
create index if not exists idx_attempts_status on public.assessment_attempts(status);

create table if not exists public.assessment_answers (
  id uuid primary key default gen_random_uuid(),
  attempt_id uuid not null references public.assessment_attempts(id) on delete cascade,
  question_id uuid not null references public.assessment_questions(id),
  selected_index int,
  is_correct boolean,
  answered_at timestamptz not null default now(),
  unique(attempt_id, question_id)
);

create table if not exists public.assessment_flags (
  id uuid primary key default gen_random_uuid(),
  attempt_id uuid not null references public.assessment_attempts(id) on delete cascade,
  kind flag_kind not null,
  detail text,
  created_at timestamptz not null default now()
);
create index if not exists idx_flags_attempt on public.assessment_flags(attempt_id);

-- ---------------------------------------------------------------------
-- COUPONS
-- ---------------------------------------------------------------------
create table if not exists public.coupons (
  id uuid primary key default gen_random_uuid(),
  code text unique not null,
  user_id uuid not null references public.users(id) on delete cascade,
  attempt_id uuid references public.assessment_attempts(id),
  discount_percent int not null,
  base_price_cents bigint not null,
  final_price_cents bigint not null,
  status coupon_status not null default 'active',
  issued_at timestamptz not null default now(),
  expires_at timestamptz not null,
  used_at timestamptz,
  used_for_enrollment_id uuid,
  created_at timestamptz not null default now()
);
create index if not exists idx_coupons_user on public.coupons(user_id);
create index if not exists idx_coupons_code on public.coupons(code);
create index if not exists idx_coupons_status on public.coupons(status);

-- ---------------------------------------------------------------------
-- ENROLLMENTS / MILESTONES / CERTIFICATES
-- ---------------------------------------------------------------------
create table if not exists public.enrollments (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  program_id uuid not null references public.programs(id),
  coupon_id uuid references public.coupons(id),
  referred_by_ambassador_id uuid,  -- fk added after ambassadors table exists
  final_price_cents bigint not null,
  payment_status payment_status not null default 'pending',
  enrolled_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);
create index if not exists idx_enrollments_user on public.enrollments(user_id);

create table if not exists public.milestones (
  id uuid primary key default gen_random_uuid(),
  enrollment_id uuid not null references public.enrollments(id) on delete cascade,
  title text not null,
  detail text,
  status milestone_status not null default 'pending',
  sort_order int not null default 0,
  completed_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists idx_milestones_enrollment on public.milestones(enrollment_id);

create table if not exists public.certificates (
  id uuid primary key default gen_random_uuid(),
  enrollment_id uuid not null references public.enrollments(id) on delete cascade,
  user_id uuid not null references public.users(id) on delete cascade,
  certificate_code text unique not null,
  issue_date date not null default current_date,
  verification_url text,
  created_at timestamptz not null default now()
);
create index if not exists idx_certificates_code on public.certificates(certificate_code);

-- ---------------------------------------------------------------------
-- CAMPUS AMBASSADOR SYSTEM
-- ---------------------------------------------------------------------
create table if not exists public.ambassador_applications (
  id uuid primary key default gen_random_uuid(),
  full_name text not null,
  email text not null,
  phone text,
  college text not null,
  department text,
  year text,
  city text,
  social text,
  reach int,
  why text,
  referral_code_used text,
  status ambassador_app_status not null default 'pending',
  reviewed_by uuid references public.users(id),
  reviewed_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists idx_amb_app_status on public.ambassador_applications(status);
create index if not exists idx_amb_app_email on public.ambassador_applications(email);

alter table public.ambassador_applications add column if not exists rejection_reason text;

create unique index if not exists uq_amb_app_email_active
  on public.ambassador_applications(lower(email))
  where status in ('pending', 'approved');

create table if not exists public.ambassadors (
  id uuid primary key default gen_random_uuid(),
  user_id uuid unique references public.users(id) on delete cascade,
  application_id uuid references public.ambassador_applications(id),
  ambassador_code text unique not null,  -- e.g. AMB12345, used as referral code
  full_name text not null,
  email text unique not null,
  password_hash text not null,
  phone text,
  college text,
  department text,
  year text,
  city text,
  social text,
  xp int not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);
create index if not exists idx_ambassadors_code on public.ambassadors(ambassador_code);
create index if not exists idx_ambassadors_email on public.ambassadors(email);

-- CHANGE 1: fk_enrollments_ambassador — kept as a guarded DO block
-- (checks pg_constraint before adding), so re-running the file never
-- raises 42710 "constraint already exists".
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_enrollments_ambassador'
      AND conrelid = 'public.enrollments'::regclass
  ) THEN
    ALTER TABLE public.enrollments
      ADD CONSTRAINT fk_enrollments_ambassador
      FOREIGN KEY (referred_by_ambassador_id)
      REFERENCES public.ambassadors(id)
      ON DELETE SET NULL;
  END IF;
END $$;

create table if not exists public.ambassador_referrals (
  id uuid primary key default gen_random_uuid(),
  ambassador_id uuid not null references public.ambassadors(id) on delete cascade,
  referred_user_id uuid references public.users(id) on delete set null,
  referral_code text not null,
  click_id text,                          -- for click-level attribution before signup
  registered boolean not null default false,
  assessment_attempted boolean not null default false,
  assessment_registered_at timestamptz,   -- set by /api/test/register
  applied boolean not null default false, -- applied a coupon
  enrolled boolean not null default false,
  enrollment_id uuid references public.enrollments(id),
  xp_awarded int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_referrals_ambassador on public.ambassador_referrals(ambassador_id);
create index if not exists idx_referrals_user on public.ambassador_referrals(referred_user_id);
-- prevent the same student being credited to the same ambassador twice
create unique index if not exists uq_referral_ambassador_user
  on public.ambassador_referrals(ambassador_id, referred_user_id)
  where referred_user_id is not null;

create table if not exists public.ambassador_campaigns (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  description text,
  starts_at date,
  ends_at date,
  target_count int not null default 0,
  xp_reward int not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.ambassador_campaign_participation (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references public.ambassador_campaigns(id) on delete cascade,
  ambassador_id uuid not null references public.ambassadors(id) on delete cascade,
  progress int not null default 0,
  joined_at timestamptz not null default now(),
  unique(campaign_id, ambassador_id)
);

create table if not exists public.ambassador_events (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  college text,
  event_date date,
  event_time text,
  location text,
  description text,
  created_at timestamptz not null default now()
);

create table if not exists public.ambassador_event_attendance (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references public.ambassador_events(id) on delete cascade,
  ambassador_id uuid not null references public.ambassadors(id) on delete cascade,
  attended boolean not null default false,
  marked_at timestamptz,
  created_at timestamptz not null default now(),
  unique(event_id, ambassador_id)
);

create table if not exists public.ambassador_challenges (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  description text,
  target_count int not null default 1,
  xp_reward int not null default 0,
  metric text not null default 'referrals', -- referrals | enrollments | campaigns
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.ambassador_rewards (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  requirement text,
  min_xp int default 0,
  min_enrollments int default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.ambassador_reward_claims (
  id uuid primary key default gen_random_uuid(),
  reward_id uuid not null references public.ambassador_rewards(id) on delete cascade,
  ambassador_id uuid not null references public.ambassadors(id) on delete cascade,
  claimed_at timestamptz not null default now(),
  unique(reward_id, ambassador_id)
);

create table if not exists public.ambassador_xp_transactions (
  id uuid primary key default gen_random_uuid(),
  ambassador_id uuid not null references public.ambassadors(id) on delete cascade,
  amount int not null,
  reason text not null,          -- e.g. 'referral_enrollment', 'event_attendance'
  reference_id uuid,             -- points at referral/enrollment/event id
  created_at timestamptz not null default now()
);
create index if not exists idx_xp_tx_ambassador on public.ambassador_xp_transactions(ambassador_id);

create table if not exists public.ambassador_certificates (
  id uuid primary key default gen_random_uuid(),
  ambassador_id uuid not null references public.ambassadors(id) on delete cascade,
  certificate_code text unique not null,
  title text not null default 'Campus Ambassador',
  issue_date date not null default current_date,
  created_at timestamptz not null default now()
);

create table if not exists public.ambassador_marketing_assets (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  asset_type text not null,       -- poster | instagram_post | instagram_story | linkedin_post | video
  file_url text,
  caption_template text,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- UPDATED_AT TRIGGER
-- ---------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_users_updated on public.users;
create trigger trg_users_updated before update on public.users
  for each row execute function public.set_updated_at();

drop trigger if exists trg_referrals_updated on public.ambassador_referrals;
create trigger trg_referrals_updated before update on public.ambassador_referrals
  for each row execute function public.set_updated_at();

-- =====================================================================
-- ROW LEVEL SECURITY
-- =====================================================================
alter table public.users enable row level security;
alter table public.programs enable row level security;
alter table public.assessment_questions enable row level security;
alter table public.assessment_attempts enable row level security;
alter table public.assessment_answers enable row level security;
alter table public.assessment_flags enable row level security;
alter table public.coupons enable row level security;
alter table public.enrollments enable row level security;
alter table public.milestones enable row level security;
alter table public.certificates enable row level security;
alter table public.ambassador_applications enable row level security;
alter table public.ambassadors enable row level security;
alter table public.ambassador_referrals enable row level security;
alter table public.ambassador_campaigns enable row level security;
alter table public.ambassador_campaign_participation enable row level security;
alter table public.ambassador_events enable row level security;
alter table public.ambassador_event_attendance enable row level security;
alter table public.ambassador_challenges enable row level security;
alter table public.ambassador_rewards enable row level security;
alter table public.ambassador_reward_claims enable row level security;
alter table public.ambassador_xp_transactions enable row level security;
alter table public.ambassador_certificates enable row level security;
alter table public.ambassador_marketing_assets enable row level security;

-- Helper: is the current auth.uid() an admin?
create or replace function public.is_admin()
returns boolean as $$
  select exists (
    select 1 from public.users u where u.id = auth.uid() and u.role in ('admin','college_coordinator')
  );
$$ language sql stable security definer;

-- NOTE: the Flask backend talks to Supabase using the SERVICE ROLE key
-- for all privileged/write operations (it does its own auth via
-- Supabase JWT verification + role checks in application code), so
-- these RLS policies are the *defense in depth* layer for any direct
-- PostgREST access using a user's own anon/JWT token.
--
-- CHANGE 2: every "create policy" below is now preceded by a matching
-- "drop policy if exists" so the whole RLS block can be re-run without
-- 42710 "policy already exists" errors. Nothing about who can do what
-- has changed — same policy names, same USING/WITH CHECK logic.

-- users: a user can read/update their own row; admins can read all
drop policy if exists users_select_own on public.users;
create policy users_select_own on public.users for select
  using (auth.uid() = id or public.is_admin());
drop policy if exists users_update_own on public.users;
create policy users_update_own on public.users for update
  using (auth.uid() = id or public.is_admin());
drop policy if exists users_insert_own on public.users;
create policy users_insert_own on public.users for insert
  with check (auth.uid() = id);

-- programs: public read of active programs, admin write
drop policy if exists programs_public_read on public.programs;
create policy programs_public_read on public.programs for select
  using (is_active = true or public.is_admin());
drop policy if exists programs_admin_write on public.programs;
create policy programs_admin_write on public.programs for all
  using (public.is_admin()) with check (public.is_admin());

-- assessment_questions: never directly readable by students (backend
-- uses the service key to serve sanitized questions without the
-- correct_index field); only admins may read/write via PostgREST.
drop policy if exists questions_admin_only on public.assessment_questions;
create policy questions_admin_only on public.assessment_questions for all
  using (public.is_admin()) with check (public.is_admin());

-- assessment_attempts: user can see their own; admin sees all
drop policy if exists attempts_owner on public.assessment_attempts;
create policy attempts_owner on public.assessment_attempts for select
  using (auth.uid() = user_id or public.is_admin());
drop policy if exists attempts_owner_write on public.assessment_attempts;
create policy attempts_owner_write on public.assessment_attempts for insert
  with check (auth.uid() = user_id);
drop policy if exists attempts_owner_update on public.assessment_attempts;
create policy attempts_owner_update on public.assessment_attempts for update
  using (auth.uid() = user_id or public.is_admin());

-- assessment_answers: via attempt ownership
drop policy if exists answers_owner on public.assessment_answers;
create policy answers_owner on public.assessment_answers for select
  using (exists (select 1 from public.assessment_attempts a
                 where a.id = attempt_id and (a.user_id = auth.uid() or public.is_admin())));
drop policy if exists answers_owner_write on public.assessment_answers;
create policy answers_owner_write on public.assessment_answers for insert
  with check (exists (select 1 from public.assessment_attempts a
                       where a.id = attempt_id and a.user_id = auth.uid()));

drop policy if exists flags_owner on public.assessment_flags;
create policy flags_owner on public.assessment_flags for select
  using (exists (select 1 from public.assessment_attempts a
                 where a.id = attempt_id and (a.user_id = auth.uid() or public.is_admin())));
drop policy if exists flags_owner_write on public.assessment_flags;
create policy flags_owner_write on public.assessment_flags for insert
  with check (exists (select 1 from public.assessment_attempts a
                       where a.id = attempt_id and a.user_id = auth.uid()));

-- coupons: owner + admin
drop policy if exists coupons_owner on public.coupons;
create policy coupons_owner on public.coupons for select
  using (auth.uid() = user_id or public.is_admin());
drop policy if exists coupons_admin_write on public.coupons;
create policy coupons_admin_write on public.coupons for all
  using (public.is_admin()) with check (public.is_admin());

-- enrollments: owner + admin
drop policy if exists enrollments_owner on public.enrollments;
create policy enrollments_owner on public.enrollments for select
  using (auth.uid() = user_id or public.is_admin());
drop policy if exists enrollments_owner_write on public.enrollments;
create policy enrollments_owner_write on public.enrollments for insert
  with check (auth.uid() = user_id);
drop policy if exists enrollments_admin_update on public.enrollments;
create policy enrollments_admin_update on public.enrollments for update
  using (public.is_admin());

-- milestones: via enrollment ownership
drop policy if exists milestones_owner on public.milestones;
create policy milestones_owner on public.milestones for select
  using (exists (select 1 from public.enrollments e
                 where e.id = enrollment_id and (e.user_id = auth.uid() or public.is_admin())));
drop policy if exists milestones_admin_write on public.milestones;
create policy milestones_admin_write on public.milestones for all
  using (public.is_admin()) with check (public.is_admin());

-- certificates: owner (for verification, a public read-by-code is
-- handled through the backend's service-key-authenticated endpoint,
-- not direct PostgREST access)
drop policy if exists certificates_owner on public.certificates;
create policy certificates_owner on public.certificates for select
  using (auth.uid() = user_id or public.is_admin());
drop policy if exists certificates_admin_write on public.certificates;
create policy certificates_admin_write on public.certificates for all
  using (public.is_admin()) with check (public.is_admin());

-- ambassador_applications: public insert (apply), admin read/update
drop policy if exists amb_app_public_insert on public.ambassador_applications;
create policy amb_app_public_insert on public.ambassador_applications for insert
  with check (true);
drop policy if exists amb_app_admin_read on public.ambassador_applications;
create policy amb_app_admin_read on public.ambassador_applications for select
  using (public.is_admin());
drop policy if exists amb_app_admin_update on public.ambassador_applications;
create policy amb_app_admin_update on public.ambassador_applications for update
  using (public.is_admin());

-- ambassadors: admin manages; ambassador auth is handled by the Flask
-- backend with its own JWT (not Supabase auth), so PostgREST access to
-- this table is restricted to the service key / admins.
drop policy if exists ambassadors_admin_all on public.ambassadors;
create policy ambassadors_admin_all on public.ambassadors for all
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists amb_referrals_admin_all on public.ambassador_referrals;
create policy amb_referrals_admin_all on public.ambassador_referrals for all
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists amb_campaigns_public_read on public.ambassador_campaigns;
create policy amb_campaigns_public_read on public.ambassador_campaigns for select
  using (is_active = true or public.is_admin());
drop policy if exists amb_campaigns_admin_write on public.ambassador_campaigns;
create policy amb_campaigns_admin_write on public.ambassador_campaigns for all
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists amb_campaign_participation_admin on public.ambassador_campaign_participation;
create policy amb_campaign_participation_admin on public.ambassador_campaign_participation for all
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists amb_events_public_read on public.ambassador_events;
create policy amb_events_public_read on public.ambassador_events for select using (true);
drop policy if exists amb_events_admin_write on public.ambassador_events;
create policy amb_events_admin_write on public.ambassador_events for all
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists amb_attendance_admin on public.ambassador_event_attendance;
create policy amb_attendance_admin on public.ambassador_event_attendance for all
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists amb_challenges_public_read on public.ambassador_challenges;
create policy amb_challenges_public_read on public.ambassador_challenges for select
  using (is_active = true or public.is_admin());
drop policy if exists amb_challenges_admin_write on public.ambassador_challenges;
create policy amb_challenges_admin_write on public.ambassador_challenges for all
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists amb_rewards_public_read on public.ambassador_rewards;
create policy amb_rewards_public_read on public.ambassador_rewards for select
  using (is_active = true or public.is_admin());
drop policy if exists amb_rewards_admin_write on public.ambassador_rewards;
create policy amb_rewards_admin_write on public.ambassador_rewards for all
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists amb_reward_claims_admin on public.ambassador_reward_claims;
create policy amb_reward_claims_admin on public.ambassador_reward_claims for all
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists amb_xp_admin on public.ambassador_xp_transactions;
create policy amb_xp_admin on public.ambassador_xp_transactions for all
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists amb_certificates_admin on public.ambassador_certificates;
create policy amb_certificates_admin on public.ambassador_certificates for all
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists amb_assets_public_read on public.ambassador_marketing_assets;
create policy amb_assets_public_read on public.ambassador_marketing_assets for select using (true);
drop policy if exists amb_assets_admin_write on public.ambassador_marketing_assets;
create policy amb_assets_admin_write on public.ambassador_marketing_assets for all
  using (public.is_admin()) with check (public.is_admin());

-- =====================================================================
-- ATOMIC ENROLLMENT + COUPON REDEMPTION
-- =====================================================================
-- Coupon redemption and enrollment creation must happen together or not
-- at all — never "enrollment succeeds, coupon stays active" or vice
-- versa. A Postgres function body runs as a single transaction, so any
-- `raise exception` here rolls back everything the function has done
-- so far. The Flask backend calls this via supabase-py's .rpc(), which
-- also re-validates coupon ownership/status/expiry *inside* this
-- transaction (with `for update` row locking) so two concurrent
-- requests racing on the same coupon cannot both succeed.
create or replace function public.create_enrollment_with_coupon(
  p_user_id uuid,
  p_program_id uuid,
  p_coupon_id uuid default null,
  p_final_price_cents bigint default null,
  p_milestones jsonb default '[]'::jsonb
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_coupon public.coupons%rowtype;
  v_enrollment public.enrollments%rowtype;
  v_payment_status public.payment_status;
  v_enrollment_id uuid := gen_random_uuid();
  v_milestone jsonb;
  v_idx int := 0;
begin
  if p_coupon_id is not null then
    select * into v_coupon from public.coupons where id = p_coupon_id for update;
    if not found then
      raise exception 'Coupon not found.';
    end if;
    if v_coupon.user_id <> p_user_id then
      raise exception 'This coupon does not belong to you.';
    end if;
    if v_coupon.status <> 'active' then
      raise exception 'This coupon is already %.', v_coupon.status;
    end if;
    if v_coupon.expires_at < now() then
      update public.coupons set status = 'expired' where id = p_coupon_id;
      raise exception 'This coupon has expired.';
    end if;
  end if;

  v_payment_status := case when coalesce(p_final_price_cents, 0) = 0 then 'free' else 'pending' end;

  insert into public.enrollments
    (id, user_id, program_id, coupon_id, final_price_cents, payment_status, enrolled_at)
  values
    (v_enrollment_id, p_user_id, p_program_id, p_coupon_id, coalesce(p_final_price_cents, 0), v_payment_status, now())
  returning * into v_enrollment;

  if p_coupon_id is not null then
    update public.coupons
       set status = 'used', used_at = now(), used_for_enrollment_id = v_enrollment_id
     where id = p_coupon_id;
  end if;

  for v_milestone in select * from jsonb_array_elements(coalesce(p_milestones, '[]'::jsonb))
  loop
    insert into public.milestones (enrollment_id, title, detail, status, sort_order, completed_at)
    values (
      v_enrollment_id,
      v_milestone->>'title',
      v_milestone->>'detail',
      (case when v_idx = 0 then 'complete' else 'pending' end)::public.milestone_status,
      v_idx,
      case when v_idx = 0 then now() else null end
    );
    v_idx := v_idx + 1;
  end loop;

  return to_jsonb(v_enrollment);
end;
$$;

grant execute on function public.create_enrollment_with_coupon(uuid, uuid, uuid, bigint, jsonb) to service_role, authenticated;

-- =====================================================================
-- STORAGE: resumes (PRIVATE) + marketing assets (public read)
-- =====================================================================
-- Run once per project. `resumes` must be private — the backend issues
-- short-lived signed URLs for the authenticated owner rather than ever
-- exposing a public URL. `marketing-assets` is public-read (campus
-- ambassador kit downloads), admin-write only.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'resumes', 'resumes', false, 5242880,
  array['application/pdf','application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
)
on conflict (id) do update set public = false, file_size_limit = 5242880;

insert into storage.buckets (id, name, public)
values ('marketing-assets', 'marketing-assets', true)
on conflict (id) do update set public = true;

-- Resume objects are stored at "<user_id>/<filename>" — a user may only
-- read/write/delete the folder matching their own auth.uid(); admins
-- may read all (e.g. to review applications).
drop policy if exists resumes_owner_select on storage.objects;
create policy resumes_owner_select on storage.objects for select
  using (
    bucket_id = 'resumes'
    and (auth.uid()::text = (storage.foldername(name))[1] or public.is_admin())
  );

drop policy if exists resumes_owner_insert on storage.objects;
create policy resumes_owner_insert on storage.objects for insert
  with check (bucket_id = 'resumes' and auth.uid()::text = (storage.foldername(name))[1]);

drop policy if exists resumes_owner_update on storage.objects;
create policy resumes_owner_update on storage.objects for update
  using (bucket_id = 'resumes' and auth.uid()::text = (storage.foldername(name))[1]);

drop policy if exists resumes_owner_delete on storage.objects;
create policy resumes_owner_delete on storage.objects for delete
  using (bucket_id = 'resumes' and auth.uid()::text = (storage.foldername(name))[1]);

-- Marketing assets: anyone can read (public kit downloads), only admins write.
drop policy if exists marketing_assets_public_read on storage.objects;
create policy marketing_assets_public_read on storage.objects for select
  using (bucket_id = 'marketing-assets');

drop policy if exists marketing_assets_admin_write on storage.objects;
create policy marketing_assets_admin_write on storage.objects for all
  using (bucket_id = 'marketing-assets' and public.is_admin())
  with check (bucket_id = 'marketing-assets' and public.is_admin());

-- =====================================================================
-- SEED DATA (optional — safe to remove)
-- =====================================================================
insert into public.programs (name, slug, description, skills, mentor_title, duration_weeks, mode, base_price_cents, image_url)
values
  ('Full Stack Development', 'full-stack-development', 'Build and ship complete web applications.', 'React, Node.js, PostgreSQL', 'Senior Software Engineer', 8, 'Remote', 999900, null),
  ('Data Science', 'data-science', 'Work with real datasets end to end.', 'Python, Pandas, ML basics', 'Data Science Lead', 8, 'Remote', 999900, null),
  ('UI/UX Design', 'ui-ux-design', 'Design production-ready interfaces.', 'Figma, Design Systems', 'Principal Designer', 6, 'Remote', 999900, null)
on conflict (slug) do nothing;

insert into public.ambassador_rewards (title, requirement, min_xp, min_enrollments)
values
  ('Ambassador Badge', 'Complete your ambassador profile', 0, 0),
  ('Digital Certificate', 'Reach 1,000 XP', 1000, 0),
  ('Merchandise Kit', '10 successful enrollments', 0, 10)
on conflict do nothing;
-- Admin control center (see migrations/2026_12_admin_control_center.sql)
create table if not exists public.ambassador_challenge_assignments (
  id uuid primary key default gen_random_uuid(),
  challenge_id uuid not null references public.ambassador_challenges(id) on delete cascade,
  ambassador_id uuid not null references public.ambassadors(id) on delete cascade,
  assigned_by uuid,
  assigned_at timestamptz default now(),
  status text default 'assigned',
  due_date date,
  unique (challenge_id, ambassador_id)
);
create index if not exists idx_chal_assign_amb on public.ambassador_challenge_assignments(ambassador_id);

create table if not exists public.ambassador_event_assignments (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references public.ambassador_events(id) on delete cascade,
  ambassador_id uuid not null references public.ambassadors(id) on delete cascade,
  assigned_by uuid,
  assigned_at timestamptz default now(),
  unique (event_id, ambassador_id)
);
create index if not exists idx_event_assign_amb on public.ambassador_event_assignments(ambassador_id);

create table if not exists public.admin_action_logs (
  id uuid primary key default gen_random_uuid(),
  admin_user_id uuid,
  action text not null,
  target_type text,
  target_id text,
  details jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_admin_logs_created on public.admin_action_logs(created_at desc);

alter table public.enrollments add column if not exists status text not null default 'active';
alter table public.ambassador_challenges add column if not exists due_date date;
alter table public.ambassador_events add column if not exists status text not null default 'active';
alter table public.enrollments add column if not exists razorpay_order_id text;
alter table public.enrollments add column if not exists razorpay_payment_id text;
create index if not exists idx_enrollments_rzp_order on public.enrollments(razorpay_order_id);
