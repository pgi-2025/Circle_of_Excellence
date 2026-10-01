-- =====================================================================
-- Campus Ambassador PSYCHOMETRIC ASSESSMENT — safe, additive migration.
-- Run once in Supabase SQL editor (idempotent; drops/renames nothing).
-- =====================================================================

-- 1) Candidate status/review columns on the existing applications table
alter table public.ambassador_applications
  add column if not exists flow text not null default 'application',              -- 'application' (legacy) | 'psychometric'
  add column if not exists assessment_status text not null default 'not_required', -- not_required | in_progress | completed
  add column if not exists latest_attempt_id uuid;
create index if not exists idx_amb_app_flow on public.ambassador_applications(flow, assessment_status);

-- 2) Question bank (scoring key lives ONLY here, never sent to the browser)
create table if not exists public.psy_questions (
  id uuid primary key default gen_random_uuid(),
  code text unique not null,
  dimension text not null,          -- communication|leadership|student_relationship|campus_management|responsibility|problem_solving|teamwork_initiative
  topic text,
  question_text text not null,
  options jsonb not null,           -- ["option text", ...]
  option_scores jsonb not null,     -- [1..4, ...] same order as options
  is_active boolean not null default true,
  sort_order int not null default 0,
  created_at timestamptz not null default now()
);

-- 3) Attempts
create table if not exists public.psy_attempts (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.ambassador_applications(id) on delete cascade,
  token_hash text not null,         -- sha256 of the secret attempt token held by the candidate's browser
  status text not null default 'in_progress',   -- in_progress | submitted | expired
  question_ids jsonb not null,
  option_order jsonb not null,      -- {question_id: [original option index per displayed position]}
  time_limit_seconds int not null,
  started_at timestamptz not null default now(),
  expires_at timestamptz not null,
  submitted_at timestamptz,
  violation_count int not null default 0
);
create index if not exists idx_psy_attempts_app on public.psy_attempts(application_id);

-- 4) Answers
create table if not exists public.psy_answers (
  id uuid primary key default gen_random_uuid(),
  attempt_id uuid not null references public.psy_attempts(id) on delete cascade,
  question_id uuid not null references public.psy_questions(id),
  selected_index int not null,      -- position shown to the candidate
  original_index int not null,      -- position in the stored option list
  score numeric,                    -- filled at submit
  answered_at timestamptz not null default now(),
  unique (attempt_id, question_id)
);

-- 5) Anti-cheat violations (server timestamp is authoritative)
create table if not exists public.psy_violations (
  id uuid primary key default gen_random_uuid(),
  attempt_id uuid not null references public.psy_attempts(id) on delete cascade,
  kind text not null,
  detail text,
  client_ts text,
  occurred_at timestamptz not null default now()
);
create index if not exists idx_psy_viol_attempt on public.psy_violations(attempt_id);

-- 6) Reports
create table if not exists public.psy_reports (
  id uuid primary key default gen_random_uuid(),
  attempt_id uuid not null unique references public.psy_attempts(id) on delete cascade,
  application_id uuid not null references public.ambassador_applications(id) on delete cascade,
  overall_score int not null,
  dimension_scores jsonb not null,
  strengths jsonb not null default '[]'::jsonb,
  development_areas jsonb not null default '[]'::jsonb,
  summary text,
  integrity_status text not null,   -- clear | review | flagged
  integrity_notes jsonb not null default '[]'::jsonb,
  violation_count int not null default 0,
  completion_pct int not null default 0,
  share_token text unique not null, -- unguessable public-report slug
  generated_at timestamptz not null default now()
);
create index if not exists idx_psy_reports_app on public.psy_reports(application_id);

-- 7) RLS — same pattern as the rest of the project: the Flask backend uses
--    the service key (bypasses RLS); PostgREST access is admin-only.
alter table public.psy_questions  enable row level security;
alter table public.psy_attempts   enable row level security;
alter table public.psy_answers    enable row level security;
alter table public.psy_violations enable row level security;
alter table public.psy_reports    enable row level security;

drop policy if exists psy_questions_admin  on public.psy_questions;
create policy psy_questions_admin  on public.psy_questions  for all using (public.is_admin()) with check (public.is_admin());
drop policy if exists psy_attempts_admin   on public.psy_attempts;
create policy psy_attempts_admin   on public.psy_attempts   for all using (public.is_admin()) with check (public.is_admin());
drop policy if exists psy_answers_admin    on public.psy_answers;
create policy psy_answers_admin    on public.psy_answers    for all using (public.is_admin()) with check (public.is_admin());
drop policy if exists psy_violations_admin on public.psy_violations;
create policy psy_violations_admin on public.psy_violations for all using (public.is_admin()) with check (public.is_admin());
drop policy if exists psy_reports_admin    on public.psy_reports;
create policy psy_reports_admin    on public.psy_reports    for all using (public.is_admin()) with check (public.is_admin());

-- 8) Seed: 20 scenario-based questions (re-runnable; skips existing codes)
insert into public.psy_questions (code, dimension, topic, question_text, options, option_scores, sort_order) values
  ('PSY01','student_relationship','Student networking','You have just joined a new campus community and know few students outside your own class. You want students from other departments to know and trust you. What do you do first?','["Ask your friends to introduce you to their friends", "Attend clubs and events across departments, introduce yourself, and follow up with people to learn what they care about", "Wait for a campus event and hope people approach you", "Post about your ambassador role in every group chat to get attention quickly"]'::jsonb,'[3, 4, 1, 2]'::jsonb,1),
  ('PSY02','student_relationship','Student relationship','A junior tells you they are nervous about internships and do not know where to start. You have exams next week. What do you do?','["Spend ten minutes now to listen, share two concrete resources, and agree a time to follow up after your exams", "Forward a generic link and move on", "Ask them to message you again after your exams", "Tell them to search online because you are busy"]'::jsonb,'[4, 2, 2, 1]'::jsonb,2),
  ('PSY03','student_relationship','Networking','You want a wide student network but have limited time each week. Which approach gives the best long-term result?','["Stay in regular, genuine contact with active club heads and class representatives who can spread the word", "Add as many people as possible on social media", "Attend many events, collect contacts, and follow up with those who show interest", "Focus only on your close friends"]'::jsonb,'[4, 1, 3, 2]'::jsonb,3),
  ('PSY04','communication','Communication','You must announce an internship program to 150 students in a five-minute slot. Many are only mildly interested. How do you prepare?','["Share a link and let them read it themselves", "Speak confidently and improvise", "Read out the full program brochure", "Open with what is in it for them, use one relatable example, keep it under four minutes, and end with one clear next step"]'::jsonb,'[2, 2, 1, 4]'::jsonb,4),
  ('PSY05','communication','Communication','A student sends an angry message saying the program details you shared were misleading. How do you respond?','["Take it to a private conversation, ask what was unclear, correct the information, and post a clarification if others may be confused", "Defend yourself and point out that they misread it", "Send a short apology and leave it there", "Reply in the group so everyone can see you were right"]'::jsonb,'[4, 1, 2, 1]'::jsonb,5),
  ('PSY06','communication','Communication','You have to explain a multi-step application process to first-year students who are new to such programs. What works best?','["Show the website and walk them through the first step live", "Explain quickly and move on if nobody asks questions", "Use technical terms so you sound credible", "Explain it in three simple steps with an example and check understanding by asking a question"]'::jsonb,'[3, 2, 1, 4]'::jsonb,6),
  ('PSY07','leadership','Leadership','You are asked to lead six volunteers for a campus event. Two of them are far more experienced than you. How do you lead?','["Step back and let the experienced volunteers run it", "Ask a faculty member to decide everyone''s roles", "Set the goal clearly, ask for input, assign roles by strengths, check progress regularly, and give credit", "Assign tasks quickly and insist everything follows your plan"]'::jsonb,'[1, 2, 4, 2]'::jsonb,7),
  ('PSY08','leadership','Leadership','Midway through a campaign a volunteer says the target is unrealistic, and half the team agrees. What do you do?','["Escalate to the program team and wait for instructions", "Push on, because targets are targets", "Lower the target immediately to keep everyone happy", "Listen, review the numbers together, adjust what is unrealistic, and re-commit the team to a clear revised plan"]'::jsonb,'[2, 1, 2, 4]'::jsonb,8),
  ('PSY09','leadership','Leadership','A teammate on your project keeps missing commitments and you are the lead. What is your first step?','["Talk privately to understand the reason, restate expectations, offer support, and agree a check-in", "Quietly take over their tasks and say nothing", "Complain about them to the rest of the team", "Reassign part of their work and explain why"]'::jsonb,'[4, 2, 1, 3]'::jsonb,9),
  ('PSY10','campus_management','Campus management relationship','You want to organise an information session on campus and need the administration''s approval. How do you approach it?','["Prepare a short proposal covering purpose, date, expected attendance and student benefit, meet the concerned coordinator, and follow the official process", "Send a WhatsApp message to the principal", "Ask a faculty member you know to raise it for you and follow their guidance", "Book the hall informally through a friend on staff and announce it"]'::jsonb,'[4, 2, 3, 1]'::jsonb,10),
  ('PSY11','campus_management','Campus management relationship','A head of department is sceptical of external programs and tells you to stop promoting on campus. What do you do?','["Pause promotion and ask the coordinator to guide you on next steps", "Continue quietly without telling them", "Ask about their concerns, share program details and credibility, follow campus rules, and offer to address their doubts", "Argue that students have a right to know about opportunities"]'::jsonb,'[3, 1, 4, 2]'::jsonb,11),
  ('PSY12','campus_management','Event coordination','You are coordinating a 100-student workshop in three days when the venue becomes unavailable. What do you do first?','["Tell participants you will update them soon and search on your own", "Check alternative venues with the campus office, confirm capacity, timing and equipment, inform attendees promptly, and keep a fallback ready", "Wait and see whether the venue frees up", "Cancel and reschedule"]'::jsonb,'[3, 4, 1, 2]'::jsonb,12),
  ('PSY13','responsibility','Reliability','You promised registration data to the program team by Friday, but exam preparation has left you behind on Thursday night. What do you do?','["Message the team after the deadline to explain", "Skip it because nobody will notice", "Submit incomplete data without telling anyone", "Complete the essential parts, and tell the team before the deadline what will be late and when it will arrive"]'::jsonb,'[3, 1, 2, 4]'::jsonb,13),
  ('PSY14','responsibility','Responsibility','You realise you shared a wrong registration deadline with students. What do you do?','["Correct it immediately, notify everyone who saw it, inform the program team, and add a check to avoid repeating it", "Correct it only in the group where someone complained", "Quietly use the correct date in future posts", "Blame the source of the information"]'::jsonb,'[4, 3, 2, 1]'::jsonb,14),
  ('PSY15','responsibility','Reliability','Your role requires a short weekly update to the program team even when nothing dramatic happened. How do you handle it?','["Fix a weekly time and send a concise update with numbers and blockers", "Send a longer update every two weeks", "Send updates when reminded", "Send updates only when something big happens"]'::jsonb,'[4, 3, 1, 2]'::jsonb,15),
  ('PSY16','problem_solving','Problem solving','Only 12 of 60 registered students attended your session. What do you do?','["Conclude that students are not interested", "Ask a few attendees and no-shows what happened, examine timing, promotion and venue, and test a fix at the next session", "Send more reminders next time", "Change the timing and promotion based on your best guess"]'::jsonb,'[1, 4, 2, 3]'::jsonb,16),
  ('PSY17','problem_solving','Problem solving','You must reach 500 students with no budget. What is your plan?','["Wait until a budget is available", "Post on social media and ask friends to share", "Map free channels such as class representatives, clubs, department groups and notice boards, craft a short message, and track which channel performs best", "Message every student personally"]'::jsonb,'[1, 3, 4, 2]'::jsonb,17),
  ('PSY18','problem_solving','Conflict handling','Two club leaders both want to co-host your event and disagree about who leads. What do you do?','["Ask a faculty advisor to decide immediately", "Pick the one you like more", "Meet both, clarify goals and roles, propose a split based on strengths, and agree how decisions will be made", "Let them sort it out themselves"]'::jsonb,'[3, 1, 4, 2]'::jsonb,18),
  ('PSY19','teamwork_initiative','Teamwork','In a team project your idea is faster but a teammate''s idea is more thorough. How do you proceed?','["Hold a quick vote and go with the majority without further discussion", "Insist on your idea", "Give in to avoid conflict", "Compare both against the goal and constraints with the team, combine the best parts, and agree on one plan"]'::jsonb,'[3, 1, 2, 4]'::jsonb,19),
  ('PSY20','teamwork_initiative','Initiative','You notice that many students do not know about upcoming internship opportunities and nobody has asked you to address this. What do you do?','["Ask the program team what they would like and wait for approval", "Propose a small pilot plan to the program team, such as a notice and a short session, run it, and report the results", "Start posting without informing anyone", "Assume the program team will handle it"]'::jsonb,'[3, 4, 2, 1]'::jsonb,20)
on conflict (code) do nothing;
