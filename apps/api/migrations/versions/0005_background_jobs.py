"""Discover durable work for the API worker without exposing source data or credentials."""

from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade():
    op.execute("alter table duecare_internal.account_deletions add column next_retry_at timestamptz")
    # Only the private server role can discover routing IDs across owners. Every actual
    # operation still runs in its owner's RLS context and takes the existing owner/job locks.
    op.execute("""create function duecare_internal.pending_background_jobs()
        returns table(kind text, owner_id uuid, job_id uuid)
        language sql security definer set search_path = '' as $$
        select q.kind, q.owner_id, q.job_id from (
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
                  where d.user_id=c.user_id and d.status <> 'completed')
        ) q order by q.priority, q.queued_at, q.job_id limit 100;
        $$""")
    op.execute("alter function duecare_internal.pending_background_jobs() owner to postgres")
    op.execute(
        "revoke all on function duecare_internal.pending_background_jobs() from public, anon, authenticated"
    )
    op.execute("grant execute on function duecare_internal.pending_background_jobs() to duecare_runtime")


def downgrade():
    op.execute("drop function duecare_internal.pending_background_jobs()")
    op.execute("alter table duecare_internal.account_deletions drop column next_retry_at")
