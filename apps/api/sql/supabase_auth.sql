-- Run with a privileged migration connection after Alembic upgrade.
-- This configures access to managed Auth tables without changing their ownership.
-- Supabase-managed Auth tables have RLS enabled without application read policies.
-- Grant only a narrow private SECURITY DEFINER lookup, not bypass privileges to runtime.
-- Execute this setup as the privileged migration role (postgres), never duecare_runtime.
-- Alembic's revision metadata is administrator-only, even in the default schema.
alter table public.alembic_version enable row level security;
revoke all on table public.alembic_version from public, anon, authenticated;

revoke select (id,user_id) on auth.sessions from duecare_runtime;
revoke select (id,email,email_confirmed_at) on auth.users from duecare_runtime;
revoke select (user_id,provider,identity_data) on auth.identities from duecare_runtime;
revoke all on auth.sessions,auth.users,auth.identities from duecare_runtime;
revoke usage on schema auth from duecare_runtime;
create or replace function duecare_internal.lookup_auth_identity(uid uuid,sid uuid)
returns table(id uuid,email text,identity_data jsonb)
language sql stable security definer set search_path = '' as $$
  select u.id,u.email,i.identity_data
  from auth.users u join auth.sessions s on s.user_id=u.id
  join auth.identities i on i.user_id=u.id and i.provider='google'
  where u.id=uid and s.id=sid and u.email_confirmed_at is not null;
$$;
alter function duecare_internal.lookup_auth_identity(uuid,uuid) owner to postgres;
revoke all on function duecare_internal.lookup_auth_identity(uuid,uuid) from public;
grant execute on function duecare_internal.lookup_auth_identity(uuid,uuid) to duecare_runtime;

-- Enable this function in Supabase Authentication > Hooks > Before user created.
-- SECURITY INVOKER; restricted to supabase_auth_admin, never anon/authenticated.
create or replace function duecare_internal.before_user_created(event jsonb)
returns jsonb language plpgsql set search_path = '' as $$
begin
  if lower(coalesce(event->'user'->>'email','')) !~ '^[^@]+@somaiya\.edu$'
     or event->'user'->'app_metadata'->>'provider' is distinct from 'google' then
    return jsonb_build_object('error',jsonb_build_object('http_code',403,
        'message','Use your Somaiya Google account to register.'));
  end if;
  return '{}'::jsonb;
end;
$$;
revoke all on function duecare_internal.before_user_created(jsonb) from public;
grant usage on schema duecare_internal to supabase_auth_admin;
grant execute on function duecare_internal.before_user_created(jsonb) to supabase_auth_admin;
