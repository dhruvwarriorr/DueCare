"""Activity inbox, private resumable deletion, and minimal import suppression."""

from alembic import op

revision = "0004"
down_revision = "0003"

# Frozen SQL; model evolution must use another migration.
STATEMENTS = [
    "\nCREATE TABLE duecare.activity_notifications (\n\tevent_key VARCHAR(200) NOT NULL, \n\tevent_type VARCHAR(30) NOT NULL, \n\ttarget_type VARCHAR(20) NOT NULL, \n\ttarget_id UUID NOT NULL, \n\tmessage VARCHAR(300) NOT NULL, \n\tread_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, event_key)\n)\n\n",
    "CREATE INDEX ix_duecare_activity_notifications_user_id ON duecare.activity_notifications (user_id)",
    "\nCREATE TABLE duecare.suppression_records (\n\tnamespace VARCHAR(64) NOT NULL, \n\tidentity_hash VARCHAR(64) NOT NULL, \n\trestored_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id, namespace, identity_hash)\n)\n\n",
    "CREATE INDEX ix_duecare_suppression_records_user_id ON duecare.suppression_records (user_id)",
    "\nCREATE TABLE duecare.privacy_jobs (\n\tkind VARCHAR(30) NOT NULL, \n\tconnection_id UUID NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tstage VARCHAR(20) NOT NULL, \n\tdata JSONB NOT NULL, \n\terror_code VARCHAR(50), \n\tid UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
    "CREATE INDEX ix_duecare_privacy_jobs_user_id ON duecare.privacy_jobs (user_id)",
    "\nCREATE TABLE duecare_internal.account_deletions (\n\tid UUID NOT NULL, \n\tuser_id UUID, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tstage VARCHAR(20) NOT NULL, \n\terror_code VARCHAR(50), \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcompleted_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tUNIQUE (user_id), \n\tUNIQUE (token_hash)\n)\n\n",
]
OWNED = ["activity_notifications", "suppression_records", "privacy_jobs"]


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
    op.execute("grant select,insert,update,delete on duecare_internal.account_deletions to duecare_runtime")
    op.execute("create index activity_unread on duecare.activity_notifications (user_id,read_at,created_at)")
    op.execute("create index source_record_expiry on duecare.source_records (user_id,expires_at)")
    # The runtime never receives general Auth write privileges. This narrow self-delete function
    # requires both its transaction owner context and a durable account-deletion checkpoint.
    op.execute("""create function duecare_internal.delete_own_auth_account(uid uuid)
        returns void language plpgsql security definer set search_path = '' as $$
        begin
            if uid is distinct from nullif(current_setting('app.user_id',true),'')::uuid
               or not exists (select 1 from duecare_internal.account_deletions d
                   where d.user_id=uid and d.status='pending' and d.stage='auth') then
                raise exception 'Self-deletion checkpoint required';
            end if;
            delete from auth.sessions where user_id=uid;
            delete from auth.identities where user_id=uid;
            delete from auth.users where id=uid;
        end; $$""")
    op.execute("alter function duecare_internal.delete_own_auth_account(uuid) owner to postgres")
    op.execute(
        "revoke all on function duecare_internal.delete_own_auth_account(uuid) from public,anon,authenticated"
    )
    op.execute("grant execute on function duecare_internal.delete_own_auth_account(uuid) to duecare_runtime")


def downgrade():
    op.execute("drop function duecare_internal.delete_own_auth_account(uuid)")
    op.execute("drop index duecare.source_record_expiry")
    op.drop_table("account_deletions", schema="duecare_internal")
    for table in reversed(OWNED):
        op.drop_table(table, schema="duecare")
