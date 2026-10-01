alter table public.enrollments add column if not exists razorpay_order_id text;
alter table public.enrollments add column if not exists razorpay_payment_id text;
create index if not exists idx_enrollments_rzp_order on public.enrollments(razorpay_order_id);
