-- Video proctoring: new violation kinds for the scholarship test (run ONCE in Supabase SQL editor).
alter type public.flag_kind add value if not exists 'phone_detected';
alter type public.flag_kind add value if not exists 'multiple_faces';
alter type public.flag_kind add value if not exists 'head_turned';
alter type public.flag_kind add value if not exists 'no_face';
alter type public.flag_kind add value if not exists 'camera_blocked';
