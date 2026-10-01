-- Admin control center: challenge/event targeting, audit log, enrollment + event status.
-- Safe to re-run.

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
