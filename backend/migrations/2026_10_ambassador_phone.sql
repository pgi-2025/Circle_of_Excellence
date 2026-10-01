-- Adds an editable phone number to ambassadors.
-- Run once in the Supabase SQL editor. Safe to re-run.

alter table public.ambassadors add column if not exists phone text;

-- Backfill existing ambassadors with the phone they gave on their application.
update public.ambassadors a
set phone = app.phone
from public.ambassador_applications app
where a.application_id = app.id
  and a.phone is null
  and app.phone is not null;
