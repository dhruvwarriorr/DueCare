"""Mobile push notifications: device tokens, notification choices, and push work discovery."""

from alembic import op

revision = "0007"
down_revision = "0006"

STATEMENTS = [
    """create table duecare.push_devices (
        token varchar(4096) not null,
        platform varchar(20) not null,
        last_seen_at timestamptz not null,
        id uuid not null,
        user_id uuid not null,
        revision integer not null,
        created_at timestamptz not null,
        updated_at timestamptz not null,
        primary key (id),
        unique (user_id, token)
    )""",
    "create index ix_duecare_push_devices_user_id on duecare.push_devices (user_id)",
    """create table duecare.notification_settings (
        user_id uuid not null,
        revision integer not null,
        data jsonb not null,
        pushed_through timestamptz not null,
        task_count integer not null,
        retry_at timestamptz,
        created_at timestamptz not null,
        updated_at timestamptz not null,
        primary key (user_id)
    )""",
    "create index task_owner_updated on duecare.tasks (user_id, updated_at)",
]
OWNED = ["push_devices", "notification_settings"]

# Unchanged job kinds from 0005.
JOBS = """
            select 'account'::text kind, d.user_id owner_id, d.id job_id,
                   0 priority, d.created_at queued_at
            from duecare_internal.account_deletions d
            where d.status <> 'completed' and d.user_id is not null
              and (d.next_retry_at is null or d.next_retry_at <= now())
            union all
            select 'privacy', p.user_id, p.id, 1, p.updated_at
            from duecare.privacy_jobs p
            where p.status <> 'completed'
              and (p.data->>'nextRetryAt' is null or (p.data->>'nextRetryAt')::timestamptz <= now())
              and not exists (select 1 from duecare_internal.account_deletions d
                  where d.user_id=p.user_id and d.status <> 'completed')
            union all
            select 'sync', s.user_id, s.id, 2, s.updated_at
            from duecare.sync_jobs s
            join duecare.connections c on c.id=s.connection_id and c.user_id=s.user_id
            where s.status in ('queued','running','waiting_retry') and c.status='active'
              and c.data->>'privacyJobId' is null
              and (s.lease_expires_at is null or s.lease_expires_at <= now())
              and (s.next_retry_at is null or s.next_retry_at <= now())
              and not exists (select 1 from duecare_internal.account_deletions d
                  where d.user_id=s.user_id and d.status <> 'completed')
            union all
            select 'reprocess', c.user_id, c.id, 2, c.updated_at
            from duecare.connections c
            where c.status='active' and c.data->>'reprocessRequested'='true'
              and c.data->>'privacyJobId' is null
              and not exists (select 1 from duecare.sync_jobs s where s.connection_id=c.id
                  and s.status in ('queued','running','waiting_retry'))
              and not exists (select 1 from duecare_internal.account_deletions d
                  where d.user_id=c.user_id and d.status <> 'completed')"""

# A student with a registered phone whose activity or tasks changed since the last push.
PUSH = """
            union all
            select 'push', n.user_id, n.user_id, 3, n.pushed_through
            from duecare.notification_settings n
            where exists (select 1 from duecare.push_devices p where p.user_id=n.user_id)
              and (n.retry_at is null or n.retry_at <= now())
              and not exists (select 1 from duecare_internal.account_deletions d
                  where d.user_id=n.user_id and d.status <> 'completed')
              and (exists (select 1 from duecare.activity_notifications a
                      where a.user_id=n.user_id and a.created_at > n.pushed_through)
                   or exists (select 1 from duecare.tasks t
                      where t.user_id=n.user_id and t.updated_at > n.pushed_through)
                   or (select count(*) from duecare.tasks t where t.user_id=n.user_id) <> n.task_count)"""


def function(jobs):
    return f"""create or replace function duecare_internal.pending_background_jobs()
        returns table(kind text, owner_id uuid, job_id uuid)
        language sql security definer set search_path = '' as $$
        select q.kind, q.owner_id, q.job_id from ({jobs}
        ) q order by q.priority, q.queued_at, q.job_id limit 100;
        $$"""


def upgrade():
    for statement in STATEMENTS:
        op.execute(statement)
    for table in OWNED:
        op.execute(f"grant select,insert,update,delete on duecare.{table} to duecare_runtime")
        op.execute(f"alter table duecare.{table} enable row level security")
        op.execute(f"alter table duecare.{table} force row level security")
        op.execute(f"""create policy owner on duecare.{table} to duecare_runtime
            using (user_id = nullif(current_setting('app.user_id',true),'')::uuid)
            with check (user_id = nullif(current_setting('app.user_id',true),'')::uuid)""")
    op.execute(function(JOBS + PUSH))


def downgrade():
    op.execute(function(JOBS))
    op.execute("drop index duecare.task_owner_updated")
    for table in reversed(OWNED):
        op.drop_table(table, schema="duecare")
