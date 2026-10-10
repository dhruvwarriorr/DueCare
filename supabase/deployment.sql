-- Hosting infrastructure, separate from the application Alembic schema.
-- Configure duecare_worker_secret and duecare_web_origin in Vault before scheduling.
create extension if not exists pg_cron;
create extension if not exists pg_net;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('duecare-timetable-temp', 'duecare-timetable-temp', false, 10485760,
        array['application/pdf','image/png','image/jpeg','image/webp'])
on conflict (id) do update set public=false, file_size_limit=excluded.file_size_limit,
                              allowed_mime_types=excluded.allowed_mime_types;

create policy duecare_timetable_insert on storage.objects for insert to authenticated
with check (bucket_id='duecare-timetable-temp' and (storage.foldername(name))[1]=(select auth.uid())::text);
create policy duecare_timetable_read on storage.objects for select to authenticated
using (bucket_id='duecare-timetable-temp' and (storage.foldername(name))[1]=(select auth.uid())::text);
create policy duecare_timetable_delete on storage.objects for delete to authenticated
using (bucket_id='duecare-timetable-temp' and (storage.foldername(name))[1]=(select auth.uid())::text);

create or replace function duecare_internal.dispatch_background_jobs()
returns bigint language plpgsql security definer set search_path='' as $$
declare origin text; secret text;
begin
  if not exists(select 1 from duecare_internal.pending_background_jobs()) then return null; end if;
  select decrypted_secret into origin from vault.decrypted_secrets where name='duecare_web_origin';
  select decrypted_secret into secret from vault.decrypted_secrets where name='duecare_worker_secret';
  if origin is null or secret is null then raise exception 'DueCare dispatcher is not configured'; end if;
  return net.http_post(url:=origin || '/internal/jobs/advance',
    headers:=jsonb_build_object('Content-Type','application/json','Authorization','Bearer ' || secret),
    body:='{}'::jsonb, timeout_milliseconds:=180000);
end $$;
revoke all on function duecare_internal.dispatch_background_jobs() from public, anon, authenticated, duecare_runtime;

-- The Edge Function uses its built-in service credential. This narrowly scoped RPC
-- verifies the separate dispatcher secret and exposes only expired temporary paths.
create or replace function public.duecare_expired_timetable_uploads(dispatch_secret text)
returns table(name text) language plpgsql security definer set search_path='' as $$
declare expected text;
begin
  select decrypted_secret into expected from vault.decrypted_secrets where vault.decrypted_secrets.name='duecare_worker_secret';
  if expected is null or dispatch_secret is distinct from expected then
    raise exception 'Unauthorized' using errcode='28000';
  end if;
  return query select o.name from storage.objects o
    where o.bucket_id='duecare-timetable-temp' and o.created_at < now()-interval '1 hour'
    order by o.created_at limit 100;
end $$;
revoke all on function public.duecare_expired_timetable_uploads(text) from public, anon, authenticated;
grant execute on function public.duecare_expired_timetable_uploads(text) to service_role;

create or replace function duecare_internal.clean_timetable_uploads()
returns bigint language plpgsql security definer set search_path='' as $$
declare secret text;
begin
  if not exists(select 1 from storage.objects where bucket_id='duecare-timetable-temp'
                and created_at < now()-interval '1 hour') then return null; end if;
  select decrypted_secret into secret from vault.decrypted_secrets where name='duecare_worker_secret';
  if secret is null then raise exception 'DueCare cleanup is not configured'; end if;
  return net.http_post(
    url:='https://obubxunyrripyyedhwbt.supabase.co/functions/v1/duecare-clean-timetable-uploads',
    headers:=jsonb_build_object('Content-Type','application/json','Authorization','Bearer ' || secret),
    body:='{}'::jsonb, timeout_milliseconds:=30000);
end $$;
revoke all on function duecare_internal.clean_timetable_uploads() from public, anon, authenticated, duecare_runtime;

select cron.schedule('duecare-background-jobs', '* * * * *', 'select duecare_internal.dispatch_background_jobs()');
select cron.schedule('duecare-temporary-upload-cleanup', '*/5 * * * *', 'select duecare_internal.clean_timetable_uploads()');
