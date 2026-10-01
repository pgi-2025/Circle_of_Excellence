-- Server-side marker that a student completed the Assessment Registration step.
alter table public.ambassador_referrals add column if not exists assessment_registered_at timestamptz;
