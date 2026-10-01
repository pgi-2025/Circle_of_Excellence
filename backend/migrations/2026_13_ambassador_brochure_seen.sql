-- Tracks whether an ambassador has already been shown the one-time
-- "Ambassador Brochure" welcome popup on the dashboard.
-- Run once in the Supabase SQL editor. Safe to re-run.
-- Existing ambassadors default to false, so they see the popup once on
-- their next login. To skip it for them, uncomment the UPDATE below.

alter table public.ambassadors
  add column if not exists ambassador_brochure_seen boolean not null default false;

-- update public.ambassadors set ambassador_brochure_seen = true;
